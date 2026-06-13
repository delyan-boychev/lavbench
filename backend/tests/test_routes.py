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
from routes.tasks import calculate_submission_priority

class TestRouteLevelLogic(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
        self.app_context = self.app.app_context()
        self.app_context.push()
        
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
            freeze_time=datetime.utcnow() + timedelta(hours=1),
            metric_name="accuracy"
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
        self.challenge.metric_name = "mse"
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
        """Competitors querying the challenge-level leaderboard after freeze time must not see post-freeze scores."""
        # Create a submission after freeze time
        self.challenge.freeze_time = datetime.utcnow() - timedelta(minutes=10)
        self.challenge.scores_finalized = False
        db.session.commit()

        # Submission created before freeze time
        s_pre = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                           status="completed", public_score=0.8, created_at=datetime.utcnow() - timedelta(minutes=20),
                           code_cells="[]")
        # Submission created after freeze time
        s_post = Submission(user_id=self.competitor.id, challenge_id=self.challenge.id, task_id=self.task.id,
                            status="completed", public_score=0.95, created_at=datetime.utcnow() - timedelta(minutes=5),
                            code_cells="[]")
        db.session.add_all([s_pre, s_post])
        db.session.commit()

        # Competitor queries challenge leaderboard
        res = self.client.get(f'/api/challenges/{self.challenge.id}/leaderboard', headers=self.get_auth_header(self.competitor_token))
        self.assertEqual(res.status_code, 200)
        leaderboard = res.get_json()["leaderboard"]
        comp_item = next(item for item in leaderboard if item["user"]["id"] == self.competitor.id)
        # Should show the pre-freeze score (0.8) instead of post-freeze score (0.95)
        self.assertEqual(comp_item["public_score"], 0.8)

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
        
        # Verify set_cached is called for challenge:<id>
        mock_set.assert_any_call(f"challenge:{self.challenge.id}", res.get_json(), timeout=600)
        
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

if __name__ == '__main__':
    unittest.main()

