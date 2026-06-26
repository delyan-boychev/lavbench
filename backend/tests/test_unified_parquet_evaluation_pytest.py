import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_utils import generate_token
from evaluation_engine import evaluate_predictions, validate_parquet_schema
from models import Challenge, Submission, Task, User, db


class TestUnifiedParquetEvaluation:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, app_ctx, app):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()
        self.client = self.app.test_client()
        self.seed_basic_data()
        self.temp_test_dir = tempfile.mkdtemp()
        self._upload_dir = self.app.config["UPLOAD_FOLDER"]
        self._temp_test_dir = self.temp_test_dir

    def seed_basic_data(self):
        self.admin = User(
            username="test_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-001",
        )
        db.session.add(self.admin)

        self.challenge = Challenge(
            title="IMDB Sentiment Classification",
            description="Predict sentiment of reviews.",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.commit()

        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Stellar-Voyager-101",
            challenge_id=self.challenge.id,
        )
        db.session.add(self.competitor)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def get_auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def get_default_task_data(self):
        return {
            "title": "Unified Task 1",
            "description": "Modality test",
            "metrics_config": json.dumps(
                {
                    "accuracy": {"weight": 0.5, "higher_is_better": True},
                    "f1_macro": {"weight": 0.5, "higher_is_better": True},
                }
            ),
            "baseline_notebook": (io.BytesIO(b"# Baseline"), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b"# Solution"), "solution.ipynb"),
        }

    @patch("subprocess.run")
    def test_celery_evaluate_submission_unified_parquet(self, mock_subproc):
        from tasks import evaluate_submission

        task = Task(
            challenge_id=self.challenge.id,
            title="Class Task",
            metrics_config=json.dumps({"accuracy": {"weight": 1.0, "higher_is_better": True}}),
            public_eval_percentage=50,
        )
        db.session.add(task)
        db.session.commit()

        task_dir = os.path.join(self._upload_dir, f"task_{task.id}")
        os.makedirs(task_dir, exist_ok=True)
        labels_parquet_path = os.path.join(task_dir, "labels.parquet")

        df_labels = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]})
        df_labels.to_parquet(labels_parquet_path)

        task.files = json.dumps(
            [
                {
                    "filename": "labels.parquet",
                    "saved_name": "labels.parquet",
                    "size_bytes": 1000,
                }
            ]
        )
        db.session.commit()

        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=task.id,
            status="queued",
        )
        sub.code_cells = json.dumps(["# Write output\nprint('Done!')"])
        db.session.add(sub)
        db.session.commit()

        original_mkdtemp = tempfile.mkdtemp
        temp_dir_holder = []

        def mock_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            temp_dir_holder.append(td)
            df_sub = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 0]})
            df_sub.to_parquet(os.path.join(td, "submission.parquet"))
            return td

        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("tempfile.mkdtemp", side_effect=mock_mkdtemp),
            patch(
                "task_modules.submission_runner.run_command_streaming",
                return_value=(0, "", "", False),
            ),
            patch("tasks.app", self.app),
        ):
            res = evaluate_submission(sub.id)
            sub_reloaded = db.session.get(Submission, sub.id)
            db.session.refresh(sub_reloaded)
            print("\n\nSTATUS:", sub_reloaded.status)
            print("LOGS:", sub_reloaded.logs, "\n\n")
            assert "evaluated with status completed" in res

        db.session.refresh(sub)
        assert sub.status == "completed"
        assert sub.public_score == pytest.approx(1.0)
        assert sub.private_score == pytest.approx(0.5)
        assert sub.metrics_payload_public == {"accuracy": 1.0}
        assert sub.metrics_payload_private == {"accuracy": 0.5}

        def mock_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            df_sub = pd.DataFrame({"not_id": [1, 2], "value": [0, 1]})
            df_sub.to_parquet(os.path.join(td, "submission.parquet"))
            return td

        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        sub.status = "queued"
        db.session.commit()

        with (
            patch("tempfile.mkdtemp", side_effect=mock_mkdtemp),
            patch(
                "task_modules.submission_runner.run_command_streaming",
                return_value=(0, "", "", False),
            ),
            patch("tasks.app", self.app),
        ):
            res = evaluate_submission(sub.id)

        db.session.refresh(sub)
        assert sub.status == "failed"
        assert "Submission schema validation failed" in sub.logs


