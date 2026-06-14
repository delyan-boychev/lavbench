import os
import sys
import json
import unittest
import tempfile
import shutil
import io
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token
from evaluation_engine import validate_parquet_schema, evaluate_predictions, TASK_SCHEMAS

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
            "task_type": "classification",
            "metrics_config": json.dumps({
                "accuracy": {"weight": 0.5, "higher_is_better": True},
                "f1_macro": {"weight": 0.5, "higher_is_better": True}
            }),
            "baseline_notebook": (io.BytesIO(b"# Baseline"), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b"# Solution"), "solution.ipynb")
        }

    def test_schema_validation(self):
        """Test schema validation helper function for different task groups."""
        # 1. Classification
        df_class_ok = pd.DataFrame({"id": [1, 2], "label": ["A", "B"]})
        df_class_bad = pd.DataFrame({"id": [1, 2], "predictions": ["A", "B"]}) # missing label
        
        is_ok, err = validate_parquet_schema(df_class_ok, "classification", is_submission=True)
        self.assertTrue(is_ok)
        is_ok, err = validate_parquet_schema(df_class_bad, "classification", is_submission=True)
        self.assertFalse(is_ok)
        self.assertIn("missing required columns", err)

        # 2. Retrieval
        df_ret_ok = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20], "score": [0.9, 0.1]})
        df_ret_bad = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20]}) # missing score
        
        is_ok, err = validate_parquet_schema(df_ret_ok, "retrieval", is_submission=True)
        self.assertTrue(is_ok)
        is_ok, err = validate_parquet_schema(df_ret_bad, "retrieval", is_submission=True)
        self.assertFalse(is_ok)

    def test_evaluate_predictions_metrics(self):
        """Test evaluate_predictions computes the correct metrics and maps them correctly."""
        # 1. Classification
        df_labels = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1, 0, 1, 0]})
        df_sub = pd.DataFrame({"id": [1, 2, 3, 4], "label": [1, 0, 0, 0]}) # 3 out of 4 correct (75% accuracy)
        
        metrics_cfg = {
            "accuracy": {"weight": 1.0, "higher_is_better": True},
            "f1_micro": {"weight": 1.0, "higher_is_better": True},
            "f1_weighted": {"weight": 1.0, "higher_is_better": True},
            "precision_micro": {"weight": 1.0, "higher_is_better": True},
            "recall_micro": {"weight": 1.0, "higher_is_better": True},
            "cohen_kappa": {"weight": 1.0, "higher_is_better": True},
            "matthews_corrcoef": {"weight": 1.0, "higher_is_better": True}
        }
        res = evaluate_predictions(df_sub, df_labels, "classification", metrics_cfg)
        self.assertIn("accuracy", res)
        self.assertAlmostEqual(res["accuracy"], 0.75)
        self.assertAlmostEqual(res["f1_micro"], 0.75)
        self.assertAlmostEqual(res["precision_micro"], 0.75)
        self.assertAlmostEqual(res["recall_micro"], 0.75)
        self.assertIn("cohen_kappa", res)
        self.assertIn("matthews_corrcoef", res)

        # 2. Regression
        df_labels_reg = pd.DataFrame({"id": [1, 2], "value": [1.0, 2.0]})
        df_sub_reg = pd.DataFrame({"id": [1, 2], "value": [1.1, 1.9]})
        
        metrics_cfg_reg = {
            "mae": {"weight": 1.0, "higher_is_better": False},
            "mape": {"weight": 1.0, "higher_is_better": False},
            "median_ae": {"weight": 1.0, "higher_is_better": False}
        }
        res_reg = evaluate_predictions(df_sub_reg, df_labels_reg, "regression", metrics_cfg_reg)
        self.assertIn("mae", res_reg)
        self.assertAlmostEqual(res_reg["mae"], 0.1)
        self.assertIn("mape", res_reg)
        self.assertIn("median_ae", res_reg)

        # 3. Retrieval
        df_labels_ret = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20]})
        df_sub_ret = pd.DataFrame({"query_id": [1, 1], "doc_id": [10, 20], "score": [0.9, 0.1]})
        metrics_cfg_ret = {
            "ndcg_5": {"weight": 1.0, "higher_is_better": True},
            "recall_5": {"weight": 1.0, "higher_is_better": True}
        }
        res_ret = evaluate_predictions(df_sub_ret, df_labels_ret, "retrieval", metrics_cfg_ret)
        self.assertIn("ndcg_5", res_ret)
        self.assertIn("recall_5", res_ret)

        # 4. Translation / Summ (chrf, ter)
        df_labels_trans = pd.DataFrame({"id": [1], "text": ["hello world"]})
        df_sub_trans = pd.DataFrame({"id": [1], "text": ["hello there"]})
        metrics_cfg_trans = {
            "chrf": {"weight": 1.0, "higher_is_better": True},
            "ter": {"weight": 1.0, "higher_is_better": False}
        }
        res_trans = evaluate_predictions(df_sub_trans, df_labels_trans, "translation_summ", metrics_cfg_trans)
        self.assertIn("chrf", res_trans)
        self.assertIn("ter", res_trans)

        # 5. Keypoints (pck)
        df_labels_kp = pd.DataFrame({"id": [1], "keypoints": [[[10, 20]]]})
        df_sub_kp = pd.DataFrame({"id": [1], "keypoints": [[[10, 20]]]})
        metrics_cfg_kp = {"pck": {"weight": 1.0}}
        res_kp = evaluate_predictions(df_sub_kp, df_labels_kp, "keypoints", metrics_cfg_kp)
        self.assertIn("pck", res_kp)
        self.assertAlmostEqual(res_kp["pck"], 1.0)

    def test_create_task_validation_routes(self):
        """Test creating tasks with valid and invalid task types/metrics configurations."""
        # 1. Valid task creation
        task_data = self.get_default_task_data()
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/tasks',
            headers=self.get_auth_header(self.admin_token),
            data=task_data,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 201)
        res_json = res.get_json()
        self.assertEqual(res_json["task_type"], "classification")
        self.assertEqual(res_json["metrics_config"]["accuracy"]["weight"], 0.5)

        # 2. Invalid task_type
        task_data_invalid = self.get_default_task_data()
        task_data_invalid["task_type"] = "invalid_type_name"
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/tasks',
            headers=self.get_auth_header(self.admin_token),
            data=task_data_invalid,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid task type", res.get_json()["error"])

        # 3. Invalid metric for task_type
        task_data_metric = self.get_default_task_data()
        task_data_metric["task_type"] = "classification"
        task_data_metric["metrics_config"] = json.dumps({
            "rmse": {"weight": 1.0, "higher_is_better": False} # rmse is reg, not class
        })
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/tasks',
            headers=self.get_auth_header(self.admin_token),
            data=task_data_metric,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid metric 'rmse' for task type 'classification'", res.get_json()["error"])

        # 4. Valid options in metrics_config
        task_data_opts = self.get_default_task_data()
        task_data_opts["metrics_config"] = json.dumps({
            "accuracy": {"weight": 1.0, "options": {"beta": 3}}
        })
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/tasks',
            headers=self.get_auth_header(self.admin_token),
            data=task_data_opts,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["metrics_config"]["accuracy"]["options"]["beta"], 3)

        # 5. Invalid options format (not dict)
        task_data_opts_inv = self.get_default_task_data()
        task_data_opts_inv["metrics_config"] = json.dumps({
            "accuracy": {"weight": 1.0, "options": "not_a_dict"}
        })
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/tasks',
            headers=self.get_auth_header(self.admin_token),
            data=task_data_opts_inv,
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Options for metric 'accuracy' must be a dictionary/JSON object", res.get_json()["error"])

    def test_labels_parquet_upload_validation(self):
        """Test labels.parquet is schema validated on upload."""
        # Write valid and invalid parquet to temp files
        valid_path = os.path.join(self.temp_test_dir, "valid_labels.parquet")
        invalid_path = os.path.join(self.temp_test_dir, "invalid_labels.parquet")
        
        pd.DataFrame({"id": [1, 2], "label": ["A", "B"]}).to_parquet(valid_path)
        pd.DataFrame({"id": [1, 2], "score": [0.5, 0.8]}).to_parquet(invalid_path)
        
        # 1. Upload valid labels.parquet
        with open(valid_path, "rb") as f_valid:
            task_data = {
                "title": "Unified Task 2",
                "task_type": "classification",
                "file_0": (f_valid, "labels.parquet"),
                "baseline_notebook": (io.BytesIO(b"# Baseline"), "baseline.ipynb"),
                "solution_notebook": (io.BytesIO(b"# Solution"), "solution.ipynb")
            }
            res = self.client.post(
                f'/api/challenges/{self.challenge.id}/tasks',
                headers=self.get_auth_header(self.admin_token),
                data=task_data,
                content_type='multipart/form-data'
            )
            self.assertEqual(res.status_code, 201)

        # 2. Upload invalid labels.parquet (missing label col)
        with open(invalid_path, "rb") as f_invalid:
            task_data = {
                "title": "Unified Task 3",
                "task_type": "classification",
                "file_0": (f_invalid, "labels.parquet"),
                "baseline_notebook": (io.BytesIO(b"# Baseline"), "baseline.ipynb"),
                "solution_notebook": (io.BytesIO(b"# Solution"), "solution.ipynb")
            }
            res = self.client.post(
                f'/api/challenges/{self.challenge.id}/tasks',
                headers=self.get_auth_header(self.admin_token),
                data=task_data,
                content_type='multipart/form-data'
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("Invalid labels.parquet schema", res.get_json()["error"])

    @patch('subprocess.run')
    def test_celery_evaluate_submission_unified_parquet(self, mock_subproc):
        """Test evaluate_submission Celery task pipeline for unified parquet submission."""
        import tempfile
        from tasks import evaluate_submission
        
        # 1. Create a task with task_type classification
        task = Task(
            challenge_id=self.challenge.id,
            title="Class Task",
            task_type="classification",
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
             patch('tasks.run_command_streaming', return_value=(0, "", "", False)), \
             patch('tasks.app', self.app):
             
             res = evaluate_submission(sub.id)
             self.assertIn("evaluated with status completed", res)

        # Refresh from database and check scores
        db.session.refresh(sub)
        self.assertEqual(sub.status, "completed")
        self.assertAlmostEqual(sub.public_score, 1.0) # public split (id 1, 2) is 100% correct
        self.assertAlmostEqual(sub.private_score, 0.5) # private split (id 3, 4) is 50% correct
        self.assertEqual(sub.metrics_payload_public, {"accuracy": 1.0})
        self.assertEqual(sub.metrics_payload_private, {"accuracy": 0.5})

    @patch('subprocess.run')
    def test_celery_evaluate_submission_invalid_schema(self, mock_subproc):
        """Test evaluate_submission fails and logs error when submission.parquet has invalid schema."""
        import tempfile
        from tasks import evaluate_submission
        
        # 1. Create a task with task_type classification
        task = Task(
            challenge_id=self.challenge.id,
            title="Class Task 2",
            task_type="classification",
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
        
        df_labels = pd.DataFrame({"id": [1, 2], "label": [0, 1]})
        df_labels.to_parquet(labels_parquet_path)
        
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

        # Mock submission.parquet to have invalid columns (value instead of label)
        original_mkdtemp = tempfile.mkdtemp
        
        def mock_mkdtemp(*args, **kwargs):
            td = original_mkdtemp(*args, **kwargs)
            df_sub = pd.DataFrame({"id": [1, 2], "value": [0, 1]}) # invalid column
            df_sub.to_parquet(os.path.join(td, "submission.parquet"))
            return td
            
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch('tempfile.mkdtemp', side_effect=mock_mkdtemp), \
             patch('tasks.run_command_streaming', return_value=(0, "", "", False)), \
             patch('tasks.app', self.app):
             
             res = evaluate_submission(sub.id)

        # Refresh from database and check status
        db.session.refresh(sub)
        self.assertEqual(sub.status, "failed")
        self.assertIn("Submission schema validation failed", sub.logs)

if __name__ == '__main__':
    unittest.main()
