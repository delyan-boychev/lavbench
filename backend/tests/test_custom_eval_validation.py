import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Force in-memory SQLite for testing
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db
from tasks import evaluate_submission

class TestCustomEvalValidation(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Disable docker version check fallback so we run local sys.executable fallback
        self.docker_patch = patch('subprocess.run')
        self.mock_sub_run = self.docker_patch.start()
        # Return code 1 for docker version check, meaning docker is unavailable
        self.mock_sub_run.return_value = MagicMock(returncode=1)

    def tearDown(self):
        self.docker_patch.stop()
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    @patch('tasks.report_status_to_server')
    def run_eval_with_code(self, custom_eval_code, mock_report):
        mock_report.return_value = True

        metadata = {
            "main_server_url": "http://localhost:5001",
            "worker_secret_key": "secret",
            "submission_id": 123,
            "task_id": 456,
            "user_code": "def run_pipeline(): return 0.75, 0.85",
            "is_custom_eval": True,
            "custom_eval_code": custom_eval_code
        }

        # Run the evaluation
        evaluate_submission(submission_id=123, metadata=metadata)

        # Retrieve the final update status arguments
        final_call_args = None
        for call in mock_report.call_args_list:
            args, kwargs = call
            # We are interested in the final status report call (completed or failed)
            status_val = kwargs.get('status')
            if status_val in ('completed', 'failed'):
                final_call_args = kwargs
                
        return final_call_args

    def test_custom_eval_success(self):
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "status": "success",
        "public_score": 0.8,
        "private_score": 0.9,
        "execution_time_ms": 150,
        "metrics_payload_public": {"acc": 0.8},
        "metrics_payload_private": {"acc": 0.9}
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['public_score'], 0.8)
        self.assertEqual(result['private_score'], 0.9)
        self.assertIn("Evaluation completed successfully.", result['logs'])

    def test_custom_eval_student_error(self):
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "status": "error",
        "error": "Failed to compile or import student code."
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Evaluation script returned error: Failed to compile or import student code.", result['logs'])
        # Should NOT contain the "Jury Evaluator Error" because the evaluator caught and returned an expected student error
        self.assertNotIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_missing_file(self):
        # Evaluator runs but does not write any file
        code = """
print("I did not write anything!")
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_corrupt_json(self):
        # Writes invalid JSON to file
        code = """
with open("eval_results.json", "w") as f:
    f.write("{not valid json")
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_missing_status(self):
        # Writes valid JSON but missing 'status'
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "public_score": 0.8,
        "private_score": 0.9
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_invalid_status_value(self):
        # Status has wrong value
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "status": "partial_success",
        "public_score": 0.8,
        "private_score": 0.9
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_missing_scores_on_success(self):
        # Status is success but scores are missing
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "status": "success"
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

    def test_custom_eval_invalid_score_types(self):
        # Scores are strings or booleans instead of numbers
        code = """
import json
with open("eval_results.json", "w") as f:
    json.dump({
        "status": "success",
        "public_score": "0.8",
        "private_score": True
    }, f)
"""
        result = self.run_eval_with_code(code)
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'failed')
        self.assertIn("Jury Evaluator Error: The custom evaluation script failed to produce a valid results file.", result['logs'])

if __name__ == '__main__':
    unittest.main()