class TestEvalPredictionsAllMetricPaths:
    """
    Comprehensive tests hitting every metric branch inside evaluate_predictions
    to maximise code coverage of evaluation_engine.py.
    """

    def _df(self, ids, labels, preds):
        return (
            pd.DataFrame({"id": ids, "label": labels}),
            pd.DataFrame({"id": ids, "prediction": preds}),
        )

    # ── Classification ────────────────────────────────────────────────────────

    def test_accuracy_balanced_option(self):
        df_l, df_s = self._df([1, 2, 3, 4], [0, 1, 0, 1], [0, 1, 0, 0])
        res = evaluate_predictions(
            df_s, df_l, {"accuracy": {"weight": 1.0, "options": {"balanced": "true"}}}
        )
        assert "accuracy" in res
        assert 0.0 <= res["accuracy"] <= 1.0

    def test_accuracy_invalid_inputs_fallback(self):
        """Accuracy with non-matching shape → fallback 0.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        res = evaluate_predictions(df_s, df_l, {"accuracy": {"weight": 1.0}})
        assert "accuracy" in res

    def test_precision_metric(self):
        df_l, df_s = self._df([1, 2, 3, 4], [0, 1, 0, 1], [0, 1, 0, 1])
        res = evaluate_predictions(df_s, df_l, {"precision": {"weight": 1.0}})
        assert "precision" in res

    def test_recall_classification_metric(self):
        df_l, df_s = self._df([1, 2, 3, 4], [0, 1, 0, 1], [0, 1, 0, 1])
        res = evaluate_predictions(df_s, df_l, {"recall": {"weight": 1.0}})
        assert "recall" in res

    def test_cohen_kappa_metric(self):
        df_l, df_s = self._df([1, 2, 3, 4], [0, 1, 0, 1], [0, 1, 0, 0])
        res = evaluate_predictions(df_s, df_l, {"cohen_kappa": {"weight": 1.0}})
        assert "cohen_kappa" in res

    def test_matthews_corrcoef_metric(self):
        df_l, df_s = self._df([1, 2, 3, 4], [0, 1, 0, 1], [0, 1, 0, 0])
        res = evaluate_predictions(df_s, df_l, {"matthews_corrcoef": {"weight": 1.0}})
        assert "matthews_corrcoef" in res

    # ── Probabilistic ─────────────────────────────────────────────────────────

    def test_auc_roc_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0.1, 0.9, 0.2, 0.8]})
        res = evaluate_predictions(df_s, df_l, {"auc_roc": {"weight": 1.0}})
        assert "auc_roc" in res
        assert res["auc_roc"] > 0.5

    def test_auc_roc_bad_input_returns_fallback(self):
        """Multiclass labels with multi_class='raise' (default) → ValueError → fallback 0.5."""
        # 3-class labels with 1D probability scores
        # triggers ValueError (multi_class='raise' default)

        df_l = pd.DataFrame({"id": [1, 2, 3], "label": [0, 1, 2]})
        df_s = pd.DataFrame({"id": [1, 2, 3], "prediction": [0.1, 0.5, 0.9]})
        res = evaluate_predictions(df_s, df_l, {"auc_roc": {"weight": 1.0}})
        # Exception is caught → fallback 0.5
        assert res["auc_roc"] == pytest.approx(0.5)

    def test_logloss_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0.1, 0.9, 0.2, 0.8]})
        res = evaluate_predictions(df_s, df_l, {"logloss": {"weight": 1.0}})
        assert "logloss" in res
        assert res["logloss"] < 5.0

    def test_logloss_invalid_input_returns_fallback(self):
        """String predictions → logloss fails → fallback 10.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["a", "b"]})
        res = evaluate_predictions(df_s, df_l, {"logloss": {"weight": 1.0}})
        assert res["logloss"] == pytest.approx(10.0)

    def test_brier_score_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0.1, 0.9, 0.2, 0.8]})
        res = evaluate_predictions(df_s, df_l, {"brier_score": {"weight": 1.0}})
        assert "brier_score" in res
        assert 0.0 <= res["brier_score"] <= 1.0

    def test_brier_score_invalid_returns_fallback(self):
        """Non-numeric predictions → brier_score fails → fallback 1.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": ["x", "y"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["a", "b"]})
        res = evaluate_predictions(df_s, df_l, {"brier_score": {"weight": 1.0}})
        assert res["brier_score"] == pytest.approx(1.0)

    # ── Regression ────────────────────────────────────────────────────────────

    def test_rmse_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"rmse": {"weight": 1.0}})
        assert "rmse" in res
        assert res["rmse"] < 0.5

    def test_mse_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"mse": {"weight": 1.0}})
        assert "mse" in res

    def test_mae_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"mae": {"weight": 1.0}})
        assert "mae" in res

    def test_r_squared_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"r_squared": {"weight": 1.0}})
        assert "r_squared" in res
        assert res["r_squared"] > 0.9

    def test_mape_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"mape": {"weight": 1.0}})
        assert "mape" in res

    def test_median_ae_metric(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1.0, 2.0, 3.0, 4.0]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1.1, 1.9, 3.1, 3.9]})
        res = evaluate_predictions(df_s, df_l, {"median_ae": {"weight": 1.0}})
        assert "median_ae" in res

    def test_rmse_with_shape_option(self):
        """Cover the shape-based RMSE code path."""
        df_l = pd.DataFrame({"id": [1, 2], "label": [[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]]})
        df_s = pd.DataFrame(
            {"id": [1, 2], "prediction": [[0.1, 1.1, 2.1, 3.1], [4.1, 5.1, 6.1, 7.1]]}
        )
        res = evaluate_predictions(
            df_s, df_l, {"rmse": {"weight": 1.0, "options": {"shape": "2,2"}}}
        )
        assert "rmse" in res

    def test_mse_with_shape_option(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]]})
        df_s = pd.DataFrame(
            {"id": [1, 2], "prediction": [[0.1, 1.1, 2.1, 3.1], [4.1, 5.1, 6.1, 7.1]]}
        )
        res = evaluate_predictions(
            df_s, df_l, {"mse": {"weight": 1.0, "options": {"shape": "2,2"}}}
        )
        assert "mse" in res

    def test_mae_with_shape_option(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [[0.0, 1.0, 2.0, 3.0], [4.0, 5.0, 6.0, 7.0]]})
        df_s = pd.DataFrame(
            {"id": [1, 2], "prediction": [[0.1, 1.1, 2.1, 3.1], [4.1, 5.1, 6.1, 7.1]]}
        )
        res = evaluate_predictions(
            df_s, df_l, {"mae": {"weight": 1.0, "options": {"shape": "2,2"}}}
        )
        assert "mae" in res

    def test_rmse_with_invalid_shape_returns_fallback(self):
        """An impossible reshape returns fallback 999.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": [[0.0, 1.0], [2.0, 3.0]]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [[0.1, 1.1], [2.1, 3.1]]})
        res = evaluate_predictions(
            df_s, df_l, {"rmse": {"weight": 1.0, "options": {"shape": "9999,9999"}}}
        )
        assert "rmse" in res
        assert res["rmse"] == 999.0

    def test_regression_string_inputs_returns_fallback(self):
        """String labels passed to MSE → fallback 999.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": ["cat", "dog"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["cat", "mouse"]})
        res = evaluate_predictions(df_s, df_l, {"mse": {"weight": 1.0}})
        assert res["mse"] == 999.0

    def test_r_squared_invalid_inputs_returns_fallback(self):
        """Non-numeric inputs to r2_score → fallback 0.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": ["a", "b"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["a", "c"]})
        res = evaluate_predictions(df_s, df_l, {"r_squared": {"weight": 1.0}})
        assert res["r_squared"] == pytest.approx(0.0)

    def test_mape_zero_in_denominator_returns_fallback(self):
        """Zero true values causes MAPE division by zero → fallback 999.0."""
        df_l = pd.DataFrame({"id": [1, 2], "label": ["x", "y"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["x", "y"]})
        res = evaluate_predictions(df_s, df_l, {"mape": {"weight": 1.0}})
        assert res["mape"] == pytest.approx(999.0)

    def test_median_ae_invalid_inputs_returns_fallback(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["x", "y"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["a", "b"]})
        res = evaluate_predictions(df_s, df_l, {"median_ae": {"weight": 1.0}})
        assert res["median_ae"] == pytest.approx(999.0)

    # ── NER / Tagging (seqeval fallback) ────────────────────────────────────

    def test_seqeval_f1_with_nested_lists(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [["B-PER", "O"], ["O", "B-ORG"]]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [["B-PER", "O"], ["O", "B-LOC"]]})
        res = evaluate_predictions(df_s, df_l, {"seqeval_f1": {"weight": 1.0}})
        assert "seqeval_f1" in res

    def test_seqeval_precision_with_nested_lists(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [["B-PER", "O"], ["O", "B-ORG"]]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [["B-PER", "O"], ["O", "B-ORG"]]})
        res = evaluate_predictions(df_s, df_l, {"seqeval_precision": {"weight": 1.0}})
        assert "seqeval_precision" in res

    def test_seqeval_recall_with_nested_lists(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [["B-PER", "O"], ["O", "B-ORG"]]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [["B-PER", "O"], ["O", "B-ORG"]]})
        res = evaluate_predictions(df_s, df_l, {"seqeval_recall": {"weight": 1.0}})
        assert "seqeval_recall" in res

    def test_seqeval_f1_empty_sequences_returns_zero(self):
        """Empty sequence lists → min_len == 0 → val = 0.0."""
        df_l = pd.DataFrame({"id": [1], "label": [[]]})
        df_s = pd.DataFrame({"id": [1], "prediction": [[]]})
        res = evaluate_predictions(df_s, df_l, {"seqeval_f1": {"weight": 1.0}})
        assert res["seqeval_f1"] == 0.0

    def test_seqeval_flat_scalars_are_wrapped(self):
        """Non-list scalars should be wrapped as [x] and still work."""
        df_l = pd.DataFrame({"id": [1, 2], "label": ["B-PER", "O"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["B-PER", "O"]})
        res = evaluate_predictions(df_s, df_l, {"seqeval_f1": {"weight": 1.0}})
        assert "seqeval_f1" in res

    # ── Generative NLP ────────────────────────────────────────────────────────

    def test_bleu_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["the cat sat on the mat", "hello world"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["the cat sat on the mat", "hello earth"]})
        res = evaluate_predictions(df_s, df_l, {"bleu": {"weight": 1.0}})
        assert "bleu" in res
        assert 0.0 <= res["bleu"] <= 1.0

    def test_rouge_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["the cat sat on the mat", "hello world"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["the cat sat on the mat", "hello world"]})
        res = evaluate_predictions(df_s, df_l, {"rouge": {"weight": 1.0}})
        assert "rouge" in res

    def test_rouge_l_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["the cat sat on the mat", "hello world"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["the cat sat on the mat", "hello earth"]})
        res = evaluate_predictions(df_s, df_l, {"rouge_l": {"weight": 1.0}})
        assert "rouge_l" in res

    def test_meteor_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["the cat sat on the mat", "hello world"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["the cat sat on the mat", "hello earth"]})
        res = evaluate_predictions(df_s, df_l, {"meteor": {"weight": 1.0}})
        assert "meteor" in res

    def test_chrf_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["hello world", "foo bar"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["hello world", "foo baz"]})
        res = evaluate_predictions(df_s, df_l, {"chrf": {"weight": 1.0}})
        assert "chrf" in res

    def test_ter_metric(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["hello world", "foo bar"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["hello world", "foo baz"]})
        res = evaluate_predictions(df_s, df_l, {"ter": {"weight": 1.0}})
        assert "ter" in res

    # ── QA Extractive ─────────────────────────────────────────────────────────

    def test_exact_match_partial(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": ["Paris", "London"]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": ["Paris", "Berlin"]})
        res = evaluate_predictions(df_s, df_l, {"exact_match": {"weight": 1.0}})
        assert res["exact_match"] == pytest.approx(0.5)

    def test_exact_match_case_insensitive(self):
        df_l = pd.DataFrame({"id": [1], "label": ["PARIS"]})
        df_s = pd.DataFrame({"id": [1], "prediction": ["paris"]})
        res = evaluate_predictions(df_s, df_l, {"exact_match": {"weight": 1.0}})
        assert res["exact_match"] == pytest.approx(1.0)

    def test_exact_match_empty_strings(self):
        df_l = pd.DataFrame({"id": [1], "label": [""]})
        df_s = pd.DataFrame({"id": [1], "prediction": [""]})
        res = evaluate_predictions(df_s, df_l, {"exact_match": {"weight": 1.0}})
        assert res["exact_match"] == pytest.approx(1.0)

    # ── CV Object Detection ────────────────────────────────────────────────────

    def _boxes(self):
        return [
            {
                "label": "cat",
                "x_min": 0.1,
                "y_min": 0.1,
                "x_max": 0.3,
                "y_max": 0.3,
                "score": 1.0,
            }
        ]

    def test_map_50_perfect_detection(self):
        boxes = self._boxes()
        df_l = pd.DataFrame({"id": [1, 2], "label": [boxes, boxes]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [boxes, boxes]})
        res = evaluate_predictions(df_s, df_l, {"map_50": {"weight": 1.0}})
        assert "map_50" in res
        assert res["map_50"] >= 0.0

    def test_map_75_metric(self):
        boxes = self._boxes()
        df_l = pd.DataFrame({"id": [1], "label": [boxes]})
        df_s = pd.DataFrame({"id": [1], "prediction": [boxes]})
        res = evaluate_predictions(df_s, df_l, {"map_75": {"weight": 1.0}})
        assert "map_75" in res

    def test_map_50_95_metric(self):
        boxes = self._boxes()
        df_l = pd.DataFrame({"id": [1], "label": [boxes]})
        df_s = pd.DataFrame({"id": [1], "prediction": [boxes]})
        res = evaluate_predictions(df_s, df_l, {"map_50_95": {"weight": 1.0}})
        assert "map_50_95" in res

    def test_recall_with_box_dict_inputs_dispatches_to_detection(self):
        """After the fix, list-of-dict inputs correctly reach the box-recall branch
        and return 1.0 when prediction boxes match ground-truth boxes."""
        boxes = [{"label": "cat", "x_min": 0.1, "y_min": 0.1, "x_max": 0.3, "y_max": 0.3}]
        df_l = pd.DataFrame({"id": [1], "label": [boxes]})
        df_s = pd.DataFrame({"id": [1], "prediction": [boxes]})
        res = evaluate_predictions(df_s, df_l, {"recall": {"weight": 1.0}})
        assert "recall" in res
        # Box recall: perfect match at IoU>=0.5 → 1.0
        assert res["recall"] == pytest.approx(1.0)

    def test_recall_with_empty_ground_truth_list_is_perfect(self):
        """Box recall: empty ground truth → recall 1.0 (nothing to miss)."""
        df_l = pd.DataFrame({"id": [1], "label": [[]]})
        df_s = pd.DataFrame({"id": [1], "prediction": [[]]})
        res = evaluate_predictions(df_s, df_l, {"recall": {"weight": 1.0}})
        assert res["recall"] == pytest.approx(1.0)

    def test_recall_with_no_predictions_is_zero(self):
        """Box recall: non-empty ground truth, empty predictions → recall 0.0."""
        boxes = [{"label": "cat", "x_min": 0.1, "y_min": 0.1, "x_max": 0.3, "y_max": 0.3}]
        df_l = pd.DataFrame({"id": [1], "label": [boxes]})
        df_s = pd.DataFrame({"id": [1], "prediction": [[]]})
        res = evaluate_predictions(df_s, df_l, {"recall": {"weight": 1.0}})
        assert res["recall"] == pytest.approx(0.0)

    # ── CV Segmentation ────────────────────────────────────────────────────────

    def test_mean_iou_perfect(self):
        mask = bytes([0, 255, 0, 255])
        df_l = pd.DataFrame({"id": [1, 2], "label": [mask, mask]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [mask, mask]})
        res = evaluate_predictions(df_s, df_l, {"mean_iou": {"weight": 1.0}})
        assert res["mean_iou"] == pytest.approx(1.0)

    def test_mean_iou_empty_mask(self):
        df_l = pd.DataFrame({"id": [1], "label": [b""]})
        df_s = pd.DataFrame({"id": [1], "prediction": [b""]})
        res = evaluate_predictions(df_s, df_l, {"mean_iou": {"weight": 1.0}})
        assert res["mean_iou"] == pytest.approx(0.0)

    def test_dice_perfect(self):
        mask = bytes([0, 255, 0, 255])
        df_l = pd.DataFrame({"id": [1], "label": [mask]})
        df_s = pd.DataFrame({"id": [1], "prediction": [mask]})
        res = evaluate_predictions(df_s, df_l, {"dice": {"weight": 1.0}})
        assert res["dice"] == pytest.approx(1.0)

    def test_dice_empty_mask(self):
        df_l = pd.DataFrame({"id": [1], "label": [b""]})
        df_s = pd.DataFrame({"id": [1], "prediction": [b""]})
        res = evaluate_predictions(df_s, df_l, {"dice": {"weight": 1.0}})
        assert res["dice"] == pytest.approx(0.0)

    def test_pixel_accuracy_perfect(self):
        mask = bytes([0, 255, 0, 255])
        df_l = pd.DataFrame({"id": [1], "label": [mask]})
        df_s = pd.DataFrame({"id": [1], "prediction": [mask]})
        res = evaluate_predictions(df_s, df_l, {"pixel_accuracy": {"weight": 1.0}})
        assert res["pixel_accuracy"] == pytest.approx(1.0)

    def test_pixel_accuracy_empty_returns_zero(self):
        df_l = pd.DataFrame({"id": [1], "label": [b""]})
        df_s = pd.DataFrame({"id": [1], "prediction": [b""]})
        res = evaluate_predictions(df_s, df_l, {"pixel_accuracy": {"weight": 1.0}})
        assert res["pixel_accuracy"] == pytest.approx(0.0)

    # ── Keypoints ──────────────────────────────────────────────────────────────

    def test_oks_perfect_keypoints(self):
        kps = [[0.5, 0.5], [0.3, 0.3]]
        df_l = pd.DataFrame({"id": [1, 2], "label": [kps, kps]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [kps, kps]})
        res = evaluate_predictions(df_s, df_l, {"oks": {"weight": 1.0}})
        assert "oks" in res
        assert res["oks"] == pytest.approx(1.0)

    def test_oks_mismatched_keypoint_count(self):
        """Keypoint count mismatch → 0.0 per sample."""
        kps_true = [[0.5, 0.5], [0.3, 0.3]]
        kps_pred = [[0.5, 0.5]]
        df_l = pd.DataFrame({"id": [1], "label": [kps_true]})
        df_s = pd.DataFrame({"id": [1], "prediction": [kps_pred]})
        res = evaluate_predictions(df_s, df_l, {"oks": {"weight": 1.0}})
        assert res["oks"] == pytest.approx(0.0)

    def test_pck_perfect_keypoints(self):
        kps = [[0.5, 0.5], [0.3, 0.3]]
        df_l = pd.DataFrame({"id": [1], "label": [kps]})
        df_s = pd.DataFrame({"id": [1], "prediction": [kps]})
        res = evaluate_predictions(df_s, df_l, {"pck": {"weight": 1.0}})
        assert res["pck"] == pytest.approx(1.0)

    def test_pck_custom_threshold(self):
        """Very tight threshold → distant keypoints fail."""
        kps_true = [[0.5, 0.5]]
        kps_pred = [[0.9, 0.9]]  # Far from true
        df_l = pd.DataFrame({"id": [1], "label": [kps_true]})
        df_s = pd.DataFrame({"id": [1], "prediction": [kps_pred]})
        res = evaluate_predictions(
            df_s, df_l, {"pck": {"weight": 1.0, "options": {"threshold": 0.001}}}
        )
        assert "pck" in res
        assert res["pck"] == pytest.approx(0.0)

    # ── Image Quality ──────────────────────────────────────────────────────────

    def test_psnr_identical_arrays(self):
        """Identical bytes → MSE == 0 → PSNR 100.0."""
        raw = bytes([100] * 16)
        df_l = pd.DataFrame({"id": [1], "label": [raw]})
        df_s = pd.DataFrame({"id": [1], "prediction": [raw]})
        res = evaluate_predictions(df_s, df_l, {"psnr": {"weight": 1.0}})
        assert "psnr" in res
        assert res["psnr"] == pytest.approx(100.0)

    def test_ssim_byte_arrays(self):
        """SSIM with raw bytes (PIL unavailable) uses NCC fallback."""
        raw = bytes([100] * 4)
        df_l = pd.DataFrame({"id": [1], "label": [raw]})
        df_s = pd.DataFrame({"id": [1], "prediction": [raw]})
        res = evaluate_predictions(df_s, df_l, {"ssim": {"weight": 1.0}})
        assert "ssim" in res

    # ── Audio Quality ──────────────────────────────────────────────────────────

    def test_snr_identical_signal(self):
        """Identical signal → noise power == 0 → SNR 100.0."""
        data = np.array([1000, 2000, 1000, 2000], dtype=np.int16).tobytes()
        df_l = pd.DataFrame({"id": [1], "label": [data]})
        df_s = pd.DataFrame({"id": [1], "prediction": [data]})
        res = evaluate_predictions(df_s, df_l, {"snr": {"weight": 1.0}})
        assert "snr" in res
        assert res["snr"] == pytest.approx(100.0)

    def test_snr_empty_signal_returns_zero(self):
        df_l = pd.DataFrame({"id": [1], "label": [b""]})
        df_s = pd.DataFrame({"id": [1], "prediction": [b""]})
        res = evaluate_predictions(df_s, df_l, {"snr": {"weight": 1.0}})
        assert res["snr"] == pytest.approx(0.0)

    def test_mel_lsd_identical_signal(self):
        data = np.array([1000, 2000, 1000, 2000], dtype=np.int16).tobytes()
        df_l = pd.DataFrame({"id": [1], "label": [data]})
        df_s = pd.DataFrame({"id": [1], "prediction": [data]})
        res = evaluate_predictions(df_s, df_l, {"mel_lsd": {"weight": 1.0}})
        assert "mel_lsd" in res

    def test_si_sdr_metric(self):
        """si_sdr is computed as compute_audio_snr + 1.2."""
        data = np.array([1000, 2000, 1000, 2000], dtype=np.int16).tobytes()
        df_l = pd.DataFrame({"id": [1], "label": [data]})
        df_s = pd.DataFrame({"id": [1], "prediction": [data]})
        res = evaluate_predictions(df_s, df_l, {"si_sdr": {"weight": 1.0}})
        assert "si_sdr" in res
        assert res["si_sdr"] > 50.0  # SNR 100 + 1.2

    # ── Clustering ─────────────────────────────────────────────────────────────

    def test_adjusted_rand_index_perfect(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4, 5, 6], "label": [0, 0, 1, 1, 2, 2]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4, 5, 6], "prediction": [0, 0, 1, 1, 2, 2]})
        res = evaluate_predictions(df_s, df_l, {"adjusted_rand_index": {"weight": 1.0}})
        assert res["adjusted_rand_index"] == pytest.approx(1.0)

    def test_clustering_inverted_labels_still_perfect_ari(self):
        """Cluster assignment is symmetric — inverted labels still yield ARI=1."""
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 0, 1, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [1, 1, 0, 0]})
        res = evaluate_predictions(df_s, df_l, {"adjusted_rand_index": {"weight": 1.0}})
        assert res["adjusted_rand_index"] == pytest.approx(1.0)

    def test_normalized_mutual_info_perfect(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 0, 1, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0, 0, 1, 1]})
        res = evaluate_predictions(df_s, df_l, {"normalized_mutual_info": {"weight": 1.0}})
        assert res["normalized_mutual_info"] == pytest.approx(1.0)

    def test_adjusted_mutual_info_perfect(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 0, 1, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0, 0, 1, 1]})
        res = evaluate_predictions(df_s, df_l, {"adjusted_mutual_info": {"weight": 1.0}})
        assert res["adjusted_mutual_info"] == pytest.approx(1.0)

    def test_v_measure_perfect(self):
        df_l = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 0, 1, 1]})
        df_s = pd.DataFrame({"id": [1, 2, 3, 4], "prediction": [0, 0, 1, 1]})
        res = evaluate_predictions(df_s, df_l, {"v_measure": {"weight": 1.0}})
        assert res["v_measure"] == pytest.approx(1.0)

    # ── Retrieval (query_id path) ─────────────────────────────────────────────

    def test_retrieval_ndcg_k_explicit_k(self):
        df_l = pd.DataFrame({"query_id": [1, 1, 2, 2], "doc_id": ["a", "b", "c", "d"]})
        df_s = pd.DataFrame(
            {
                "query_id": [1, 1, 2, 2],
                "doc_id": ["a", "b", "c", "d"],
                "score": [1.0, 0.8, 0.9, 0.7],
            }
        )
        res = evaluate_predictions(df_s, df_l, {"ndcg_k": {"weight": 1.0, "options": {"k": 5}}})
        assert "ndcg_k" in res
        assert res["ndcg_k"] == pytest.approx(1.0)

    def test_retrieval_recall_k_explicit_k(self):
        df_l = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "b"]})
        df_s = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "b"], "score": [1.0, 0.8]})
        res = evaluate_predictions(df_s, df_l, {"recall_k": {"weight": 1.0, "options": {"k": 5}}})
        assert "recall_k" in res
        assert res["recall_k"] == pytest.approx(1.0)

    def test_retrieval_mrr(self):
        df_l = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "b"]})
        df_s = pd.DataFrame({"query_id": [1, 1], "doc_id": ["a", "b"], "score": [1.0, 0.8]})
        res = evaluate_predictions(df_s, df_l, {"mrr": {"weight": 1.0}})
        assert "mrr" in res
        assert res["mrr"] == pytest.approx(1.0)

    def test_retrieval_ndcg_k_parsed_from_metric_name(self):
        """ndcg_10 as metric name parses k=10 automatically."""
        df_l = pd.DataFrame({"query_id": [1], "doc_id": ["a"]})
        df_s = pd.DataFrame({"query_id": [1], "doc_id": ["a"], "score": [1.0]})
        res = evaluate_predictions(df_s, df_l, {"ndcg_10": {"weight": 1.0}})
        assert "ndcg_10" in res

    def test_retrieval_recall_k_parsed_from_metric_name(self):
        """recall_5 as metric name parses k=5 automatically."""
        df_l = pd.DataFrame({"query_id": [1], "doc_id": ["a"]})
        df_s = pd.DataFrame({"query_id": [1], "doc_id": ["a"], "score": [1.0]})
        res = evaluate_predictions(df_s, df_l, {"recall_5": {"weight": 1.0}})
        assert "recall_5" in res

    def test_retrieval_k_option_invalid_string_falls_back(self):
        """Non-integer k option string falls back to default k=10 gracefully."""
        df_l = pd.DataFrame({"query_id": [1], "doc_id": ["a"]})
        df_s = pd.DataFrame({"query_id": [1], "doc_id": ["a"], "score": [1.0]})
        res = evaluate_predictions(
            df_s, df_l, {"ndcg_k": {"weight": 1.0, "options": {"k": "not_a_number"}}}
        )
        assert "ndcg_k" in res

    # ── Custom column logic ────────────────────────────────────────────────────

    def test_custom_column_missing_from_submission_returns_zero(self):
        """Specified column not in submission df → value 0.0, no crash."""
        df_l = pd.DataFrame({"id": [1, 2], "target_col": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "other_col": [0, 1]})
        res = evaluate_predictions(
            df_s,
            df_l,
            {"accuracy": {"weight": 1.0, "options": {"column": "target_col"}}},
        )
        assert res["accuracy"] == pytest.approx(0.0)

    def test_custom_column_missing_from_labels_returns_zero(self):
        """Specified column not in labels df → value 0.0, no crash."""
        df_l = pd.DataFrame({"id": [1, 2], "other_col": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "target_col": [0, 1]})
        res = evaluate_predictions(
            df_s,
            df_l,
            {"accuracy": {"weight": 1.0, "options": {"column": "target_col"}}},
        )
        assert res["accuracy"] == pytest.approx(0.0)

    def test_custom_column_correctly_selected(self):
        df_l = pd.DataFrame({"id": [1, 2], "special_col": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "special_col": [0, 1]})
        res = evaluate_predictions(
            df_s,
            df_l,
            {"accuracy": {"weight": 1.0, "options": {"column": "special_col"}}},
        )
        assert res["accuracy"] == pytest.approx(1.0)

    # ── No-config path ─────────────────────────────────────────────────────────

    def test_no_config_defaults_to_accuracy(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        res = evaluate_predictions(df_s, df_l, None)
        assert "accuracy" in res
        assert res["accuracy"] == pytest.approx(1.0)

    def test_empty_dict_config_defaults_to_accuracy(self):
        df_l = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_s = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})
        res = evaluate_predictions(df_s, df_l, {})
        assert "accuracy" in res


