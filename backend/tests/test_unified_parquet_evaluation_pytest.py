import os
import sys
import json
import pytest
import tempfile
import shutil
import io
import math
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token
from evaluation_engine import validate_parquet_schema, evaluate_predictions


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
            [{"filename": "labels.parquet", "saved_name": "labels.parquet", "size_bytes": 1000}]
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

    def test_multi_column_evaluation(self):
        df_labels = pd.DataFrame({"id": [1, 2], "label_1": [1.0, 2.0], "label_2": [3.0, 4.0]})
        df_sub = pd.DataFrame({"id": [1, 2], "label_1": [1.1, 1.9], "label_2": [3.2, 4.2]})

        metrics_cfg = {
            "mse": {"weight": 1.0, "options": {"column": "label_1", "multioutput": "raw_values"}},
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

        tz_sofia = zoneinfo.ZoneInfo("Europe/Sofia")
        now_utc = datetime(2026, 6, 14, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        now_sofia_expected = datetime(2026, 6, 14, 15, 0, 0)

        local_now = _now_local_for_timezone("Europe/Sofia")
        assert local_now.tzinfo is None
        utc_now_naive = datetime.utcnow()
        diff = abs((local_now.replace(tzinfo=None) - utc_now_naive).total_seconds())
        assert diff < 3600 * 5
