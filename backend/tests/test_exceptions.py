import os
import sys
import json
import unittest
from io import BytesIO
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Force in-memory SQLite for testing
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, User, Challenge, Task, Submission
from auth_utils import generate_token

class TestBackendExceptionAndErrorCases(unittest.TestCase):
    def setUp(self):
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
        # Admin User
        self.admin = User(
            username="admin_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="admin",
            alias_id="Admin-999"
        )
        # Competitor challenge A
        self.challenge_a = Challenge(
            title="Challenge Alpha",
            description="Competitor challenge A",
            max_eval_requests=3,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            metric_name="accuracy"
        )
        # Competitor challenge B (unregistered for self.competitor)
        self.challenge_b = Challenge(
            title="Challenge Beta",
            description="Competitor challenge B",
            max_eval_requests=5,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            metric_name="accuracy"
        )
        db.session.add(self.admin)
        db.session.add(self.challenge_a)
        db.session.add(self.challenge_b)
        db.session.commit()

        # Competitor registered for Challenge A
        self.competitor = User(
            username="competitor_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="competitor",
            alias_id="Competitor-101",
            challenge_id=self.challenge_a.id
        )
        # Competitor unregistered/registered for nothing
        self.unregistered_competitor = User(
            username="unregistered_user",
            password_hash="pbkdf2:sha256:260000$mockpbkdf2hash",
            role="competitor",
            alias_id="Competitor-102",
            challenge_id=None
        )
        db.session.add(self.competitor)
        db.session.add(self.unregistered_competitor)
        db.session.commit()

    # --- AUTHENTICATION ENDPOINT EXCEPTIONS ---

    def test_login_missing_parameters(self):
        # Empty body
        res = self.client.post('/api/auth/login', json={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Missing username/email or password", res.json["error"])

        # Missing password
        res = self.client.post('/api/auth/login', json={"username": "admin_user"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Missing username/email or password", res.json["error"])

    def test_login_invalid_credentials(self):
        # Non-existent user
        res = self.client.post('/api/auth/login', json={"username": "ghost", "password": "pwd"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid credentials", res.json["error"])

        # Incorrect password
        res = self.client.post('/api/auth/login', json={"username": "admin_user", "password": "wrong_password"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid credentials", res.json["error"])

    def test_me_unauthorized_missing_token(self):
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 401)
        self.assertIn("Unauthorized access", res.json["error"])

    def test_me_unauthorized_invalid_token(self):
        headers = {"Authorization": "Bearer malformed.token.signature"}
        res = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Unauthorized access", res.json["error"])

    def test_me_user_not_found(self):
        # Valid signature, but user is deleted from database
        token = generate_token(99999, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(res.status_code, 404)
        self.assertIn("User not found", res.json["error"])


    # --- CHALLENGE ENDPOINT EXCEPTIONS ---

    def test_get_challenge_not_registered_competitor(self):
        # User registered to Challenge A trying to fetch details of Challenge B (unregistered)
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.get(f'/api/challenges/{self.challenge_b.id}', headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied. You are not registered for this competition", res.json["error"])

    def test_get_challenge_not_found(self):
        # Admin trying to fetch non-existent challenge ID
        token = generate_token(self.admin.id, "admin")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.get(f'/api/challenges/9999', headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_create_challenge_unauthorized_role(self):
        # Competitor role cannot create challenges
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post('/api/challenges', json={"title": "Unauthorized"}, headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Requires role: ['admin', 'jury']", res.json["error"])

    def test_create_challenge_missing_title(self):
        token = generate_token(self.admin.id, "admin")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post('/api/challenges', json={"description": "No Title"}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Competition title is required", res.json["error"])

    def test_update_challenge_not_found(self):
        token = generate_token(self.admin.id, "admin")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.put('/api/challenges/9999', json={"title": "Updated"}, headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_delete_challenge_not_found(self):
        token = generate_token(self.admin.id, "admin")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.delete('/api/challenges/9999', headers=headers)
        self.assertEqual(res.status_code, 404)


    # --- SUBMISSION ENDPOINT EXCEPTIONS ---

    def test_parse_notebook_denied_access_competitor(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post(f'/api/challenges/{self.challenge_b.id}/parse-notebook', headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json["error"])

    def test_parse_notebook_missing_file(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/parse-notebook', headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("No file uploaded", res.json["error"])

    def test_parse_notebook_invalid_extension(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        file_content = BytesIO(b"print('not a notebook')")
        data = {'file': (file_content, 'submission.py')}
        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/parse-notebook', data=data, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only Jupyter Notebook (.ipynb) files are supported", res.json["error"])

    def test_parse_notebook_malformed_json(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        file_content = BytesIO(b"this is not a valid JSON notebook")
        data = {'file': (file_content, 'submission.ipynb')}
        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/parse-notebook', data=data, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Failed to parse notebook", res.json["error"])

    def test_submit_code_denied_access_competitor(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.post(f'/api/challenges/{self.challenge_b.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json["error"])

    def test_submit_code_challenge_inactive_or_archived(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Inactive Challenge
        inactive_challenge = Challenge(title="Inactive", is_active=False, max_eval_requests=5)
        db.session.add(inactive_challenge)
        db.session.commit()

        # Re-fetch or link competitor to inactive challenge for 403 bypass
        self.competitor.challenge_id = inactive_challenge.id
        db.session.commit()

        res = self.client.post(f'/api/challenges/{inactive_challenge.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("This challenge is currently inactive", res.json["error"])

        # 2. Archived Challenge
        archived_challenge = Challenge(title="Archived", is_active=True, is_archived=True, max_eval_requests=5)
        db.session.add(archived_challenge)
        db.session.commit()

        self.competitor.challenge_id = archived_challenge.id
        db.session.commit()

        res = self.client.post(f'/api/challenges/{archived_challenge.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("This challenge has been archived", res.json["error"])

    def test_submit_code_timeline_violations(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}

        # Reset competitor back to Challenge A
        self.competitor.challenge_id = self.challenge_a.id
        db.session.commit()

        # 1. Not started
        self.challenge_a.start_time = datetime.utcnow() + timedelta(hours=1)
        self.challenge_a.end_time = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()

        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("This competition has not started yet", res.json["error"])

        # 2. Has ended
        self.challenge_a.start_time = datetime.utcnow() - timedelta(hours=2)
        self.challenge_a.end_time = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()

        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("This competition has ended", res.json["error"])

    @patch('tasks.evaluate_submission.delay')
    def test_submit_code_missing_cells_and_rate_limits(self, mock_celery):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}

        # Fix Challenge A timeline
        self.challenge_a.start_time = datetime.utcnow() - timedelta(hours=1)
        self.challenge_a.end_time = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()

        # 1. Missing selected cells
        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/submit', json={}, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("selected_cells list is required", res.json["error"])

        # 2. Rate limit check (max submissions is 3 for Challenge A)
        for i in range(3):
            sub = Submission(
                user_id=self.competitor.id,
                challenge_id=self.challenge_a.id,
                status='completed',
                code_cells="[]",
                created_at=datetime.utcnow()
            )
            db.session.add(sub)
        db.session.commit()

        res = self.client.post(f'/api/challenges/{self.challenge_a.id}/submit', json={"selected_cells": ["cell_content"]}, headers=headers)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Daily limit reached", res.json["error"])

    def test_select_final_submission_denied_competitor(self):
        # Competitor trying to set final submission they don't own
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}

        # Create submission belonging to admin user (id != competitor.id)
        sub = Submission(
            user_id=self.admin.id,
            challenge_id=self.challenge_a.id,
            status='completed',
            code_cells="[]"
        )
        db.session.add(sub)
        db.session.commit()

        res = self.client.post(f'/api/submissions/{sub.id}/select-final', headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied. You do not own this submission", res.json["error"])


    # --- LEADERBOARD ENDPOINT EXCEPTIONS ---

    def test_get_leaderboard_denied_access_competitor(self):
        token = generate_token(self.competitor.id, "competitor")
        headers = {"Authorization": f"Bearer {token}"}

        res = self.client.get(f'/api/challenges/{self.challenge_b.id}/leaderboard', headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json["error"])

    def test_get_leaderboard_not_found(self):
        token = generate_token(self.admin.id, "admin")
        headers = {"Authorization": f"Bearer {token}"}

        res = self.client.get('/api/challenges/9999/leaderboard', headers=headers)
        self.assertEqual(res.status_code, 404)

if __name__ == '__main__':
    unittest.main()