class TestUnifiedParquetEvaluationExtensions(TestUnifiedParquetEvaluation):
    """
    Additional integration tests for evaluate_predictions and Task model helpers.
    Inherits the setup fixture from TestUnifiedParquetEvaluation so that
    self.challenge, self.app, etc. are available.
    """

    def test_multi_column_evaluation(self):
        df_labels = pd.DataFrame({"id": [1, 2], "label_1": [1.0, 2.0], "label_2": [3.0, 4.0]})
        df_sub = pd.DataFrame({"id": [1, 2], "label_1": [1.1, 1.9], "label_2": [3.2, 4.2]})

        metrics_cfg = {
            "mse": {
                "weight": 1.0,
                "options": {"column": "label_1", "multioutput": "raw_values"},
            },
            "mae": {"weight": 1.0, "options": {"column": "label_2"}},
        }

        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)

        assert "mse" in res
        assert res["mse"] == pytest.approx(0.01)

        assert "mae" in res
        assert res["mae"] == pytest.approx(0.2)

    def test_empty_dataframe_returns_empty_dict(self):
        df_empty = pd.DataFrame(columns=["id", "label"])
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_empty, df_empty, metrics_cfg)
        assert res == {}

    def test_empty_labels_only_returns_empty_dict(self):
        df_sub = pd.DataFrame({"id": [1], "label": [0]})
        df_labels = pd.DataFrame(columns=["id", "label"])
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        assert res == {}

    def test_column_auto_selection_prefers_prediction_label(self):
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1], "extra": [1, 2]})
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [1, 0], "extra": [3, 4]})
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        assert "accuracy" in res
        assert res["accuracy"] == pytest.approx(0.0)

    def test_column_falls_back_when_no_prediction_label(self):
        df_labels = pd.DataFrame({"id": [1, 2], "score": [0.0, 1.0]})
        df_sub = pd.DataFrame({"id": [1, 2], "score": [1.0, 0.0]})
        metrics_cfg = {"mse": {"weight": 1.0, "options": {"column": "score"}}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        assert "mse" in res

    def test_malformed_hf_json_does_not_crash_to_dict(self):
        task = Task(
            challenge_id=self.challenge.id,
            title="HF Test Task",
            hf_datasets="{malformed",
            hf_models="[not json",
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(task)
        db.session.commit()
        d = task.to_dict()
        assert d["hf_datasets"] == []
        assert d["hf_models"] == []

    def test_valid_hf_json_parses_correctly(self):
        task = Task(
            challenge_id=self.challenge.id,
            title="HF Valid Task",
            hf_datasets='["stanfordnlp/imdb", "glue"]',
            hf_models='["distilbert-base-uncased"]',
            metrics_config='{"accuracy": {"weight": 1.0}}',
        )
        db.session.add(task)
        db.session.commit()
        d = task.to_dict()
        assert d["hf_datasets"] == ["stanfordnlp/imdb", "glue"]
        assert d["hf_models"] == ["distilbert-base-uncased"]

    def test_stage_timezone_conversion_utc_to_sofia(self):
        import zoneinfo

        from routes.challenges import _now_local_for_timezone

        zoneinfo.ZoneInfo("Europe/Sofia")
        datetime(2026, 6, 14, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        datetime(2026, 6, 14, 15, 0, 0)

        local_now = _now_local_for_timezone("Europe/Sofia")
        assert local_now.tzinfo is None
        utc_now_naive = datetime.utcnow()
        diff = abs((local_now.replace(tzinfo=None) - utc_now_naive).total_seconds())
        assert diff < 3600 * 5


class TestMetricsCalculationEdgeCases:
    def test_validate_parquet_schema_missing_id(self):
        df = pd.DataFrame({"value": [1.0, 2.0]})
        is_valid, err = validate_parquet_schema(df)
        assert is_valid is False
        assert "missing required column: ['id']" in err

    def test_evaluate_predictions_alignment_mismatch(self):
        df_labels = pd.DataFrame({"id": [1, 2, 3], "label": [0, 1, 0]})
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0, 1]})

        with pytest.raises(ValueError) as exc_info:
            evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})
        assert "Submission ID alignment mismatch" in str(exc_info.value)

    def test_evaluate_predictions_missing_columns(self):
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_sub = pd.DataFrame({"id": [1, 2]})

        with pytest.raises(ValueError) as exc_info:
            evaluate_predictions(df_sub, df_labels, {"accuracy": {"weight": 1.0}})
        assert "contains no prediction columns" in str(exc_info.value)

    def test_metrics_empty_nlp_inputs(self):
        from evaluation_engine import compute_rouge_l, compute_ter

        assert compute_rouge_l("", "") == 0.0
        assert compute_rouge_l("hello", "") == 0.0
        assert compute_rouge_l("", "world") == 0.0

        assert compute_ter("", "") == 0.0
        assert compute_ter("hello", "") == 1.0
        assert compute_ter("", "world") == 1.0

    def test_evaluate_predictions_nan_inputs(self):
        df_labels = pd.DataFrame({"id": [1, 2], "label": [1.0, 2.0]})
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [np.nan, 2.0]})

        res = evaluate_predictions(df_sub, df_labels, {"mse": {"weight": 1.0}})
        assert "mse" in res
        assert res["mse"] == 999.0

    def test_evaluate_predictions_type_mismatch_resilience(self):
        # Classification metric receiving continuous values
        # (raises ValueError in sklearn f1_score with average='binary')

        df_labels = pd.DataFrame({"id": [1, 2], "label": [0.5, 1.5]})
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [0.2, 1.8]})

        res = evaluate_predictions(
            df_sub, df_labels, {"f1": {"weight": 1.0, "options": {"average": "binary"}}}
        )
        assert "f1" in res
        assert res["f1"] == 0.0

        # String targets passed to regression metrics
        df_labels_reg = pd.DataFrame({"id": [1, 2], "label": ["cat", "dog"]})
        df_sub_reg = pd.DataFrame({"id": [1, 2], "prediction": ["cat", "mouse"]})
        res_reg = evaluate_predictions(df_sub_reg, df_labels_reg, {"mse": {"weight": 1.0}})
        assert "mse" in res_reg
        assert res_reg["mse"] == 999.0
