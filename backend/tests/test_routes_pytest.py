import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_utils import generate_token
from models import Challenge, Submission, Task, User, db
from services.submission_service import calculate_submission_priority


class TestRouteLevelLogic:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, client, auth_headers, csrf_headers, redis_flush):
        self.client = client
        self._auth = auth_headers
        self.csrf_headers = csrf_headers
        self.seed_basic_data()

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
        self.competitor.set_demographics("Jane", "Doe", "12", "Sofia High", "Sofia")
        db.session.add(self.competitor)

        self.task = Task(
            challenge_id=self.challenge.id,
            title="Classification Task",
            description="Predict movie ratings.",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]",
        )
        db.session.add(self.task)
        db.session.commit()

        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

        self.jury = User(
            username="test_jury",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Test",
        )
        db.session.add(self.jury)
        db.session.commit()

        from models import JuryChallenge

        if (
            not db.session.query(JuryChallenge)
            .filter_by(jury_id=self.jury.id, challenge_id=self.challenge.id)
            .first()
        ):
            db.session.add(JuryChallenge(jury_id=self.jury.id, challenge_id=self.challenge.id))
            db.session.commit()

        self.jury_token = generate_token(self.jury.id, self.jury.role)

    def get_auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_role_authorization_admin_vs_competitor(self):
        res = self.client.get(
            "/api/admin/users", headers=self.get_auth_header(self.competitor_token)
        )
        assert res.status_code == 403
        assert "Requires role" in res.get_json()["error"]

        res = self.client.get("/api/admin/users", headers=self.get_auth_header(self.admin_token))
        assert res.status_code == 200
        assert "items" in res.get_json()

    @patch("tasks.evaluate_submission.apply_async")
    def test_competition_schedule_boundaries(self, mock_celery):
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\nprint('code')"]}
        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "has not started yet" in res.get_json()["error"]

        self.challenge.start_time = datetime.utcnow() - timedelta(hours=2)
        self.challenge.end_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 400
        assert "has ended" in res.get_json()["error"]

        self.challenge.end_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202
        assert "queued for execution" in res.get_json()["message"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_rate_limiting_daily_and_task_boundaries(self, mock_celery):
        self.challenge.max_eval_requests = 2
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\nprint('hello')"]}

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 429
        assert "Daily limit reached" in res.get_json()["error"]

        self.challenge.max_eval_requests = 10
        self.task.max_submissions_per_period = 1
        self.task.submission_period_hours = 1
        db.session.commit()

        Submission.query.delete()
        db.session.commit()

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202

        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 429
        assert "Task limit reached" in res.get_json()["error"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_submit_dictionary_cells(self, mock_celery):
        payload = {
            "selected_cells": [
                {"id": 0, "type": "code", "source": "# SUBMIT\nprint('hello dict')"},
                {
                    "id": 1,
                    "type": "code",
                    "source": ["print('hello line 1')\n", "print('hello line 2')"],
                },
            ]
        }
        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202
        assert "queued for execution" in res.get_json()["message"]

    @patch("tasks.evaluate_submission.apply_async")
    def test_submit_task_with_database_custom_eval(self, mock_celery):
        self.task.custom_eval_code = "print('custom evaluation code')"
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\ndef predict(x): return x"]}
        res = self.client.post(
            f"/api/tasks/{self.task.id}/submit",
            headers=self.get_auth_header(self.competitor_token),
            json=payload,
        )
        assert res.status_code == 202

        assert mock_celery.called
        called_args, called_kwargs = mock_celery.call_args
        args = called_kwargs.get("args") or called_args[0]
        assert len(args) == 2
        meta_dict = args[1]
        assert meta_dict.get("is_custom_eval")
        assert meta_dict.get("custom_eval_code") == "print('custom evaluation code')"

    def test_leaderboard_sorting_and_tie_breaking(self):
        u1 = User(
            username="u1",
            role="competitor",
            alias_id="User-One",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        u2 = User(
            username="u2",
            role="competitor",
            alias_id="User-Two",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        u3 = User(
            username="u3",
            role="competitor",
            alias_id="User-Three",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        db.session.add_all([u1, u2, u3])
        db.session.commit()

        s1 = Submission(
            user_id=u1.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.85,
            execution_time_ms=100,
            is_final_selection=True,
            code_cells="[]",
        )
        s2 = Submission(
            user_id=u2.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.90,
            execution_time_ms=200,
            is_final_selection=True,
            code_cells="[]",
        )
        s3 = Submission(
            user_id=u3.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.90,
            execution_time_ms=150,
            is_final_selection=True,
            code_cells="[]",
        )

        db.session.add_all([s1, s2, s3])
        db.session.commit()

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]

        assert leaderboard[0]["user"]["alias_id"] == "User-Three"
        assert leaderboard[1]["user"]["alias_id"] == "User-Two"
        assert leaderboard[2]["user"]["alias_id"] == "User-One"

        Submission.query.delete()
        db.session.commit()

        self.task.metrics_config = json.dumps({"mse": {"weight": 1.0}})
        db.session.commit()

        s1 = Submission(
            user_id=u1.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.15,
            execution_time_ms=100,
            is_final_selection=True,
            code_cells="[]",
        )
        s2 = Submission(
            user_id=u2.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.10,
            execution_time_ms=200,
            is_final_selection=True,
            code_cells="[]",
        )
        s3 = Submission(
            user_id=u3.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.10,
            execution_time_ms=150,
            is_final_selection=True,
            code_cells="[]",
        )

        db.session.add_all([s1, s2, s3])
        db.session.commit()

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]

        assert leaderboard[0]["user"]["alias_id"] == "User-Three"
        assert leaderboard[1]["user"]["alias_id"] == "User-Two"
        assert leaderboard[2]["user"]["alias_id"] == "User-One"

    def test_dynamic_priority_scheduling_calculation(self):
        assert calculate_submission_priority(self.competitor.id, "competitor") == 6

        s1 = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            code_cells="[]",
        )
        db.session.add(s1)
        db.session.commit()
        assert calculate_submission_priority(self.competitor.id, "competitor") == 5

        for _i in range(4):
            s = Submission(
                user_id=self.competitor.id,
                challenge_id=self.challenge.id,
                task_id=self.task.id,
                status="completed",
                public_score=0.8,
                code_cells="[]",
            )
            db.session.add(s)
        db.session.commit()
        assert calculate_submission_priority(self.competitor.id, "competitor") == 1

        for _i in range(5):
            s = Submission(
                user_id=self.competitor.id,
                challenge_id=self.challenge.id,
                task_id=self.task.id,
                status="completed",
                public_score=0.8,
                code_cells="[]",
            )
            db.session.add(s)
        db.session.commit()
        assert calculate_submission_priority(self.competitor.id, "competitor") == 1

    def test_leaderboard_contains_non_submitting_competitors(self):
        non_submitting = User(
            username="lazy_comp",
            role="competitor",
            alias_id="Lazy-One",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        db.session.add(non_submitting)
        db.session.commit()

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]

        aliases = [item["user"]["alias_id"] for item in leaderboard]
        assert "Lazy-One" in aliases
        lazy_item = next(item for item in leaderboard if item["user"]["alias_id"] == "Lazy-One")
        assert lazy_item["public_score"] is None

    def test_update_user_route_jury_restrictions(self):
        jury = User(
            username="jury_user",
            role="jury",
            alias_id="Jury-One",
            password_hash="pbkdf2:sha256:...",
        )
        db.session.add(jury)
        db.session.commit()
        jury_token = generate_token(jury.id, jury.role)

        target_user = User(
            username="edit_me",
            role="competitor",
            alias_id="Edit-Me",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        db.session.add(target_user)
        db.session.commit()

        self.challenge.start_time = datetime.utcnow() + timedelta(days=1)
        db.session.commit()

        res = self.client.put(
            f"/api/admin/users/{target_user.id}",
            headers={"Authorization": f"Bearer {jury_token}"},
            json={
                "name": "NewName",
                "surname": "NewSurname",
                "middle_name": "NewMiddle",
                "birth_date": "2008-01-01",
                "grade": "10",
                "school": "Sofia High",
                "city": "Sofia",
            },
        )
        assert res.status_code == 200

        self.challenge.start_time = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        res = self.client.put(
            f"/api/admin/users/{target_user.id}",
            headers={"Authorization": f"Bearer {jury_token}"},
            json={"name": "StaleName"},
        )
        assert res.status_code == 403
        assert "already started" in res.get_json()["error"]

    def test_download_scores_and_submissions_routes(self):
        jury = User(
            username="jury_downloader",
            role="jury",
            alias_id="Jury-Downloader",
            password_hash="pbkdf2:sha256:...",
        )
        db.session.add(jury)
        db.session.commit()
        jury_token = generate_token(jury.id, jury.role)

        self.challenge.scores_finalized = False
        db.session.commit()

        res = self.client.get(
            f"/api/admin/challenges/{self.challenge.id}/download-scores-csv",
            headers={"Authorization": f"Bearer {jury_token}"},
        )
        assert res.status_code == 400

        res = self.client.get(
            f"/api/admin/challenges/{self.challenge.id}/download-submissions-zip",
            headers={"Authorization": f"Bearer {jury_token}"},
        )
        assert res.status_code == 400

        self.challenge.scores_finalized = True
        db.session.commit()

        res = self.client.get(
            f"/api/admin/challenges/{self.challenge.id}/download-scores-csv",
            headers={"Authorization": f"Bearer {jury_token}"},
        )
        assert res.status_code == 200
        assert res.mimetype == "text/csv"

        res = self.client.get(
            f"/api/admin/challenges/{self.challenge.id}/download-submissions-zip",
            headers={"Authorization": f"Bearer {jury_token}"},
        )
        assert res.status_code == 200
        assert res.mimetype == "application/zip"

    @patch("redis.Redis.from_url")
    def test_sse_live_leaderboard_route(self, mock_redis_cls):
        mock_redis = mock_redis_cls.return_value
        mock_redis.exists.return_value = 0
        mock_pubsub = mock_redis.pubsub.return_value
        mock_pubsub.get_message.return_value = None

        self.client.set_cookie("auth_token", self.competitor_token, domain="localhost")
        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard/live",
        )
        assert res.status_code == 200
        assert res.mimetype == "text/event-stream"
        first_chunk = next(res.response)
        assert b"data: " in first_chunk
        assert b"challenge_title" in first_chunk

    @patch("redis.Redis.from_url")
    def test_sse_live_submissions_route(self, mock_redis_cls):
        mock_redis = mock_redis_cls.return_value
        mock_redis.exists.return_value = 0
        mock_pubsub = mock_redis.pubsub.return_value
        mock_pubsub.get_message.return_value = None

        self.client.set_cookie("auth_token", self.competitor_token, domain="localhost")
        res = self.client.get(
            f"/api/tasks/{self.task.id}/submissions/live",
        )
        assert res.status_code == 200
        assert res.mimetype == "text/event-stream"
        first_chunk = next(res.response)
        assert b"data: " in first_chunk

    def test_blind_review_during_ongoing_competition(self):
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        self.challenge.scores_finalized = False
        db.session.commit()

        jury_user = User(
            username="test_jury_blind",
            role="jury",
            alias_id="Jury-999",
            password_hash="pbkdf2:sha256:...",
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]

        comp_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        assert "name" in comp_item["user"]
        assert comp_item["user"]["name"] == "Jane"

        other_comp = User(
            username="other_comp",
            role="competitor",
            alias_id="Other-Pseudonym",
            password_hash="pbkdf2:sha256:...",
            challenge_id=self.challenge.id,
        )
        other_comp.set_demographics("OtherName", "OtherSurname", "12", "OtherSchool", "OtherCity")
        db.session.add(other_comp)
        db.session.commit()

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        leaderboard = res.get_json()["leaderboard"]
        other_item = next(item for item in leaderboard if item["user"]["id"] == other_comp.id)
        assert "name" not in other_item["user"]
        assert "email" not in other_item["user"]
        assert other_item["user"]["alias_id"] == "Other-Pseudonym"

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]
        for item in leaderboard:
            assert "name" not in item["user"]
            assert "email" not in item["user"]
            assert item["user"]["alias_id"] is not None

        res = self.client.get("/api/admin/users", headers=self.get_auth_header(jury_token))
        assert res.status_code == 200
        users = res.get_json()["items"]
        competitor_users = [u for u in users if u["role"] == "competitor"]
        for u in competitor_users:
            assert "name" not in u
            assert "email" not in u
            assert u["alias_id"] is not None

    def test_challenge_leaderboard_freeze_time(self):
        self.challenge.is_frozen = True
        self.challenge.scores_finalized = False
        db.session.commit()

        res_submit = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json={"task_id": self.task.id, "selected_cells": []},
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res_submit.status_code == 403
        assert "frozen" in res_submit.get_json()["error"]

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200

    @patch("tasks.celery.control.inspect")
    def test_worker_status_endpoint(self, mock_inspect_cls):
        mock_inspect = mock_inspect_cls.return_value

        mock_inspect.ping.return_value = {"celery@gpu-worker": {"ok": "pong"}}
        mock_inspect.registered.return_value = {"celery@gpu-worker": ["tasks.evaluate_submission"]}
        res = self.client.get(
            "/api/worker-status", headers=self.get_auth_header(self.competitor_token)
        )
        assert res.status_code == 200
        assert res.get_json()["status"] == "online"

        mock_inspect.ping.return_value = None
        res = self.client.get(
            "/api/worker-status", headers=self.get_auth_header(self.competitor_token)
        )
        assert res.status_code == 200
        assert res.get_json()["status"] == "offline"

    @patch("tasks.celery.control.inspect")
    def test_detailed_worker_stats_endpoint(self, mock_inspect_cls):
        mock_inspect = mock_inspect_cls.return_value

        mock_inspect.ping.return_value = {"celery@gpu-worker-0": {"ok": "pong"}}
        mock_inspect.stats.return_value = {
            "celery@gpu-worker-0": {
                "pid": 12345,
                "uptime": 3600,
                "pool": {"max-concurrency": 4},
                "total": {"evaluate_submission": 12},
                "broker": {"transport": "redis", "hostname": "localhost", "port": 6379},
            }
        }
        mock_inspect.active.return_value = {
            "celery@gpu-worker-0": [{"id": "task-uuid-1", "name": "tasks.evaluate_submission"}]
        }
        mock_inspect.reserved.return_value = {"celery@gpu-worker-0": []}
        mock_inspect.registered.return_value = {
            "celery@gpu-worker-0": ["tasks.evaluate_submission"]
        }

        res = self.client.get(
            "/api/admin/workers/stats",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 403

        res = self.client.get(
            "/api/admin/workers/stats", headers=self.get_auth_header(self.admin_token)
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["connected_workers_count"] == 1
        assert data["workers"][0]["name"] == "celery@gpu-worker-0"
        assert data["workers"][0]["pool_size"] == 4
        assert data["workers"][0]["active_tasks_count"] == 1

    def test_leaderboard_late_processed_submission_override(self):
        self.challenge.end_time = datetime.utcnow() - timedelta(minutes=15)
        self.challenge.scores_finalized = False
        db.session.commit()

        Submission.query.filter_by(user_id=self.competitor.id).delete()
        db.session.commit()

        s_final = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.75,
            is_final_selection=True,
            created_at=self.challenge.end_time - timedelta(minutes=10),
            executed_at=self.challenge.end_time - timedelta(minutes=9),
            code_cells="[]",
        )

        s_late = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.95,
            is_final_selection=False,
            created_at=self.challenge.end_time - timedelta(minutes=2),
            executed_at=self.challenge.end_time + timedelta(minutes=5),
            code_cells="[]",
        )
        db.session.add_all([s_final, s_late])
        db.session.commit()

        res = self.client.get(
            f"/api/tasks/{self.task.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        leaderboard = res.get_json()["leaderboard"]
        comp_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        assert comp_item["public_score"] == 0.95

    def test_task_creation_parameter_validation(self):
        admin_header = self.get_auth_header(self.admin_token)
        import io

        data = {
            "title": "Missing Baseline Task",
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 400
        assert "Baseline notebook is required" in res.get_json()["error"]

        data = {
            "title": "Invalid RAM Task",
            "ram_limit_mb": 20000,
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 400
        assert "cannot exceed 16384 MB" in res.get_json()["error"]

        data = {
            "title": "Invalid Image Task",
            "base_docker_image": "python:3.10-slim; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 400
        assert "Invalid base Docker image" in res.get_json()["error"]

        data = {
            "title": "Invalid APT Task",
            "apt_packages": "curl, htop; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 400
        assert "Invalid APT package name" in res.get_json()["error"]

        data = {
            "title": "Invalid Pip Task",
            "pip_requirements": "numpy>=1.20.0\nrequests; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 400
        assert "Invalid pip requirement line" in res.get_json()["error"]

    def test_jury_custom_environment_restrictions(self):
        jury_user = User(username="test_jury_env", password_hash="pbkdf2:sha256:...", role="jury")
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)
        jury_header = self.get_auth_header(jury_token)

        import io

        data = {
            "title": "Jury Custom Env Task",
            "base_docker_image": "python:3.10-slim",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks", data=data, headers=jury_header
        )
        assert res.status_code == 403
        assert "Only administrators are allowed" in res.get_json()["error"]

        task = Task(
            challenge_id=self.challenge.id,
            title="Clean Task",
            description="No custom env",
            ram_limit_mb=1024,
            time_limit_sec=60,
        )
        db.session.add(task)
        db.session.commit()

        data = {"base_docker_image": "python:3.10-slim"}
        res = self.client.put(f"/api/tasks/{task.id}", data=data, headers=jury_header)
        assert res.status_code == 403
        assert "Only administrators are allowed" in res.get_json()["error"]

        admin_header = self.get_auth_header(self.admin_token)
        res = self.client.put(f"/api/tasks/{task.id}", data=data, headers=admin_header)
        assert res.status_code == 200

    @patch("cache_utils.delete_cached")
    @patch("utils.cache_helpers.set_cached")
    @patch("utils.cache_helpers.get_cached")
    def test_cache_invalidation_workflows(self, mock_get, mock_set, mock_delete):
        mock_get.return_value = None

        competitor_header = self.get_auth_header(self.competitor_token)
        res = self.client.get(f"/api/challenges/{self.challenge.id}", headers=competitor_header)
        assert res.status_code == 200

        mock_set.assert_any_call(
            f"challenge:{self.challenge.id}:competitor", res.get_json(), timeout=600
        )

        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(self.challenge.id, delete_only=True)
        mock_delete.assert_any_call(f"leaderboard:raw:{self.challenge.id}:frozen")
        mock_delete.assert_any_call(f"leaderboard:raw:{self.challenge.id}:unfrozen")

        mock_delete.reset_mock()

        admin_header = self.get_auth_header(self.admin_token)
        import io

        data = {
            "title": "New Test Task",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), "baseline.ipynb"),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), "solution.ipynb"),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/tasks",
            data=data,
            headers=admin_header,
        )
        assert res.status_code == 201
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")

        mock_delete.reset_mock()
        new_task_id = res.get_json()["id"]

        update_data = {"title": "Updated Test Task Title"}
        res = self.client.put(f"/api/tasks/{new_task_id}", data=update_data, headers=admin_header)
        assert res.status_code == 200
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")

        mock_delete.reset_mock()

        res = self.client.delete(f"/api/tasks/{new_task_id}", headers=admin_header)
        assert res.status_code == 200
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")

    @patch("tasks.evaluate_submission.delay")
    def test_challenge_submission_route_and_ast_rule_engine(self, mock_celery):
        comp_header = self.get_auth_header(self.competitor_token)

        payload = {"selected_cells": ["print('hello')"]}
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json=payload,
            headers=comp_header,
        )
        assert res.status_code == 400
        assert "task_id is required" in res.get_json()["error"]

        payload = {"selected_cells": ["print('hello')"], "task_id": 99999}
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json=payload,
            headers=comp_header,
        )
        assert res.status_code == 400
        assert "Invalid task_id" in res.get_json()["error"]

        self.task.banned_imports = "os,sys,subprocess"
        db.session.commit()

        payload = {
            "selected_cells": ["import os\nprint('hack')"],
            "task_id": self.task.id,
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json=payload,
            headers=comp_header,
        )
        assert res.status_code == 400
        assert "Import of library 'os' is banned" in res.get_json()["error"]

        self.task.ban_magic_commands = True
        self.task.banned_imports = ""
        db.session.commit()

        payload = {"selected_cells": ["!pip install requests"], "task_id": self.task.id}
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json=payload,
            headers=comp_header,
        )
        assert res.status_code == 400
        assert "magic commands" in res.get_json()["error"]

        payload = {
            "selected_cells": ["# SUBMIT\nprint('hello')"],
            "task_id": self.task.id,
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            json=payload,
            headers=comp_header,
        )
        assert res.status_code == 202

        sub_id = res.get_json()["submission_id"]
        submission = db.session.get(Submission, sub_id)
        assert submission is not None
        assert submission.task_id == self.task.id
        assert submission.challenge_id == self.challenge.id

    def test_docs_secure_access(self):
        comp_header = self.get_auth_header(self.competitor_token)
        jury_token = generate_token(999, "jury")
        jury_header = self.get_auth_header(jury_token)
        admin_header = self.get_auth_header(self.admin_token)

        res = self.client.get("/api/docs/student", headers=comp_header)
        assert res.status_code == 200
        res = self.client.get("/api/docs/student", headers=jury_header)
        assert res.status_code == 200
        res = self.client.get("/api/docs/student", headers=admin_header)
        assert res.status_code == 200

        res = self.client.get("/api/docs/jury", headers=comp_header)
        assert res.status_code == 403
        res = self.client.get("/api/docs/jury", headers=jury_header)
        assert res.status_code == 200
        res = self.client.get("/api/docs/jury", headers=admin_header)
        assert res.status_code == 200

        res = self.client.get("/api/docs/admin", headers=comp_header)
        assert res.status_code == 403
        res = self.client.get("/api/docs/admin", headers=jury_header)
        assert res.status_code == 403
        res = self.client.get("/api/docs/admin", headers=admin_header)
        assert res.status_code == 200

        res = self.client.get("/api/docs/api-reference", headers=admin_header)
        assert res.status_code == 404

    def test_bulgarian_name_transliteration(self):
        payload = {
            "name": "Иван",
            "middle_name": "Георгиев",
            "surname": "Петров",
            "birth_date": "2008-05-14",
            "grade": "10",
            "school": "Sofia High",
            "city": "Sofia",
            "challenge_id": self.challenge.id,
        }
        res = self.client.post(
            "/api/admin/register-competitor",
            headers=self.get_auth_header(self.admin_token),
            json=payload,
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        username = data["generated_username"]
        assert username.startswith("comp_iva_pet_")

    def test_csv_import_anonymity_support(self):
        csv_data = (
            "name,surname,middle_name,birth_date,grade,school,city,is_anonymous\n"
            "Ivan,Petrov,Georgiev,2008-05-14,10,Sofia High,Sofia,1\n"
            "Maria,Georgieva,Stoyanova,2007-06-15,11,Plovdiv High,Plovdiv,0\n"
        )
        import io

        res = self.client.post(
            f"/api/admin/import-competitors-csv?challenge_id={self.challenge.id}",
            headers=self.get_auth_header(self.admin_token),
            data={"file": (io.BytesIO(csv_data.encode("utf-8")), "competitors.csv")},
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert len(data["competitors"]) == 2

        ivan = User.query.filter_by(username=data["competitors"][0]["generated_username"]).first()
        assert ivan is not None
        assert ivan.is_anonymous

        maria = User.query.filter_by(username=data["competitors"][1]["generated_username"]).first()
        assert maria is not None
        assert maria.is_anonymous is False

    def test_reset_user_password_routes(self):
        jury_user = User(
            username="test_jury_pwd",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Oracle-pwd",
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        res = self.client.post(
            f"/api/admin/users/{self.competitor.id}/reset-password",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "password" in data

        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f"/api/admin/users/{self.competitor.id}/reset-password",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200

        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f"/api/admin/users/{self.competitor.id}/reset-password",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 403

    def test_reset_all_challenge_passwords_routes(self):
        jury_user = User(
            username="test_jury_pwd2",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Oracle-pwd2",
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        res = self.client.post(
            f"/api/admin/challenges/{self.challenge.id}/reset-all-passwords",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "reset_accounts" in data
        assert len(data["reset_accounts"]) > 0
        account = data["reset_accounts"][0]
        assert "middle_name" in account
        assert "birth_date" in account

        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f"/api/admin/challenges/{self.challenge.id}/reset-all-passwords",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200

        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f"/api/admin/challenges/{self.challenge.id}/reset-all-passwords",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 403

    def test_search_competitors_privacy_constraints(self):
        jury_user = User(
            username="test_jury_search",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Search-001",
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        self.challenge.start_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

        res = self.client.get(
            "/api/admin/users?role=competitor&search=Sofia",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert any(u["id"] == self.competitor.id for u in data["items"])

        res = self.client.get(
            "/api/admin/users?role=competitor&search=test_comp",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert any(u["id"] == self.competitor.id for u in data["items"])

        res = self.client.get(
            "/api/admin/users?role=competitor&search=Stellar",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert any(u["id"] == self.competitor.id for u in data["items"])

        self.challenge.start_time = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()

        res = self.client.get(
            "/api/admin/users?role=competitor&search=Sofia",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert not any(u["id"] == self.competitor.id for u in data["items"])

        res = self.client.get(
            "/api/admin/users?role=competitor&search=test_comp",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert not any(u["id"] == self.competitor.id for u in data["items"])

        res = self.client.get(
            "/api/admin/users?role=competitor&search=Stellar",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert any(u["id"] == self.competitor.id for u in data["items"])

        res = self.client.get(
            "/api/admin/users?role=competitor&search=Sofia",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert any(u["id"] == self.competitor.id for u in data["items"])

    def test_competitor_anonymity_privacy_constraints(self):
        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(self.challenge.id)

        anon_comp = User(
            username="anon_student",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Ghost-Rider-777",
            challenge_id=self.challenge.id,
            is_anonymous=True,
        )
        anon_comp.set_demographics("John", "Doe", "11", "Varna High", "Varna")
        db.session.add(anon_comp)
        db.session.commit()

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        leaderboard = data["leaderboard"]

        anon_entry = next(e for e in leaderboard if e["user"]["id"] == anon_comp.id)
        assert "name" not in anon_entry["user"]
        assert "school" not in anon_entry["user"]
        assert "city" not in anon_entry["user"]

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        leaderboard = data["leaderboard"]

        anon_entry_admin = next(e for e in leaderboard if e["user"]["id"] == anon_comp.id)
        assert anon_entry_admin["user"]["name"] == "John"
        assert anon_entry_admin["user"]["school"] == "Varna High"
        assert anon_entry_admin["user"]["city"] == "Varna"

    def test_manual_points_entry_and_leaderboard_ranking(self):
        s_comp = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            private_score=0.85,
        )
        db.session.add(s_comp)
        db.session.commit()

        self.challenge.scores_finalized = True
        self.challenge.reveal_results = False
        db.session.commit()

        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(self.challenge.id)

        payload = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 85},
            "reason": "Correcting grade error after finalization",
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self.get_auth_header(self.jury_token),
        )
        assert res.status_code == 200
        assert res.get_json()["manual_points"][str(self.task.id)] == 85

        comp2 = User(
            username="competitor_two",
            email="comp2@example.com",
            role="competitor",
            password_hash="pbkdf2:sha256:placeholder",
            challenge_id=self.challenge.id,
        )
        comp2.set_demographics("Mary", "Jane", "11", "Sofia High", "Sofia")
        db.session.add(comp2)
        db.session.commit()

        s_comp2 = Submission(
            user_id=comp2.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            private_score=0.85,
        )
        db.session.add(s_comp2)
        db.session.commit()

        payload2 = {
            "user_id": comp2.id,
            "points": {str(self.task.id): 95},
            "reason": "Correcting grade error after finalization",
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            data=json.dumps(payload2),
            content_type="application/json",
            headers=self.get_auth_header(self.jury_token),
        )
        assert res.status_code == 200

        self.challenge.reveal_results = True
        db.session.commit()
        from cache_utils import invalidate_leaderboard_cache

        invalidate_leaderboard_cache(self.challenge.id)

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}/leaderboard",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        data = res.get_json()
        leaderboard = data["leaderboard"]

        assert leaderboard[0]["user"]["id"] == comp2.id
        assert leaderboard[0]["total_points"] == 95
        assert leaderboard[0]["rank"] == 1

        assert leaderboard[1]["user"]["id"] == self.competitor.id
        assert leaderboard[1]["total_points"] == 85
        assert leaderboard[1]["rank"] == 2

    def test_submission_blocked_when_competition_finalized(self):
        self.challenge.scores_finalized = True
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            data=json.dumps(
                {
                    "task_id": self.task.id,
                    "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}],
                }
            ),
            content_type="application/json",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 403
        assert "Submissions are disabled for finalized competitions" in res.get_json()["error"]

        self.challenge.scores_finalized = False
        db.session.commit()

    def test_finalize_constraints_and_permissions(self):
        self.challenge.scores_finalized = False
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=2)
        # Create a submission so competitor is required to have manual points
        sub = Submission(
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            user_id=self.competitor.id,
            status="completed",
            public_score=80.0,
            private_score=85.0,
        )
        db.session.add(sub)
        db.session.commit()

        jury = User(
            username="jury_member_test",
            email="jury_test@example.com",
            role="jury",
            password_hash="pbkdf2:sha256:placeholder",
        )
        db.session.add(jury)
        db.session.commit()

        jury_token = generate_token(jury.id, "jury")

        res_before = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res_before.status_code == 400
        assert "before its end time" in res_before.get_json()["error"].lower()

        self.challenge.end_time = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 403

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 400
        assert "missing manual points" in res.get_json()["error"]

        self.competitor.manual_points = {str(self.task.id): 90}
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        assert self.challenge.scores_finalized

    def test_stages_crud_finalization_and_submission_boundaries(self):
        jury = User(
            username="jury_member_stage_test",
            email="jury_stage_test@example.com",
            role="jury",
            password_hash="pbkdf2:sha256:placeholder",
        )
        db.session.add(jury)
        db.session.commit()

        jury_token = generate_token(jury.id, "jury")

        self.challenge.start_time = datetime.utcnow() - timedelta(hours=5)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=24)
        db.session.commit()

        payload = {
            "title": "Stage 1",
            "stage_number": 1,
            "start_time": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages",
            data=json.dumps(payload),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 201
        stage_data = res.get_json()
        stage_id = stage_data["id"]
        assert stage_data["title"] == "Stage 1"

        payload_update = {"title": "Stage 1 Updated"}
        res = self.client.put(
            f"/api/challenges/{self.challenge.id}/stages/{stage_id}",
            data=json.dumps(payload_update),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        stage_data = res.get_json()
        assert stage_data["title"] == "Stage 1 Updated"

        future_payload = {
            "title": "Future Stage",
            "stage_number": 2,
            "start_time": (datetime.utcnow() + timedelta(hours=10)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=11)).isoformat(),
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages",
            data=json.dumps(future_payload),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 201
        future_stage_id = res.get_json()["id"]

        self.task.stage_id = future_stage_id
        db.session.commit()

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        assert len(res.get_json()["tasks"]) == 0

        res = self.client.get(
            f"/api/tasks/{self.task.id}",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code in [403, 404]

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            data=json.dumps(
                {
                    "task_id": self.task.id,
                    "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}],
                }
            ),
            content_type="application/json",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 400
        assert "has not started yet" in res.get_json()["error"]

        # Try to finalize before the stage has ended
        res_before = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res_before.status_code == 400
        assert "before its end time" in res_before.get_json()["error"].lower()

        from models import Stage

        stage2 = db.session.get(Stage, future_stage_id)
        stage2.start_time = datetime.utcnow() - timedelta(hours=2)
        stage2.end_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        from cache_utils import invalidate_challenge_cache

        invalidate_challenge_cache(self.challenge.id)

        res = self.client.get(
            f"/api/challenges/{self.challenge.id}",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        assert len(res.get_json()["tasks"]) == 1

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/submit",
            data=json.dumps(
                {
                    "task_id": self.task.id,
                    "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}],
                }
            ),
            content_type="application/json",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 400
        assert "has passed" in res.get_json()["error"]

        from models import Submission

        db.session.add(
            Submission(
                user_id=self.competitor.id,
                challenge_id=self.challenge.id,
                task_id=self.task.id,
                status="completed",
            )
        )
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize",
            data=json.dumps({}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 400
        assert "missing manual points" in res.get_json()["error"]

        self.competitor.manual_points = {str(self.task.id): 85}
        db.session.commit()

        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res.status_code == 200
        assert res.get_json()["is_finalized"]

        # Verify repeat stage finalization returns 400
        res_repeat = self.client.post(
            f"/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize",
            data=json.dumps({"reveal_results": True}),
            content_type="application/json",
            headers=self.get_auth_header(jury_token),
        )
        assert res_repeat.status_code == 400
        assert "already finalized" in res_repeat.get_json()["error"].lower()

        self.challenge.is_archived = True
        db.session.commit()

        from werkzeug.security import generate_password_hash

        self.competitor.password_hash = generate_password_hash(
            "my-competitor-password", method="pbkdf2:sha256"
        )
        db.session.commit()

        login_res = self.client.post(
            "/api/auth/login",
            data=json.dumps(
                {
                    "username": self.competitor.username,
                    "password": "my-competitor-password",
                }
            ),
            content_type="application/json",
        )
        assert login_res.status_code == 403
        assert "archived" in login_res.get_json()["error"]

        self.challenge.is_archived = False
        db.session.commit()

        comp_in_db = User.query.filter_by(challenge_id=self.challenge.id, role="competitor").first()
        assert comp_in_db is not None

        res = self.client.delete(
            f"/api/challenges/{self.challenge.id}",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res.status_code == 200

        comp_in_db = User.query.filter_by(challenge_id=self.challenge.id, role="competitor").first()
        assert comp_in_db is None

    def test_archived_challenges_visibility(self):
        self.challenge.is_archived = True
        db.session.commit()
        from cache_utils import invalidate_challenge_cache

        invalidate_challenge_cache(self.challenge.id)

        res_list = self.client.get(
            "/api/challenges", headers=self.get_auth_header(self.competitor_token)
        )
        assert res_list.status_code == 200
        assert len(res_list.get_json()) == 0

        res_detail = self.client.get(
            f"/api/challenges/{self.challenge.id}",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res_detail.status_code == 404

        res_admin = self.client.get(
            f"/api/challenges/{self.challenge.id}",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res_admin.status_code == 200
        assert res_admin.get_json()["is_archived"] is True

        self.challenge.is_archived = False
        db.session.commit()
        invalidate_challenge_cache(self.challenge.id)

    def test_manual_points_audit_and_constraints(self):
        s_comp = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="completed",
            public_score=0.8,
            private_score=0.85,
        )
        db.session.add(s_comp)
        db.session.commit()

        self.challenge.scores_finalized = True
        self.challenge.reveal_results = False
        db.session.commit()

        payload_no_reason = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 50},
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            data=json.dumps(payload_no_reason),
            content_type="application/json",
            headers=self.get_auth_header(self.jury_token),
        )
        assert res.status_code == 400
        assert "justification reason is mandatory" in res.get_json()["error"]

        payload_with_reason = {
            "user_id": self.competitor.id,
            "points": {str(self.task.id): 60},
            "reason": "Scoring correction post finalization",
        }
        res = self.client.post(
            f"/api/challenges/{self.challenge.id}/manual-points",
            data=json.dumps(payload_with_reason),
            content_type="application/json",
            headers=self.get_auth_header(self.jury_token),
        )
        assert res.status_code == 200

        from models import AuditLog

        logs = AuditLog.query.filter_by(target_user_id=self.competitor.id).all()
        assert len(logs) == 1
        assert logs[0].new_score == 60
        assert logs[0].reason == "Scoring correction post finalization"

    def test_results_export(self):
        res_comp = self.client.get(
            f"/api/challenges/{self.challenge.id}/export-results",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res_comp.status_code == 403

        res_admin = self.client.get(
            f"/api/challenges/{self.challenge.id}/export-results",
            headers=self.get_auth_header(self.admin_token),
        )
        assert res_admin.status_code == 200
        assert res_admin.mimetype == "text/csv"
        csv_data = res_admin.data.decode("utf-8")
        assert "Rank,Username,Alias ID" in csv_data
        assert "--- SCORE CORRECTION AUDIT LOG ---" in csv_data

    def test_stream_submission_logs(self):
        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status="queued",
            detailed_status="queued",
            code_cells="[]",
        )
        db.session.add(sub)
        db.session.commit()

        res = self.client.get(
            f"/api/submissions/{sub.id}/logs/live",
            headers=self.get_auth_header(self.competitor_token),
        )
        assert res.status_code == 200
        assert res.mimetype == "text/event-stream"
