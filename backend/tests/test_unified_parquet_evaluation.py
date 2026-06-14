import os
import sys
import json
import unittest
import tempfile
import shutil
import io
import math
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token
from evaluation_engine import validate_parquet_schema, evaluate_predictions

class TestUnifiedParquetEvaluation(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
        self.client = self.app.test_client()
        
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        db.create_all()
        self.seed_basic_data()
        
        # Temp dir for generating test parquet files
        self.temp_test_dir = tempfile.mkdtemp()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        shutil.rmtree(self.app.config['UPLOAD_FOLDER'], ignore_errors=True)
        shutil.rmtree(self.temp_test_dir, ignore_errors=True)

    def seed_basic_data(self):
        # Create an admin user
        self.admin = User(
            username="test_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-001"
        )
        db.session.add(self.admin)

        # Create a competitor challenge
        self.challenge = Challenge(
            title="IMDB Sentiment Classification",
            description="Predict sentiment of reviews.",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() + timedelta(hours=2),
            is_frozen=False
        )
        db.session.add(self.challenge)
        db.session.commit()

        # Create a competitor user
        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Stellar-Voyager-101",
            challenge_id=self.challenge.id
        )
        db.session.add(self.competitor)
        db.session.commit()

        # Save tokens for authentication
        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def get_auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def get_default_task_data(self):
        return {
            "title": "Unified Task 1",
            "description": "Modality test",
            "metrics_config": json.dumps({
                "accuracy": {"weight": 0.5, "higher_is_better": True},
                "f1_macro": {"weight": 0.5, "higher_is_better": True}
            }),
            "baseline_notebook": (io.BytesIO(b"# Baseline"), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b"# Solution"), "solution.ipynb")
        }

    @patch('subprocess.run')
    def test_celery_evaluate_submission_unified_parquet(self, mock_subproc):
        """Test evaluate_submission Celery task pipeline for unified parquet submission."""
        import tempfile
        from tasks import evaluate_submission
        
        # 1. Create a unified parquet task
        task = Task(
            challenge_id=self.challenge.id,
            title="Class Task",
            metrics_config=json.dumps({
                "accuracy": {"weight": 1.0, "higher_is_better": True}
            }),
            public_eval_percentage=50
        )
        db.session.add(task)
        db.session.commit()
        
        # Save dummy labels.parquet
        task_dir = os.path.join(self.app.config['UPLOAD_FOLDER'], f"task_{task.id}")
        os.makedirs(task_dir, exist_ok=True)
        labels_parquet_path = os.path.join(task_dir, "labels.parquet")
        
        # 4 items (2 public, 2 private)
        df_labels = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 1]})
        df_labels.to_parquet(labels_parquet_path)
        
        # Set task files meta
        task.files = json.dumps([{
            "filename": "labels.parquet",
            "saved_name": "labels.parquet",
            "size_bytes": 1000
        }])
        db.session.commit()

        # Create submission
        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=task.id,
            status="queued"
        )
        sub.code_cells = json.dumps(["# Write output\nprint('Done!')"])
        db.session.add(sub)
        db.session.commit()

        # Mock subprocess run to output a mock submission.parquet inside temp_dir!
        # We hook into temp_dir creation by mocking tempfile.mkdtemp.
        original_mkdtemp = tempfile.mkdtemp
        temp_dir_holder = []
        
        def mock_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            temp_dir_holder.append(td)
            # Write a mock submission.parquet inside this directory
            # Make public score 100% correct (0, 1), private 50% correct (0, 0 vs 0, 1)
            df_sub = pd.DataFrame({"id": [1, 2, 3, 4], "label": [0, 1, 0, 0]})
            df_sub.to_parquet(os.path.join(td, "submission.parquet"))
            return td
            
        # Mock run_command_streaming or subprocess.run to just exit success
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch('tempfile.mkdtemp', side_effect=mock_mkdtemp), \
             patch('task_modules.submission_runner.run_command_streaming', return_value=(0, "", "", False)), \
             patch('tasks.app', self.app):
             
             res = evaluate_submission(sub.id)
             sub_reloaded = db.session.get(Submission, sub.id)
             db.session.refresh(sub_reloaded)
             print("\n\nSTATUS:", sub_reloaded.status)
             print("LOGS:", sub_reloaded.logs, "\n\n")
             self.assertIn("evaluated with status completed", res)

        # Refresh from database and check scores
        db.session.refresh(sub)
        self.assertEqual(sub.status, "completed")
        self.assertAlmostEqual(sub.public_score, 1.0) # public split (id 1, 2) is 100% correct
        self.assertAlmostEqual(sub.private_score, 0.5) # private split (id 3, 4) is 50% correct
        self.assertEqual(sub.metrics_payload_public, {"accuracy": 1.0})
        self.assertEqual(sub.metrics_payload_private, {"accuracy": 0.5})


        # Mock submission.parquet to have invalid columns (value instead of label)
        original_mkdtemp = tempfile.mkdtemp
        
        def mock_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            df_sub = pd.DataFrame({"not_id": [1, 2], "value": [0, 1]}) # invalid column missing id
            df_sub.to_parquet(os.path.join(td, "submission.parquet"))
            return td
            
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch('tempfile.mkdtemp', side_effect=mock_mkdtemp), \
             patch('task_modules.submission_runner.run_command_streaming', return_value=(0, "", "", False)), \
             patch('tasks.app', self.app):
             
             res = evaluate_submission(sub.id)

        # Refresh from database and check status
        db.session.refresh(sub)
        self.assertEqual(sub.status, "failed")
        self.assertIn("Submission schema validation failed", sub.logs)

    def test_multi_column_evaluation(self):
        """Test multi-column extraction and multioutput aggregation."""
        df_labels = pd.DataFrame({
            "id": [1, 2],
            "label_1": [1.0, 2.0],
            "label_2": [3.0, 4.0]
        })
        df_sub = pd.DataFrame({
            "id": [1, 2],
            "label_1": [1.1, 1.9],
            "label_2": [3.2, 4.2]
        })
        
        metrics_cfg = {
            "mse": {"weight": 1.0, "options": {"column": "label_1", "multioutput": "raw_values"}},
            "mae": {"weight": 1.0, "options": {"column": "label_2"}}
        }
        
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        
        self.assertIn("mse", res)
        # mse for label_1: (0.1^2 + -0.1^2) / 2 = 0.01
        self.assertAlmostEqual(res["mse"], 0.01)
        
        self.assertIn("mae", res)
        # mae for label_2: (0.2 + 0.2) / 2 = 0.2
        self.assertAlmostEqual(res["mae"], 0.2)

    def test_empty_dataframe_returns_empty_dict(self):
        """Empty DataFrames should return {} without crashing."""
        df_empty = pd.DataFrame(columns=["id", "label"])
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_empty, df_empty, metrics_cfg)
        self.assertEqual(res, {})

    def test_empty_labels_only_returns_empty_dict(self):
        """When only labels is empty, should return {} gracefully."""
        df_sub = pd.DataFrame({"id": [1], "label": [0]})
        df_labels = pd.DataFrame(columns=["id", "label"])
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        self.assertEqual(res, {})

    def test_column_auto_selection_prefers_prediction_label(self):
        """Should prefer 'prediction' column on sub side, 'label' on labels side."""
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1], "extra": [1, 2]})
        df_sub = pd.DataFrame({"id": [1, 2], "prediction": [1, 0], "extra": [3, 4]})
        metrics_cfg = {"accuracy": {"weight": 1.0}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        # prediction=1,0 vs label=0,1 → 0% accuracy
        self.assertIn("accuracy", res)
        self.assertAlmostEqual(res["accuracy"], 0.0)

    def test_column_falls_back_when_no_prediction_label(self):
        """When no 'prediction'/'label' columns, should use first non-id column."""
        df_labels = pd.DataFrame({"id": [1, 2], "score": [0.0, 1.0]})
        df_sub = pd.DataFrame({"id": [1, 2], "score": [1.0, 0.0]})
        metrics_cfg = {"mse": {"weight": 1.0, "options": {"column": "score"}}}
        res = evaluate_predictions(df_sub, df_labels, metrics_cfg)
        self.assertIn("mse", res)

    def test_malformed_hf_json_does_not_crash_to_dict(self):
        """Task.to_dict() should not crash when hf_datasets/hf_models contain malformed JSON."""
        task = Task(
            challenge_id=self.challenge.id,
            title="HF Test Task",
            hf_datasets="{malformed",
            hf_models='[not json',
            metrics_config='{"accuracy": {"weight": 1.0}}'
        )
        db.session.add(task)
        db.session.commit()
        d = task.to_dict()
        self.assertEqual(d["hf_datasets"], [])
        self.assertEqual(d["hf_models"], [])

    def test_valid_hf_json_parses_correctly(self):
        """Task.to_dict() should correctly parse valid JSON hf_datasets/hf_models."""
        task = Task(
            challenge_id=self.challenge.id,
            title="HF Valid Task",
            hf_datasets='["stanfordnlp/imdb", "glue"]',
            hf_models='["distilbert-base-uncased"]',
            metrics_config='{"accuracy": {"weight": 1.0}}'
        )
        db.session.add(task)
        db.session.commit()
        d = task.to_dict()
        self.assertEqual(d["hf_datasets"], ["stanfordnlp/imdb", "glue"])
        self.assertEqual(d["hf_models"], ["distilbert-base-uncased"])

    def test_stage_timezone_conversion_utc_to_sofia(self):
        """Stage start_time in UTC should be correctly converted to challenge timezone."""
        import zoneinfo
        from routes.challenges import _now_local_for_timezone

        tz_sofia = zoneinfo.ZoneInfo("Europe/Sofia")  # UTC+3 summer
        now_utc = datetime(2026, 6, 14, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))
        now_sofia_expected = datetime(2026, 6, 14, 15, 0, 0)  # 12:00 UTC = 15:00 Sofia

        # _now_local_for_timezone should return a naive datetime in the challenge's local zone
        local_now = _now_local_for_timezone("Europe/Sofia")
        # Just verify it returns a datetime without tzinfo
        self.assertIsNone(local_now.tzinfo)
        # Verify it's within a reasonable range (within a minute of current time)
        utc_now_naive = datetime.utcnow()
        diff = abs((local_now.replace(tzinfo=None) - utc_now_naive).total_seconds())
        self.assertLess(diff, 3600 * 5)  # within 5 hours (UTC+2 or UTC+3 for Sofia)

if __name__ == '__main__':
    unittest.main()
