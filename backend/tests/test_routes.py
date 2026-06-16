import os
import sys
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

# Set environment variable before any flask imports to force in-memory SQLite
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Add backend directory to path so we can import from it
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token
from services.submission_service import calculate_submission_priority

class TestRouteLevelLogic(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Flush cache to avoid cross-test contamination
        from cache_utils import get_redis_client
        r = get_redis_client()
        if r:
            try:
                r.flushdb()
            except Exception:
                pass
                
        db.create_all()
        self.seed_basic_data()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

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
        db.session.commit() # Get challenge ID

        # Create a competitor user
        self.competitor = User(
            username="test_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Stellar-Voyager-101",
            challenge_id=self.challenge.id
        )
        # Demographic fields are encrypted internally by the model
        self.competitor.set_demographics("Jane", "Doe", "12", "Sofia High", "Sofia")
        db.session.add(self.competitor)

        # Create a task under the challenge
        self.task = Task(
            challenge_id=self.challenge.id,
            title="Classification Task",
            description="Predict movie ratings.",
            ram_limit_mb=4096,
            time_limit_sec=60,
            gpu_required=False,
            files="[]"
        )
        db.session.add(self.task)
        db.session.commit()

        # Save tokens for authentication
        self.admin_token = generate_token(self.admin.id, self.admin.role)
        self.competitor_token = generate_token(self.competitor.id, self.competitor.role)

    def get_auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_role_authorization_admin_vs_competitor(self):
        """Competitors should be denied access to admin routes, whereas admins should be allowed."""
        # Competitor tries to list users
        res = self.client.get('/api/admin/users', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 403)
        self.assertIn("Requires role", res.get_json()["error"])

        # Admin lists users
        res = self.client.get('/api/admin/users', headers=self.get_auth_header(self.admin_token))
        self.assertEqual(res.status_code, 200)
        self.assertIn("items", res.get_json())

    @patch('tasks.evaluate_submission.apply_async')
    def test_competition_schedule_boundaries(self, mock_celery):
        """Competitor submissions should fail if competition hasn't started or has ended."""
        # Case A: Before Start Time
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\nprint('code')"]}
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token),
                               json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("has not started yet", res.get_json()["error"])

        # Case B: After End Time
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=2)
        self.challenge.end_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()

        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token),
                               json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("has ended", res.get_json()["error"])

        # Case C: Active Competition
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token),
                               json=payload)
        self.assertEqual(res.status_code, 202)
        self.assertIn("queued for execution", res.get_json()["message"])

    @patch('tasks.evaluate_submission.apply_async')
    def test_rate_limiting_daily_and_task_boundaries(self, mock_celery):
        """Competitor submissions should fail if daily challenge limit or task period limit is hit."""
        # Set daily limit on challenge to 2
        self.challenge.max_eval_requests = 2
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\nprint('hello')"]}
        
        # 1st Submission: success
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token), json=payload)
        self.assertEqual(res.status_code, 202)

        # 2nd Submission: success
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token), json=payload)
        self.assertEqual(res.status_code, 202)

        # 3rd Submission: fails (daily limit)
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token), json=payload)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Daily limit reached", res.get_json()["error"])

        # Reset daily limits and test task-specific rate limits
        self.challenge.max_eval_requests = 10
        self.task.max_submissions_per_period = 1
        self.task.submission_period_hours = 1
        db.session.commit()

        # Delete old submissions so daily limit doesn't interfere
        Submission.query.delete()
        db.session.commit()

        # 1st Submission: success
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token), json=payload)
        self.assertEqual(res.status_code, 202)

        # 2nd Submission: fails (task limit)
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token), json=payload)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Task limit reached", res.get_json()["error"])

    @patch('tasks.evaluate_submission.apply_async')
    def test_submit_dictionary_cells(self, mock_celery):
        """Competitor submissions with notebook cells format (dictionaries) should succeed."""
        payload = {
            "selected_cells": [
                {"id": 0, "type": "code", "source": "# SUBMIT\nprint('hello dict')"},
                {"id": 1, "type": "code", "source": ["print('hello line 1')\n", "print('hello line 2')"]}
            ]
        }
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token),
                               json=payload)
        self.assertEqual(res.status_code, 202)
        self.assertIn("queued for execution", res.get_json()["message"])

    @patch('tasks.evaluate_submission.apply_async')
    def test_submit_task_with_database_custom_eval(self, mock_celery):
        """Task submission with database-defined custom_eval_code should trigger custom evaluation."""
        self.task.custom_eval_code = "print('custom evaluation code')"
        db.session.commit()

        payload = {"selected_cells": ["# SUBMIT\ndef predict(x): return x"]}
        res = self.client.post(f'/api/tasks/{self.task.id}/submit', 
                               headers=self.get_auth_header(self.competitor_token),
                               json=payload)
        self.assertEqual(res.status_code, 202)
        
        # Verify the celery task was called with correct metadata
        self.assertTrue(mock_celery.called)
        called_args, called_kwargs = mock_celery.call_args
        args = called_kwargs.get("args") or called_args[0]
        self.assertEqual(len(args), 2)
        meta_dict = args[1]
        self.assertTrue(meta_dict.get("is_custom_eval"))
        self.assertEqual(meta_dict.get("custom_eval_code"), "print('custom evaluation code')")

    def test_leaderboard_sorting_and_tie_breaking(self):
        """Leaderboard should sort correctly and break ties using execution time (speed)."""
        # Create users for rankings with valid password hashes to satisfy NOT NULL constraints
        u1 = User(username="u1", role="competitor", alias_id="User-One", password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        u2 = User(username="u2", role="competitor", alias_id="User-Two", password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        u3 = User(username="u3", role="competitor", alias_id="User-Three", password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        db.session.add_all([u1, u2, u3])
        db.session.commit()

        # Case A: Accuracy (Higher is better)
        # Setup final submissions:
        # u1 gets score 0.85, execution time 100ms
        # u2 gets score 0.90, execution time 200ms
        # u3 gets score 0.90, execution time 150ms (same score, faster than u2)
        s1 = Submission(user_id=u1.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.85, execution_time_ms=100, is_final_selection=True,
                        code_cells="[]")
        s2 = Submission(user_id=u2.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.90, execution_time_ms=200, is_final_selection=True,
                        code_cells="[]")
        s3 = Submission(user_id=u3.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.90, execution_time_ms=150, is_final_selection=True,
                        code_cells="[]")
        
        db.session.add_all([s1, s2, s3])
        db.session.commit()

        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        
        # Expected rank order: User-Three (0.90, 150ms) -> User-Two (0.90, 200ms) -> User-One (0.85, 100ms)
        self.assertEqual(leaderboard[0]["user"]["alias_id"], "User-Three")
        self.assertEqual(leaderboard[1]["user"]["alias_id"], "User-Two")
        self.assertEqual(leaderboard[2]["user"]["alias_id"], "User-One")

        # Cleanup submissions
        Submission.query.delete()
        db.session.commit()

        # Case B: MSE (Lower is better)
        self.task.metrics_config = json.dumps({"mse": {"weight": 1.0}})
        db.session.commit()

        # Setup final submissions:
        # u1 gets score 0.15, execution time 100ms
        # u2 gets score 0.10, execution time 200ms
        # u3 gets score 0.10, execution time 150ms (same score, faster than u2)
        s1 = Submission(user_id=u1.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.15, execution_time_ms=100, is_final_selection=True,
                        code_cells="[]")
        s2 = Submission(user_id=u2.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.10, execution_time_ms=200, is_final_selection=True,
                        code_cells="[]")
        s3 = Submission(user_id=u3.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.10, execution_time_ms=150, is_final_selection=True,
                        code_cells="[]")
        
        db.session.add_all([s1, s2, s3])
        db.session.commit()

        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]

        # Expected rank order (lower score is better): User-Three (0.10, 150ms) -> User-Two (0.10, 200ms) -> User-One (0.15, 100ms)
        self.assertEqual(leaderboard[0]["user"]["alias_id"], "User-Three")
        self.assertEqual(leaderboard[1]["user"]["alias_id"], "User-Two")
        self.assertEqual(leaderboard[2]["user"]["alias_id"], "User-One")

    def test_dynamic_priority_scheduling_calculation(self):
        """Priority level must decay dynamically based on user's daily submission count."""
        # 0 submissions today: priority 6
        self.assertEqual(calculate_submission_priority(self.competitor.id, "competitor"), 6)

        # Add 1 submission
        s1 = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                        status="completed", public_score=0.8, code_cells="[]")
        db.session.add(s1)
        db.session.commit()
        # 1 submission today: priority 5
        self.assertEqual(calculate_submission_priority(self.competitor.id, "competitor"), 5)

        # Add 4 more submissions (total 5)
        for i in range(4):
            s = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                           status="completed", public_score=0.8, code_cells="[]")
            db.session.add(s)
        db.session.commit()
        # 5 submissions today: priority 1
        self.assertEqual(calculate_submission_priority(self.competitor.id, "competitor"), 1)

        # Add 5 more submissions (total 10)
        for i in range(5):
            s = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                           status="completed", public_score=0.8, code_cells="[]")
            db.session.add(s)
        db.session.commit()
        # priority remains capped at minimum 1
        self.assertEqual(calculate_submission_priority(self.competitor.id, "competitor"), 1)

    def test_leaderboard_contains_non_submitting_competitors(self):
        """Leaderboard must include registered competitors even if they have not submitted anything."""
        # Create a competitor who hasn't submitted
        non_submitting = User(username="lazy_comp", role="competitor", alias_id="Lazy-One", 
                               password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        db.session.add(non_submitting)
        db.session.commit()
        
        # Fetch leaderboard
        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        
        # Verify the non-submitting competitor is present at the end
        aliases = [item["user"]["alias_id"] for item in leaderboard]
        self.assertIn("Lazy-One", aliases)
        # Check that their score is None
        lazy_item = next(item for item in leaderboard if item["user"]["alias_id"] == "Lazy-One")
        self.assertIsNone(lazy_item["public_score"])

    def test_update_user_route_jury_restrictions(self):
        """Jury should be able to edit user details before the competition starts but not after."""
        # Create a jury user
        jury = User(username="jury_user", role="jury", alias_id="Jury-One", password_hash="pbkdf2:sha256:...")
        db.session.add(jury)
        db.session.commit()
        jury_token = generate_token(jury.id, jury.role)
        
        # competitor that we want to update
        target_user = User(username="edit_me", role="competitor", alias_id="Edit-Me", 
                           password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        db.session.add(target_user)
        db.session.commit()
        
        # 1. Update when start_time is in the future
        self.challenge.start_time = datetime.utcnow() + timedelta(days=1)
        db.session.commit()
        
        res = self.client.put(f'/api/admin/users/{target_user.id}', 
                               headers={"Authorization": f"Bearer {jury_token}"},
                               json={"name": "NewName", "surname": "NewSurname"})
        self.assertEqual(res.status_code, 200)
        
        # 2. Try to update when start_time is in the past
        self.challenge.start_time = datetime.utcnow() - timedelta(days=1)
        db.session.commit()
        
        res = self.client.put(f'/api/admin/users/{target_user.id}', 
                               headers={"Authorization": f"Bearer {jury_token}"},
                               json={"name": "StaleName"})
        self.assertEqual(res.status_code, 403)
        self.assertIn("already started", res.get_json()["error"])

    def test_download_scores_and_submissions_routes(self):
        """Jury/Admin should be able to download scores CSV and submissions ZIP after finalization."""
        # Create a jury token
        jury = User(username="jury_downloader", role="jury", alias_id="Jury-Downloader", password_hash="pbkdf2:sha256:...")
        db.session.add(jury)
        db.session.commit()
        jury_token = generate_token(jury.id, jury.role)
        
        # 1. Try before finalization
        self.challenge.scores_finalized = False
        db.session.commit()
        
        res = self.client.get(f'/api/admin/challenges/{self.challenge.id}/download-scores-csv', 
                              headers={"Authorization": f"Bearer {jury_token}"})
        self.assertEqual(res.status_code, 400)
        
        res = self.client.get(f'/api/admin/challenges/{self.challenge.id}/download-submissions-zip', 
                              headers={"Authorization": f"Bearer {jury_token}"})
        self.assertEqual(res.status_code, 400)
        
        # 2. Try after finalization
        self.challenge.scores_finalized = True
        db.session.commit()
        
        res = self.client.get(f'/api/admin/challenges/{self.challenge.id}/download-scores-csv', 
                              headers={"Authorization": f"Bearer {jury_token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "text/csv")
        
        res = self.client.get(f'/api/admin/challenges/{self.challenge.id}/download-submissions-zip', 
                              headers={"Authorization": f"Bearer {jury_token}"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/zip")

    @patch('redis.Redis.from_url')
    def test_sse_live_leaderboard_route(self, mock_redis_cls):
        """Leaderboard live SSE endpoint should authenticate and stream data."""
        mock_redis = mock_redis_cls.return_value
        mock_redis.exists.return_value = 0  # Token revocation check
        mock_pubsub = mock_redis.pubsub.return_value
        mock_pubsub.get_message.return_value = None

        res = self.client.get(
            f'/api/tasks/{self.task.id}/leaderboard/live',
            query_string={'token': self.competitor_token}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/event-stream')
        # Consume the first yielded chunk of data
        first_chunk = next(res.response)
        self.assertIn(b"data: ", first_chunk)
        self.assertIn(b"challenge_title", first_chunk)

    @patch('redis.Redis.from_url')
    def test_sse_live_submissions_route(self, mock_redis_cls):
        """Submissions live SSE endpoint should authenticate and stream data."""
        mock_redis = mock_redis_cls.return_value
        mock_redis.exists.return_value = 0  # Token revocation check
        mock_pubsub = mock_redis.pubsub.return_value
        mock_pubsub.get_message.return_value = None

        res = self.client.get(
            f'/api/tasks/{self.task.id}/submissions/live',
            query_string={'token': self.competitor_token}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/event-stream')
        first_chunk = next(res.response)
        self.assertIn(b"data: ", first_chunk)

    def test_blind_review_during_ongoing_competition(self):
        """Even when competition is started and not finalized/ended, judges (jury) and other competitors must only get pseudonym/alias details and not personal demographics."""
        # 1. Set the competition to be started (start_time in the past) and not finalized
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        self.challenge.scores_finalized = False
        db.session.commit()

        # Create a jury token
        jury_user = User(username="test_jury_blind", role="jury", alias_id="Jury-999", password_hash="pbkdf2:sha256:...")
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        # A. Competitor querying the leaderboard
        # They should see details of themselves, but not others
        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        
        # self.competitor is the competitor requesting. They should see their own details:
        comp_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        self.assertIn("name", comp_item["user"])
        self.assertEqual(comp_item["user"]["name"], "Jane") # Decrypted correctly for self

        # Let's add another competitor to the challenge
        other_comp = User(username="other_comp", role="competitor", alias_id="Other-Pseudonym", password_hash="pbkdf2:sha256:...", challenge_id=self.challenge.id)
        other_comp.set_demographics("OtherName", "OtherSurname", "12", "OtherSchool", "OtherCity")
        db.session.add(other_comp)
        db.session.commit()

        # Query leaderboard again
        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        leaderboard = res.get_json()["leaderboard"]
        other_item = next(item for item in leaderboard if item["user"]["id"] == other_comp.id)
        # Should not contain name, email, school, city etc.
        self.assertNotIn("name", other_item["user"])
        self.assertNotIn("email", other_item["user"])
        self.assertEqual(other_item["user"]["alias_id"], "Other-Pseudonym")

        # B. Jury querying the leaderboard (during active competition, not finalized)
        # They should not see details of any competitor, only alias_id
        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(jury_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        for item in leaderboard:
            self.assertNotIn("name", item["user"])
            self.assertNotIn("email", item["user"])
            self.assertIsNotNone(item["user"]["alias_id"])

        # C. Jury querying users list via admin blueprint
        # During active competition, they should only see pseudonyms for competitors
        res = self.client.get('/api/admin/users', headers=self.get_auth_header(jury_token))
        self.assertEqual(res.status_code, 200)
        users = res.get_json()["items"]
        competitor_users = [u for u in users if u["role"] == "competitor"]
        for u in competitor_users:
            self.assertNotIn("name", u)
            self.assertNotIn("email", u)
            self.assertIsNotNone(u["alias_id"])

    def test_challenge_leaderboard_freeze_time(self):
        """Competitors querying the challenge-level leaderboard when frozen should get the current leaderboard state, and submitting new solutions should be blocked."""
        self.challenge.is_frozen = True
        self.challenge.scores_finalized = False
        db.session.commit()

        # Try submitting when frozen
        res_submit = self.client.post(
            f'/api/challenges/{self.challenge.id}/submit',
            json={"task_id": self.task.id, "selected_cells": []},
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res_submit.status_code, 403)
        self.assertIn("frozen", res_submit.get_json()["error"])

        # Competitor queries challenge leaderboard
        res = self.client.get(f'/api/challenges/{self.challenge.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)

    @patch('tasks.celery.control.inspect')
    def test_worker_status_endpoint(self, mock_inspect_cls):
        """Worker status endpoint should return online when workers reply, and offline when they do not."""
        mock_inspect = mock_inspect_cls.return_value
        
        # Case 1: Active workers online
        mock_inspect.ping.return_value = {"celery@gpu-worker": {"ok": "pong"}}
        res = self.client.get('/api/worker-status', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "online")
        
        # Case 2: No workers online (ping returns None)
        mock_inspect.ping.return_value = None
        res = self.client.get('/api/worker-status', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "offline")

    @patch('tasks.celery.control.inspect')
    def test_detailed_worker_stats_endpoint(self, mock_inspect_cls):
        """Admin worker stats endpoint should return concurrency and status statistics when online."""
        mock_inspect = mock_inspect_cls.return_value
        
        # Mock responses
        mock_inspect.ping.return_value = {"celery@gpu-worker-0": {"ok": "pong"}}
        mock_inspect.stats.return_value = {
            "celery@gpu-worker-0": {
                "pid": 12345,
                "uptime": 3600,
                "pool": {"max-concurrency": 4},
                "total": {"evaluate_submission": 12},
                "broker": {"transport": "redis", "hostname": "localhost", "port": 6379}
            }
        }
        mock_inspect.active.return_value = {"celery@gpu-worker-0": [{"id": "task-uuid-1", "name": "tasks.evaluate_submission"}]}
        mock_inspect.reserved.return_value = {"celery@gpu-worker-0": []}
        mock_inspect.registered.return_value = {"celery@gpu-worker-0": ["tasks.evaluate_submission"]}
        
        # Competitor role should be rejected (403)
        res = self.client.get('/api/admin/workers/stats', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 403)
        
        # Admin role should succeed (200)
        res = self.client.get('/api/admin/workers/stats', headers=self.get_auth_header(self.admin_token))
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["connected_workers_count"], 1)
        self.assertEqual(data["workers"][0]["name"], "celery@gpu-worker-0")
        self.assertEqual(data["workers"][0]["pool_size"], 4)
        self.assertEqual(data["workers"][0]["active_tasks_count"], 1)

    def test_leaderboard_late_processed_submission_override(self):
        """If competition has ended and the user had late-processed submissions (completed after end_time), the leaderboard should auto-select the best submission instead of honoring manual selections."""
        # Set competition end time in the past
        self.challenge.end_time = datetime.utcnow() - timedelta(minutes=15)
        self.challenge.scores_finalized = False
        db.session.commit()

        # Delete other competitor submissions to make assertions clean
        Submission.query.filter_by(user_id=self.competitor.id).delete()
        db.session.commit()

        # Submission 1 (selected as final, score 0.75, processed before end_time)
        s_final = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                             status="completed", public_score=0.75, is_final_selection=True,
                             created_at=self.challenge.end_time - timedelta(minutes=10),
                             executed_at=self.challenge.end_time - timedelta(minutes=9),
                             code_cells="[]")
        
        # Submission 2 (not selected as final, score 0.95, processed LATE after end_time)
        s_late = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                            status="completed", public_score=0.95, is_final_selection=False,
                            created_at=self.challenge.end_time - timedelta(minutes=2),
                            executed_at=self.challenge.end_time + timedelta(minutes=5), # completed late!
                            code_cells="[]")
        db.session.add_all([s_final, s_late])
        db.session.commit()

        # Query task leaderboard
        res = self.client.get(f'/api/tasks/{self.task.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        comp_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        # Should override the manual final selection (0.75) and return the best overall score (0.95)
        self.assertEqual(comp_item["public_score"], 0.95)

    def test_task_creation_parameter_validation(self):
        """Test that task creation rejects invalid RAM, base image, apt packages, and pip requirements."""
        admin_header = self.get_auth_header(self.admin_token)
        import io
        
        # 0. Missing baseline notebook
        data = {
            "title": "Missing Baseline Task",
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Baseline notebook is required", res.get_json()["error"])
        
        # 1. Invalid RAM (exceeds 16GB)
        data = {
            "title": "Invalid RAM Task",
            "ram_limit_mb": 20000,
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("cannot exceed 16384 MB", res.get_json()["error"])
        
        # 2. Invalid base docker image name
        data = {
            "title": "Invalid Image Task",
            "base_docker_image": "python:3.10-slim; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid base Docker image", res.get_json()["error"])
        
        # 3. Invalid APT package names
        data = {
            "title": "Invalid APT Task",
            "apt_packages": "curl, htop; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid APT package name", res.get_json()["error"])
        
        # 4. Invalid pip requirements line
        data = {
            "title": "Invalid Pip Task",
            "pip_requirements": "numpy>=1.20.0\nrequests; rm -rf /",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid pip requirement line", res.get_json()["error"])

    def test_jury_custom_environment_restrictions(self):
        """Jury users should not be allowed to configure base_docker_image, apt_packages, or pip_requirements during task creation or update."""
        jury_user = User(
            username="test_jury_env",
            password_hash="pbkdf2:sha256:...",
            role="jury"
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)
        jury_header = self.get_auth_header(jury_token)
        
        # 1. Jury attempts to create a task with base_docker_image
        import io
        data = {
            "title": "Jury Custom Env Task",
            "base_docker_image": "python:3.10-slim",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=jury_header)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Only administrators are allowed", res.get_json()["error"])
        
        # 2. Jury attempts to update a task and set base_docker_image
        task = Task(
            challenge_id=self.challenge.id,
            title="Clean Task",
            description="No custom env",
            ram_limit_mb=1024,
            time_limit_sec=60
        )
        db.session.add(task)
        db.session.commit()
        
        data = {
            "base_docker_image": "python:3.10-slim"
        }
        res = self.client.put(f'/api/tasks/{task.id}', data=data, headers=jury_header)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Only administrators are allowed", res.get_json()["error"])
        
        # 3. Admin updates the task successfully with custom env
        admin_header = self.get_auth_header(self.admin_token)
        res = self.client.put(f'/api/tasks/{task.id}', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 200)

    @patch('cache_utils.delete_cached')
    @patch('cache_utils.set_cached')
    @patch('cache_utils.get_cached')
    def test_cache_invalidation_workflows(self, mock_get, mock_set, mock_delete):
        """Test cache setting on GET challenge and cache invalidation on task mutations/leaderboard resets."""
        mock_get.return_value = None
        
        # 1. Fetch challenge details: check if set_cached is called
        competitor_header = self.get_auth_header(self.competitor_token)
        res = self.client.get(f'/api/challenges/{self.challenge.id}', headers=competitor_header)
        self.assertEqual(res.status_code, 200)
        
        # Verify set_cached is called for challenge:<id>:competitor
        mock_set.assert_any_call(f"challenge:{self.challenge.id}:competitor", res.get_json(), timeout=600)
        
        # 2. Invalidate leaderboard cache verification
        from cache_utils import invalidate_leaderboard_cache
        invalidate_leaderboard_cache(self.challenge.id)
        mock_delete.assert_any_call(f"leaderboard:raw:{self.challenge.id}:frozen")
        mock_delete.assert_any_call(f"leaderboard:raw:{self.challenge.id}:unfrozen")
        
        # Reset mock call history for deletion
        mock_delete.reset_mock()
        
        # 3. Create a task and verify challenge cache invalidation
        admin_header = self.get_auth_header(self.admin_token)
        import io
        data = {
            "title": "New Test Task",
            "baseline_notebook": (io.BytesIO(b'{"cells": []}'), 'baseline.ipynb'),
            "solution_notebook": (io.BytesIO(b'{"cells": []}'), 'solution.ipynb'),
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/tasks', data=data, headers=admin_header)
        self.assertEqual(res.status_code, 201)
        # Verify that create_task invalidates the challenge cache
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")
        
        # Reset mock
        mock_delete.reset_mock()
        new_task_id = res.get_json()["id"]
        
        # 4. Update the task and verify challenge cache invalidation
        update_data = {
            "title": "Updated Test Task Title"
        }
        res = self.client.put(f'/api/tasks/{new_task_id}', data=update_data, headers=admin_header)
        self.assertEqual(res.status_code, 200)
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")
        
        # Reset mock
        mock_delete.reset_mock()
        
        # 5. Delete the task and verify challenge cache invalidation
        res = self.client.delete(f'/api/tasks/{new_task_id}', headers=admin_header)
        self.assertEqual(res.status_code, 200)
        mock_delete.assert_any_call("challenges:all")
        mock_delete.assert_any_call(f"challenge:{self.challenge.id}")

    @patch('tasks.evaluate_submission.delay')
    def test_challenge_submission_route_and_ast_rule_engine(self, mock_celery):
        """Test submission route task_id checking and AST pre-execution rule validations."""
        comp_header = self.get_auth_header(self.competitor_token)
        
        # 1. Missing task_id
        payload = {
            "selected_cells": ["print('hello')"]
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("task_id is required", res.get_json()["error"])
        
        # 2. Invalid task_id (mismatched challenge)
        payload = {
            "selected_cells": ["print('hello')"],
            "task_id": 99999
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid task_id", res.get_json()["error"])
        
        # 3. AST Banned Imports check (should fail with 400)
        self.task.banned_imports = "os,sys,subprocess"
        db.session.commit()
        
        payload = {
            "selected_cells": ["import os\nprint('hack')"],
            "task_id": self.task.id
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Import of library 'os' is banned", res.get_json()["error"])
        
        # 4. AST Banned Magic Commands check
        self.task.ban_magic_commands = True
        self.task.banned_imports = ""
        db.session.commit()
        
        payload = {
            "selected_cells": ["!pip install requests"],
            "task_id": self.task.id
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("magic commands", res.get_json()["error"])
        
        # 5. AST Required Tag check
        self.task.ban_magic_commands = False
        self.task.require_submit_tag = True
        db.session.commit()
        
        payload = {
            "selected_cells": ["print('hello')"],
            "task_id": self.task.id
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 400)
        self.assertIn("missing the required '# SUBMIT' tag", res.get_json()["error"])
        
        # 6. Valid submission
        payload = {
            "selected_cells": ["# SUBMIT\nprint('hello')"],
            "task_id": self.task.id
        }
        res = self.client.post(f'/api/challenges/{self.challenge.id}/submit', json=payload, headers=comp_header)
        self.assertEqual(res.status_code, 202)
        
        sub_id = res.get_json()["submission_id"]
        submission = db.session.get(Submission, sub_id)
        self.assertIsNotNone(submission)
        self.assertEqual(submission.task_id, self.task.id)
        self.assertEqual(submission.challenge_id, self.challenge.id)

    def test_docs_secure_access(self):
        comp_header = self.get_auth_header(self.competitor_token)
        jury_token = generate_token(999, "jury")
        jury_header = self.get_auth_header(jury_token)
        admin_header = self.get_auth_header(self.admin_token)
        
        # 1. Student doc access (all roles)
        res = self.client.get('/api/docs/student', headers=comp_header)
        self.assertEqual(res.status_code, 200)
        res = self.client.get('/api/docs/student', headers=jury_header)
        self.assertEqual(res.status_code, 200)
        res = self.client.get('/api/docs/student', headers=admin_header)
        self.assertEqual(res.status_code, 200)
        
        # 2. Jury doc access (Jury & Admin)
        res = self.client.get('/api/docs/jury', headers=comp_header)
        self.assertEqual(res.status_code, 403)
        res = self.client.get('/api/docs/jury', headers=jury_header)
        self.assertEqual(res.status_code, 200)
        res = self.client.get('/api/docs/jury', headers=admin_header)
        self.assertEqual(res.status_code, 200)
        
        # 3. Admin doc access (Admin only)
        res = self.client.get('/api/docs/admin', headers=comp_header)
        self.assertEqual(res.status_code, 403)
        res = self.client.get('/api/docs/admin', headers=jury_header)
        self.assertEqual(res.status_code, 403)
        res = self.client.get('/api/docs/admin', headers=admin_header)
        self.assertEqual(res.status_code, 200)
        
        # 4. API reference removed (replaced by /apidocs Swagger UI)
        res = self.client.get('/api/docs/api-reference', headers=admin_header)
        self.assertEqual(res.status_code, 404)
        
    def test_bulgarian_name_transliteration(self):
        """Registering a competitor with Bulgarian/Cyrillic names should transliterate them properly to standard Latin before username base is calculated."""
        payload = {
            "name": "Иван",
            "surname": "Петров",
            "grade": "10",
            "school": "Sofia High",
            "city": "Sofia",
            "challenge_id": self.challenge.id
        }
        res = self.client.post(
            '/api/admin/register-competitor',
            headers=self.get_auth_header(self.admin_token),
            json=payload
        )
        self.assertEqual(res.status_code, 201)
        data = json.loads(res.data)
        username = data["generated_username"]
        self.assertTrue(username.startswith("comp_iva_pet_"))

    def test_csv_import_anonymity_support(self):
        """Importing a CSV of competitors with anonymity settings (0/1 or true/false) should respect and persist it."""
        csv_data = (
            "name,surname,grade,school,city,is_anonymous\n"
            "Ivan,Petrov,10,Sofia High,Sofia,1\n"
            "Maria,Georgieva,11,Plovdiv High,Plovdiv,0\n"
        )
        import io
        res = self.client.post(
            f'/api/admin/import-competitors-csv?challenge_id={self.challenge.id}',
            headers=self.get_auth_header(self.admin_token),
            data={
                'file': (io.BytesIO(csv_data.encode('utf-8')), 'competitors.csv')
            }
        )
        self.assertEqual(res.status_code, 201)
        data = json.loads(res.data)
        self.assertEqual(len(data["competitors"]), 2)
        
        # Check that database matches the anonymity flag
        ivan = User.query.filter_by(username=data["competitors"][0]["generated_username"]).first()
        self.assertIsNotNone(ivan)
        self.assertTrue(ivan.is_anonymous)
        
        maria = User.query.filter_by(username=data["competitors"][1]["generated_username"]).first()
        self.assertIsNotNone(maria)
        self.assertFalse(maria.is_anonymous)

    def test_reset_user_password_routes(self):
        """Test individual password reset endpoint controls."""
        jury_user = User(
            username="test_jury_pwd",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Oracle-pwd"
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        # 1. Admin can reset password anytime
        res = self.client.post(
            f'/api/admin/users/{self.competitor.id}/reset-password',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn("password", data)

        # 2. Jury can reset password before challenge starts
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f'/api/admin/users/{self.competitor.id}/reset-password',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)

        # 3. Jury cannot reset password after challenge starts
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f'/api/admin/users/{self.competitor.id}/reset-password',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 403)

    def test_reset_all_challenge_passwords_routes(self):
        """Test bulk password reset endpoint controls."""
        jury_user = User(
            username="test_jury_pwd2",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Oracle-pwd2"
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        # 1. Admin can bulk reset anytime
        res = self.client.post(
            f'/api/admin/challenges/{self.challenge.id}/reset-all-passwords',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn("reset_accounts", data)
        self.assertTrue(len(data["reset_accounts"]) > 0)

        # 2. Jury can bulk reset before challenge starts
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f'/api/admin/challenges/{self.challenge.id}/reset-all-passwords',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)

        # 3. Jury cannot bulk reset after challenge starts
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        res = self.client.post(
            f'/api/admin/challenges/{self.challenge.id}/reset-all-passwords',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 403)

    def test_search_competitors_privacy_constraints(self):
        """Test search privacy constraints for jury vs admin, before and after competition starts."""
        # Create a jury user and token
        jury_user = User(
            username="test_jury_search",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Search-001"
        )
        db.session.add(jury_user)
        db.session.commit()
        jury_token = generate_token(jury_user.id, jury_user.role)

        # 1. Before challenge starts:
        # Challenge start_time set to future
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

        # Jury search by school "Sofia"
        res = self.client.get(
            '/api/admin/users?role=competitor&search=Sofia',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(any(u["id"] == self.competitor.id for u in data["items"]))

        # Jury search by username "test_comp"
        res = self.client.get(
            '/api/admin/users?role=competitor&search=test_comp',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(any(u["id"] == self.competitor.id for u in data["items"]))

        # Jury search by alias "Stellar"
        res = self.client.get(
            '/api/admin/users?role=competitor&search=Stellar',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(any(u["id"] == self.competitor.id for u in data["items"]))

        # 2. After challenge starts:
        # Challenge start_time set to past
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=2)
        db.session.commit()

        # Jury search by school "Sofia" - should not match the competitor
        res = self.client.get(
            '/api/admin/users?role=competitor&search=Sofia',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertFalse(any(u["id"] == self.competitor.id for u in data["items"]))

        # Jury search by username "test_comp" - should not match
        res = self.client.get(
            '/api/admin/users?role=competitor&search=test_comp',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertFalse(any(u["id"] == self.competitor.id for u in data["items"]))

        # Jury search by alias "Stellar" - SHOULD STILL MATCH (alias search supported everywhere)
        res = self.client.get(
            '/api/admin/users?role=competitor&search=Stellar',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(any(u["id"] == self.competitor.id for u in data["items"]))

        # 3. Admin search after challenge starts:
        # Admin search by school "Sofia" - should match (admin is allowed to search by this)
        res = self.client.get(
            '/api/admin/users?role=competitor&search=Sofia',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(any(u["id"] == self.competitor.id for u in data["items"]))

    def test_competitor_anonymity_privacy_constraints(self):
        """Test anonymity constraints for students requesting anonymity on the leaderboard."""
        from cache_utils import invalidate_leaderboard_cache
        invalidate_leaderboard_cache(self.challenge.id)

        # Create an anonymous competitor
        anon_comp = User(
            username="anon_student",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Ghost-Rider-777",
            challenge_id=self.challenge.id,
            is_anonymous=True
        )
        anon_comp.set_demographics("John", "Doe", "11", "Varna High", "Varna")
        db.session.add(anon_comp)
        db.session.commit()

        # Let's request the leaderboard as the other competitor (self.competitor)
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        leaderboard = data["leaderboard"]
        
        # Find the entry for anon_comp
        anon_entry = next(e for e in leaderboard if e["user"]["id"] == anon_comp.id)
        # Should not reveal demographics because anon_comp has is_anonymous=True
        self.assertNotIn("name", anon_entry["user"])
        self.assertNotIn("school", anon_entry["user"])
        self.assertNotIn("city", anon_entry["user"])

        # Request leaderboard as admin
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        leaderboard = data["leaderboard"]
        
        anon_entry_admin = next(e for e in leaderboard if e["user"]["id"] == anon_comp.id)
        # Admin should see everything
        self.assertEqual(anon_entry_admin["user"]["name"], "John")
        self.assertEqual(anon_entry_admin["user"]["school"], "Varna High")
        self.assertEqual(anon_entry_admin["user"]["city"], "Varna")

    def test_manual_points_entry_and_leaderboard_ranking(self):
        """Test manual points entry and that finalized leaderboard is sorted by manual points."""
        # Seed a completed submission for self.competitor so they can receive manual points
        s_comp = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                            status='completed', public_score=0.8, private_score=0.85)
        db.session.add(s_comp)
        db.session.commit()

        # 1. Finalize the challenge first
        self.challenge.scores_finalized = True
        db.session.commit()

        # Invalidate cache
        from cache_utils import invalidate_leaderboard_cache
        invalidate_leaderboard_cache(self.challenge.id)

        # 2. Enter manual points as admin for self.competitor (reason required since finalized)
        payload = {
            "user_id": self.competitor.id,
            "points": {
                str(self.task.id): 85
            },
            "reason": "Correcting grade error after finalization"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["manual_points"][str(self.task.id)], 85)

        # 3. Enter manual points as admin for another competitor
        comp2 = User(
            username="competitor_two",
            email="comp2@example.com",
            role="competitor",
            password_hash="pbkdf2:sha256:placeholder",
            challenge_id=self.challenge.id
        )
        comp2.set_demographics("Mary", "Jane", "11", "Sofia High", "Sofia")
        db.session.add(comp2)
        db.session.commit()

        # Seed completed submission for comp2 so they can receive manual points
        s_comp2 = Submission(user_id=comp2.id, challenge_id=self.challenge.id, task_id=self.task.id,
                             status='completed', public_score=0.8, private_score=0.85)
        db.session.add(s_comp2)
        db.session.commit()

        # Award 95 points to comp2
        payload2 = {
            "user_id": comp2.id,
            "points": {
                str(self.task.id): 95
            },
            "reason": "Correcting grade error after finalization"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            data=json.dumps(payload2),
            content_type='application/json',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)

        # 4. Fetch finalized leaderboard and assert sorting: comp2 should be rank 1 (95 pts)
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}/leaderboard',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        leaderboard = data["leaderboard"]
        
        self.assertEqual(leaderboard[0]["user"]["id"], comp2.id)
        self.assertEqual(leaderboard[0]["total_points"], 95)
        self.assertEqual(leaderboard[0]["rank"], 1)

        self.assertEqual(leaderboard[1]["user"]["id"], self.competitor.id)
        self.assertEqual(leaderboard[1]["total_points"], 85)
        self.assertEqual(leaderboard[1]["rank"], 2)

    def test_submission_blocked_when_competition_finalized(self):
        # 1. Finalize the challenge scores
        self.challenge.scores_finalized = True
        db.session.commit()

        # 2. Competitor tries to submit code: should return 403 Forbidden
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/submit',
            data=json.dumps({
                "task_id": self.task.id,
                "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}]
            }),
            content_type='application/json',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Submissions are disabled for finalized competitions", res.get_json()["error"])

        # 3. Unfinalize the challenge
        self.challenge.scores_finalized = False
        db.session.commit()

    def test_finalize_constraints_and_permissions(self):
        # 1. Reset challenge finalized status
        self.challenge.scores_finalized = False
        db.session.commit()

        # Generate a jury token (jury is allowed to finalize, but admin is not)
        jury = User(
            username="jury_member_test",
            email="jury_test@example.com",
            role="jury",
            password_hash="pbkdf2:sha256:placeholder"
        )
        db.session.add(jury)
        db.session.commit()
        from routes.auth import generate_token
        jury_token = generate_token(jury.id, "jury")

        # 2. Try to finalize as admin (should return 403)
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/finalize',
            data=json.dumps({
                "reveal_public_scores": True,
                "reveal_private_scores": True,
                "reveal_points": True
            }),
            content_type='application/json',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 403)

        # 3. Try to finalize as jury, but self.competitor has no points entered yet (should return 400)
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/finalize',
            data=json.dumps({
                "reveal_public_scores": True,
                "reveal_private_scores": True,
                "reveal_points": True
            }),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("missing manual points", res.get_json()["error"])

        # 4. Enter points for competitor
        self.competitor.manual_points = {str(self.task.id): 90}
        db.session.commit()

        # 5. Finalize as jury (should succeed and return 200)
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/finalize',
            data=json.dumps({
                "reveal_public_scores": True,
                "reveal_private_scores": True,
                "reveal_points": True
            }),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(self.challenge.scores_finalized)

    def test_stages_crud_finalization_and_submission_boundaries(self):
        # 1. Create a Jury User to get a jury token
        jury = User(
            username="jury_member_stage_test",
            email="jury_stage_test@example.com",
            role="jury",
            password_hash="pbkdf2:sha256:placeholder"
        )
        db.session.add(jury)
        db.session.commit()
        from routes.auth import generate_token
        jury_token = generate_token(jury.id, "jury")

        # 2. Stage CRUD Operations (POST, PUT, DELETE)
        # Create a Stage
        payload = {
            "title": "Stage 1",
            "stage_number": 1,
            "start_time": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=1)).isoformat()
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/stages',
            data=json.dumps(payload),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 201)
        stage_data = res.get_json()
        stage_id = stage_data["id"]
        self.assertEqual(stage_data["title"], "Stage 1")

        # Update a Stage
        payload_update = {
            "title": "Stage 1 Updated"
        }
        res = self.client.put(
            f'/api/challenges/{self.challenge.id}/stages/{stage_id}',
            data=json.dumps(payload_update),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        stage_data = res.get_json()
        self.assertEqual(stage_data["title"], "Stage 1 Updated")

        # 3. Create a task in an unstarted stage and check visibility constraints
        # Create a future stage
        future_payload = {
            "title": "Future Stage",
            "stage_number": 2,
            "start_time": (datetime.utcnow() + timedelta(hours=10)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(hours=11)).isoformat()
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/stages',
            data=json.dumps(future_payload),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 201)
        future_stage_id = res.get_json()["id"]

        # Bind self.task to the future stage
        self.task.stage_id = future_stage_id
        db.session.commit()

        # competitor fetches challenge metadata: task should NOT be visible
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["tasks"]), 0)

        # competitor fetches task details directly: should be excluded / not found
        res = self.client.get(
            f'/api/tasks/{self.task.id}',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertIn(res.status_code, [403, 404])

        # competitor tries to submit code to this unstarted stage task: should return 400
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/submit',
            data=json.dumps({
                "task_id": self.task.id,
                "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}]
            }),
            content_type='application/json',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("has not started yet", res.get_json()["error"])

        # 4. Check stage deadline expired submissions block
        # Move stage timeline into the past
        from models import Stage
        stage2 = db.session.get(Stage, future_stage_id)
        stage2.start_time = datetime.utcnow() - timedelta(hours=2)
        stage2.end_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
        from cache_utils import invalidate_challenge_cache
        invalidate_challenge_cache(self.challenge.id)

        # competitor fetches challenge metadata: task is now visible (since it has started)
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()["tasks"]), 1)

        # competitor tries to submit code after the deadline: should return 400
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/submit',
            data=json.dumps({
                "task_id": self.task.id,
                "selected_cells": [{"id": 1, "type": "code", "source": "print(1)"}]
            }),
            content_type='application/json',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("has passed", res.get_json()["error"])

        # 5. Test Stage Finalization constraints
        # Try to finalize Stage 2 as jury: competitor has no manual points for self.task (should fail with 400)
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize',
            data=json.dumps({"finalize_type": "visible"}),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("missing manual points", res.get_json()["error"])

        # Set manual points for the competitor on this task
        self.competitor.manual_points = {str(self.task.id): 85}
        db.session.commit()

        # Finalizing Stage 2 as jury should now succeed
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/stages/{future_stage_id}/finalize',
            data=json.dumps({"finalize_type": "visible", "reveal_public": True}),
            content_type='application/json',
            headers=self.get_auth_header(jury_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["is_finalized"])

        # 6. Test login block for archived challenges
        self.challenge.is_archived = True
        db.session.commit()

        # competitor logins: should return 403 Forbidden
        from werkzeug.security import generate_password_hash
        self.competitor.password_hash = generate_password_hash("my-competitor-password", method="pbkdf2:sha256")
        db.session.commit()
        
        login_res = self.client.post(
            '/api/auth/login',
            data=json.dumps({
                "username": self.competitor.username,
                "password": "my-competitor-password"
            }),
            content_type='application/json'
        )
        self.assertEqual(login_res.status_code, 403)
        self.assertIn("archived", login_res.get_json()["error"])

        # Unarchive challenge
        self.challenge.is_archived = False
        db.session.commit()

        # 7. Test cascading student deletion
        # Verify competitor exists first
        comp_in_db = User.query.filter_by(challenge_id=self.challenge.id, role="competitor").first()
        self.assertIsNotNone(comp_in_db)

        # Delete challenge via admin endpoint
        res = self.client.delete(
            f'/api/challenges/{self.challenge.id}',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)

        # Verify competitor is deleted
        comp_in_db = User.query.filter_by(challenge_id=self.challenge.id, role="competitor").first()
        self.assertIsNone(comp_in_db)

    def test_test_competition_creation_and_unstarted_limits(self):
        # 1. Test unstarted competition limits
        self.challenge.start_time = datetime.utcnow() + timedelta(hours=2)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=4)
        db.session.commit()
        from cache_utils import invalidate_challenge_cache
        invalidate_challenge_cache(self.challenge.id)

        # Competitor fetches challenge metadata: tasks and stages must be empty lists, but num_tasks visible
        res = self.client.get(
            f'/api/challenges/{self.challenge.id}',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["tasks"]), 0)
        self.assertEqual(len(data["stages"]), 0)
        self.assertEqual(data["num_tasks"], 1)

        # Competitor fetches task details directly: should be blocked with 403
        res = self.client.get(
            f'/api/tasks/{self.task.id}',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 403)

        # 2. Test scheduled test competition creation
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/test-competition',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("Test: ", data["test_competition"]["title"])
        self.assertEqual(data["test_competition"]["max_eval_requests"], 100)
        self.assertEqual(data["test_competition"]["double_blind"], False)
        self.assertEqual(len(data["test_competition"]["tasks"]), 1)
        self.assertEqual(data["test_competition"]["tasks"][0]["title"], "Warm-up Test Task")

        # Cleanup start/end times
        self.challenge.start_time = datetime.utcnow() - timedelta(hours=2)
        self.challenge.end_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

    def test_archived_challenges_visibility(self):
        """Competitors should not see archived challenges in list or detail routes."""
        self.challenge.is_archived = True
        db.session.commit()
        from cache_utils import invalidate_challenge_cache
        invalidate_challenge_cache(self.challenge.id)

        # 1. Competitor tries to list challenges
        res_list = self.client.get('/api/challenges', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.get_json()), 0)

        # 2. Competitor tries to fetch challenge details
        res_detail = self.client.get(f'/api/challenges/{self.challenge.id}', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res_detail.status_code, 404)

        # 3. Admin should still see the archived challenge
        res_admin = self.client.get(f'/api/challenges/{self.challenge.id}', headers=self.get_auth_header(self.admin_token))
        self.assertEqual(res_admin.status_code, 200)
        self.assertEqual(res_admin.get_json()["is_archived"], True)

        # Restore
        self.challenge.is_archived = False
        db.session.commit()
        invalidate_challenge_cache(self.challenge.id)

    def test_manual_points_audit_and_constraints(self):
        """Test that updating manual points requires reason if finalized and creates audit log."""
        # Seed completed submission
        s_comp = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                            status='completed', public_score=0.8, private_score=0.85)
        db.session.add(s_comp)
        db.session.commit()

        # Finalize challenge
        self.challenge.scores_finalized = True
        db.session.commit()

        # 1. Update points without a reason: should return 400
        payload_no_reason = {
            "user_id": self.competitor.id,
            "points": {
                str(self.task.id): 50
            }
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            data=json.dumps(payload_no_reason),
            content_type='application/json',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("justification reason is mandatory", res.get_json()["error"])

        # 2. Update points with reason: should succeed and create AuditLog
        payload_with_reason = {
            "user_id": self.competitor.id,
            "points": {
                str(self.task.id): 60
            },
            "reason": "Scoring correction post finalization"
        }
        res = self.client.post(
            f'/api/challenges/{self.challenge.id}/manual-points',
            data=json.dumps(payload_with_reason),
            content_type='application/json',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res.status_code, 200)

        # Query AuditLog to verify it exists
        from models import AuditLog
        logs = AuditLog.query.filter_by(target_user_id=self.competitor.id).all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].new_score, 60)
        self.assertEqual(logs[0].reason, "Scoring correction post finalization")

    def test_results_export(self):
        """Test final results export CSV endpoint and role-based permissions."""
        # 1. Competitor tries to export: should be blocked
        res_comp = self.client.get(
            f'/api/challenges/{self.challenge.id}/export-results',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res_comp.status_code, 403)

        # 2. Admin exports successfully
        res_admin = self.client.get(
            f'/api/challenges/{self.challenge.id}/export-results',
            headers=self.get_auth_header(self.admin_token)
        )
        self.assertEqual(res_admin.status_code, 200)
        self.assertEqual(res_admin.mimetype, "text/csv")
        csv_data = res_admin.data.decode('utf-8')
        self.assertIn("Rank,Username,Alias ID", csv_data)
        self.assertIn("--- SCORE CORRECTION AUDIT LOG ---", csv_data)

    def test_stream_submission_logs(self):
        """Test streaming submission logs SSE endpoint."""
        sub = Submission(
            user_id=self.competitor.id,
            challenge_id=self.challenge.id,
            task_id=self.task.id,
            status='queued',
            detailed_status='queued',
            code_cells="[]"
        )
        db.session.add(sub)
        db.session.commit()
        
        # Competitor gets their own submission logs stream
        res = self.client.get(
            f'/api/submissions/{sub.id}/logs/live',
            headers=self.get_auth_header(self.competitor_token)
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/event-stream')

if __name__ == '__main__':
    unittest.main()


