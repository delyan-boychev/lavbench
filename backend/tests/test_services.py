import os
import sys
import unittest

# Set environment variable before any flask imports to force in-memory SQLite
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Add backend directory to path so we can import from it
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, Task
from services.submission_service import check_execution_rules, calculate_submission_priority
from datetime import datetime

class TestServiceSandboxAndPriority(unittest.TestCase):
    def setUp(self):
        # Setup application context
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create an actual Task instance for testing execution rules
        self.task = Task(
            require_submit_tag=False,
            ban_magic_commands=False,
            banned_imports=None
        )

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_check_execution_rules_basic_pass(self):
        """Valid code with no special rules should pass."""
        code_cells = ["def predict(x):\n    return x * 2"]
        passed, error = check_execution_rules(self.task, code_cells)
        self.assertTrue(passed)
        self.assertIsNone(error)

    def test_check_execution_rules_missing_submit_tag(self):
        """Code must fail if # SUBMIT tag is required but missing."""
        self.task.require_submit_tag = True
        code_cells = ["def predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells)
        self.assertFalse(passed)
        self.assertIn("missing the required '# SUBMIT' tag", error)

        # Should pass when tag is present
        code_cells_with_tag = ["# SUBMIT\ndef predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells_with_tag)
        self.assertTrue(passed)
        self.assertIsNone(error)

    def test_check_execution_rules_banned_magic_commands(self):
        """Code must fail if Jupyter magic commands are banned and present."""
        self.task.ban_magic_commands = True
        
        # Test exclamation mark prefix
        code_cells_bang = ["!pip install numpy\ndef predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells_bang)
        self.assertFalse(passed)
        self.assertIn("magic commands ('!' or '%') are banned", error)

        # Test percent prefix
        code_cells_percent = ["%matplotlib inline\ndef predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells_percent)
        self.assertFalse(passed)
        self.assertIn("magic commands ('!' or '%') are banned", error)

    def test_check_execution_rules_banned_imports_ast(self):
        """Code must fail if imports are banned in AST."""
        self.task.banned_imports = "os,sys,subprocess"

        # Standard import statement
        code_cells_os = ["import os\nprint('hello')"]
        passed, error = check_execution_rules(self.task, code_cells_os)
        self.assertFalse(passed)
        self.assertIn("Import of library 'os' is banned", error)

        # ImportFrom statement
        code_cells_from_sys = ["from sys import exit\nexit(0)"]
        passed, error = check_execution_rules(self.task, code_cells_from_sys)
        self.assertFalse(passed)
        self.assertIn("Import from library 'sys' is banned", error)

        # Submodule import
        code_cells_sub = ["import os.path as osp\nprint('hello')"]
        passed, error = check_execution_rules(self.task, code_cells_sub)
        self.assertFalse(passed)
        self.assertIn("Import of library 'os.path' is banned", error)

        # Non-banned import should pass
        code_cells_numpy = ["import numpy as np\nprint(np.zeros(5))"]
        passed, error = check_execution_rules(self.task, code_cells_numpy)
        self.assertTrue(passed)

    def test_calculate_submission_priority_admin_jury(self):
        """Admins and Jury members must get the highest priority (9)."""
        self.assertEqual(calculate_submission_priority(1, "admin"), 9)
        self.assertEqual(calculate_submission_priority(2, "jury"), 9)

    def test_evaluation_templates_formatting(self):
        """Verify that evaluation templates can be formatted without raising KeyError."""
        from task_modules.templates import DEFAULT_EVALUATION_TEMPLATE, render_eval_template
        
        # Format DEFAULT_EVALUATION_TEMPLATE
        formatted_default = render_eval_template(
            DEFAULT_EVALUATION_TEMPLATE,
            user_code="print('user default')",

            hf_token="test_token",
            public_eval_percentage=30,
            hf_dataset_split="test",
            metrics_config_str='{"accuracy": {"weight": 1.0, "higher_is_better": true}}'
        )
        self.assertIn("test_token", formatted_default)

    def test_get_best_submission_higher_better(self):
        """Verify get_best_submission returns the submission with the highest score and handles tie breaking."""
        from models import Challenge, Submission
        from services.submission_service import get_best_submission
        
        challenge = Challenge(title="Test Challenge", start_time=datetime.utcnow(), end_time=datetime.utcnow())
        db.session.add(challenge)
        db.session.commit()
        
        sub1 = Submission(task_id=self.task.id, user_id=1, status='completed', public_score=0.7, private_score=0.8, execution_time_ms=200)
        sub2 = Submission(task_id=self.task.id, user_id=1, status='completed', public_score=0.9, private_score=0.9, execution_time_ms=100)
        
        best = get_best_submission(self.task, [sub1, sub2], challenge)
        self.assertEqual(best.public_score, 0.9)

    def test_get_best_submission_lower_better(self):
        """Verify get_best_submission returns the submission with the lowest score for lower-better metrics."""
        from models import Challenge, Submission
        from services.submission_service import get_best_submission
        
        challenge = Challenge(title="Test Challenge", start_time=datetime.utcnow(), end_time=datetime.utcnow())
        db.session.add(challenge)
        db.session.commit()
        
        self.task.metrics_config = '{"mse": {"weight": 1.0, "higher_is_better": false}}'
        sub1 = Submission(task_id=self.task.id, user_id=1, status='completed', public_score=10.0, private_score=10.0, execution_time_ms=200)
        sub2 = Submission(task_id=self.task.id, user_id=1, status='completed', public_score=5.0, private_score=5.0, execution_time_ms=100)
        
        best = get_best_submission(self.task, [sub1, sub2], challenge, is_lower_better=True)
        self.assertEqual(best.public_score, 5.0)

    def test_challenge_csv_generation(self):
        """Verify that generate_scores_csv and generate_exported_results_csv execute successfully and return CSV strings."""
        from models import Challenge, User, Submission
        from services.challenge_service import generate_scores_csv, generate_exported_results_csv
        
        challenge = Challenge(title="Test Challenge", scores_finalized=True, start_time=datetime.utcnow(), end_time=datetime.utcnow())
        db.session.add(challenge)
        db.session.commit()
        
        task = Task(
            challenge_id=challenge.id,
            title="Test Task",
            require_submit_tag=False,
            ban_magic_commands=False,
            files="[]"
        )
        db.session.add(task)
        
        comp = User(username="student1", role="competitor", challenge_id=challenge.id, password_hash="dummy")
        db.session.add(comp)
        db.session.commit()
        
        sub = Submission(task_id=task.id, challenge_id=challenge.id, user_id=comp.id, status='completed', public_score=0.8, private_score=0.85, execution_time_ms=100)
        db.session.add(sub)
        db.session.commit()
        
        csv_scores = generate_scores_csv(challenge)
        self.assertIn("student1", csv_scores)
        self.assertIn("Total Score", csv_scores)
        
        csv_exported = generate_exported_results_csv(challenge)
        self.assertIn("student1", csv_exported)
        self.assertIn("Aggregated Private Score", csv_exported)

if __name__ == '__main__':
    unittest.main()
