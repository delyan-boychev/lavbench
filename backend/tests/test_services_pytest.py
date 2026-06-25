import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import db, Task
from services.submission_service import (
    check_execution_rules,
    calculate_submission_priority,
)
from datetime import datetime


class TestServiceSandboxAndPriority:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.task = Task(ban_magic_commands=False, banned_imports=None)

    def test_check_execution_rules_basic_pass(self):
        code_cells = ["def predict(x):\n    return x * 2"]
        passed, error = check_execution_rules(self.task, code_cells)
        assert passed
        assert error is None

    def test_check_execution_rules_banned_magic_commands(self):
        self.task.ban_magic_commands = True

        code_cells_bang = ["!pip install numpy\ndef predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells_bang)
        assert not passed
        assert "magic commands ('!' or '%') are banned" in error

        code_cells_percent = ["%matplotlib inline\ndef predict(x):\n    return x"]
        passed, error = check_execution_rules(self.task, code_cells_percent)
        assert not passed
        assert "magic commands ('!' or '%') are banned" in error

    def test_check_execution_rules_banned_imports_ast(self):
        self.task.banned_imports = "os,sys,subprocess"

        code_cells_os = ["import os\nprint('hello')"]
        passed, error = check_execution_rules(self.task, code_cells_os)
        assert not passed
        assert "Import of library 'os' is banned" in error

        code_cells_from_sys = ["from sys import exit\nexit(0)"]
        passed, error = check_execution_rules(self.task, code_cells_from_sys)
        assert not passed
        assert "Import from library 'sys' is banned" in error

        code_cells_sub = ["import os.path as osp\nprint('hello')"]
        passed, error = check_execution_rules(self.task, code_cells_sub)
        assert not passed
        assert "Import of library 'os.path' is banned" in error

        code_cells_numpy = ["import numpy as np\nprint(np.zeros(5))"]
        passed, error = check_execution_rules(self.task, code_cells_numpy)
        assert passed

    def test_calculate_submission_priority_admin_jury(self):
        assert calculate_submission_priority(1, "admin") == 9
        assert calculate_submission_priority(2, "jury") == 9

    def test_evaluation_templates_formatting(self):
        from task_modules.templates import (
            DEFAULT_EVALUATION_TEMPLATE,
            render_eval_template,
        )

        formatted_default = render_eval_template(
            DEFAULT_EVALUATION_TEMPLATE,
            user_code="print('user default')",
            public_eval_percentage=30,
            hf_dataset_split="test",
            metrics_config_str='{"accuracy": {"weight": 1.0, "higher_is_better": true}}',
        )
        assert "load_dataset" in formatted_default

    def test_get_best_submission_higher_better(self):
        from models import Challenge, Submission
        from services.submission_service import get_best_submission

        challenge = Challenge(
            title="Test Challenge",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        )
        db.session.add(challenge)
        db.session.commit()

        sub1 = Submission(
            task_id=self.task.id,
            user_id=1,
            status="completed",
            public_score=0.7,
            private_score=0.8,
            execution_time_ms=200,
        )
        sub2 = Submission(
            task_id=self.task.id,
            user_id=1,
            status="completed",
            public_score=0.9,
            private_score=0.9,
            execution_time_ms=100,
        )

        best = get_best_submission(self.task, [sub1, sub2], challenge)
        assert best.public_score == 0.9

    def test_get_best_submission_lower_better(self):
        from models import Challenge, Submission
        from services.submission_service import get_best_submission

        challenge = Challenge(
            title="Test Challenge",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        )
        db.session.add(challenge)
        db.session.commit()

        self.task.metrics_config = '{"mse": {"weight": 1.0, "higher_is_better": false}}'
        # In practice, scores are normalized by the runner to higher-is-better:
        # sub1 (MSE = 10.0) -> normalized to 1.0 / (1.0 + 10.0) = 0.0909
        # sub2 (MSE = 5.0)  -> normalized to 1.0 / (1.0 + 5.0) = 0.1667
        sub1 = Submission(
            task_id=self.task.id,
            user_id=1,
            status="completed",
            public_score=0.0909,
            private_score=0.0909,
            execution_time_ms=200,
        )
        sub2 = Submission(
            task_id=self.task.id,
            user_id=1,
            status="completed",
            public_score=0.1667,
            private_score=0.1667,
            execution_time_ms=100,
        )

        best = get_best_submission(self.task, [sub1, sub2], challenge, is_lower_better=True)
        assert best.public_score == 0.1667

    def test_challenge_csv_generation(self):
        from models import Challenge, User, Submission
        from services.challenge_service import (
            generate_scores_csv,
            generate_exported_results_csv,
        )

        challenge = Challenge(
            title="Test Challenge",
            scores_finalized=True,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
        )
        db.session.add(challenge)
        db.session.commit()

        task = Task(
            challenge_id=challenge.id,
            title="Test Task",
            ban_magic_commands=False,
            files="[]",
        )
        db.session.add(task)

        comp = User(
            username="student1",
            role="competitor",
            challenge_id=challenge.id,
            password_hash="dummy",
        )
        db.session.add(comp)
        db.session.commit()

        sub = Submission(
            task_id=task.id,
            challenge_id=challenge.id,
            user_id=comp.id,
            status="completed",
            public_score=0.8,
            private_score=0.85,
            execution_time_ms=100,
        )
        db.session.add(sub)
        db.session.commit()

        csv_scores = generate_scores_csv(challenge)
        assert "student1" in csv_scores
        assert "Total Score" in csv_scores

        csv_exported = generate_exported_results_csv(challenge)
        assert "student1" in csv_exported
        assert "Aggregated Private Score" in csv_exported
