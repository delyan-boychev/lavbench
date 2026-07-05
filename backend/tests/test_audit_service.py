import uuid

import pytest

from utils.dates import utcnow


class TestAuditService:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, sample_admin, app):
        self.admin = sample_admin
        self.db = db_session
        self.app = app
        self.dummy_uuids = [str(uuid.uuid4()) for _ in range(10)]

    def _log(self, **kwargs):
        from services.audit_service import log_action

        with self.app.test_request_context():
            log_action(admin_id=self.admin.id, **kwargs)

    def _query(self, **kwargs):
        from models import AuditLog

        return AuditLog.query.filter_by(**kwargs)

    def test_log_action_creates_entry(self):
        tid = self.dummy_uuids[0]
        self._log(
            action_type="create",
            target_type="challenge",
            target_id=tid,
            details={"title": "New Challenge"},
        )
        entry = self._query(action_type="create").first()
        assert entry is not None
        assert str(entry.admin_id) == str(self.admin.id)
        assert entry.target_type == "challenge"
        assert entry.target_id == tid
        assert entry.details == {"title": "New Challenge"}
        assert entry.ip_address is not None

    def test_log_action_with_legacy_fields(self):
        tid = self.dummy_uuids[1]
        task_id = self.dummy_uuids[2]
        self._log(
            action_type="update",
            target_type="submission",
            target_id=tid,
            target_user_id=self.admin.id,
            task_id=task_id,
            old_score=0.5,
            new_score=0.9,
            reason="Recalculation",
        )
        entry = self._query(action_type="update").first()
        assert str(entry.target_user_id) == str(self.admin.id)
        assert entry.task_id == task_id
        assert entry.old_score == 0.5
        assert entry.new_score == 0.9
        assert entry.reason == "Recalculation"

    def test_log_action_multiple_entries(self):
        for i in range(3):
            self._log(
                action_type="delete",
                target_type="task",
                target_id=self.dummy_uuids[3 + i],
            )
        assert self._query(action_type="delete").count() == 3

    def test_log_action_handles_none_details(self):
        tid = self.dummy_uuids[6]
        self._log(action_type="create", target_type="user", target_id=tid, details=None)
        entry = self._query(action_type="create", target_id=tid).first()
        assert entry.details == {}

    def test_get_client_ip_returns_remote_addr(self, app):
        from services.audit_service import get_client_ip

        with app.test_request_context():
            assert get_client_ip() == "127.0.0.1"

    def test_get_client_ip_forwarded_for(self, app):
        from services.audit_service import get_client_ip

        with app.test_request_context(headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}):
            assert get_client_ip() == "10.0.0.1"

    def test_get_client_ip_forwarded_for_single(self, app):
        from services.audit_service import get_client_ip

        with app.test_request_context(headers={"X-Forwarded-For": "203.0.113.5"}):
            assert get_client_ip() == "203.0.113.5"

    def test_log_action_stores_ip(self):
        tid = self.dummy_uuids[7]
        self._log(action_type="update", target_type="user", target_id=tid)
        entry = self._query(action_type="update", target_id=tid).first()
        assert entry.ip_address == "127.0.0.1"

    def test_audit_log_timestamps(self):
        tid = self.dummy_uuids[8]
        self._log(action_type="create", target_type="stage", target_id=tid)
        entry = self._query(action_type="create", target_id=tid).first()
        assert entry.timestamp is not None


class TestAuditLogsRoute:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.app = app
        self.client = app.test_client()

        from auth_utils import generate_token
        from models import User

        # Create users
        self.admin = User(
            username="audit_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-Audit",
        )
        self.jury = User(
            username="audit_jury",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Audit",
        )
        self.competitor = User(
            username="audit_comp",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="Comp-Audit",
        )

        db_session.add_all([self.admin, self.jury, self.competitor])
        db_session.commit()

        self.admin_token = generate_token(self.admin.id, role="admin")
        self.jury_token = generate_token(self.jury.id, role="jury")
        self.comp_token = generate_token(self.competitor.id, role="competitor")

    def test_get_audit_logs_admin_allowed(self):
        # Create an audit log entry

        from models import AuditLog

        entry = AuditLog(
            admin_id=self.admin.id,
            action_type="create",
            target_type="challenge",
            timestamp=utcnow(),
        )
        from models import db

        db.session.add(entry)
        db.session.commit()

        # Call the endpoint
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        res = self.client.get("/api/admin/audit-logs", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert "logs" in data
        assert len(data["logs"]) >= 1
        assert data["logs"][0]["action_type"] == "create"

    def test_get_audit_logs_non_admin_forbidden(self):
        # Test jury forbidden
        headers = {"Authorization": f"Bearer {self.jury_token}"}
        res = self.client.get("/api/admin/audit-logs", headers=headers)
        assert res.status_code == 403

        # Test competitor forbidden
        headers = {"Authorization": f"Bearer {self.comp_token}"}
        res = self.client.get("/api/admin/audit-logs", headers=headers)
        assert res.status_code == 403

    def test_get_audit_logs_filter_by_challenge(self):
        # Create a challenge, tasks, stages, users
        from datetime import timedelta

        from models import AuditLog, Challenge, db

        challenge = Challenge(
            title="Audit Test Challenge",
            description="Test Description",
            max_eval_requests=3,
            start_time=utcnow(),
            end_time=utcnow() + timedelta(hours=2),
        )
        db.session.add(challenge)
        db.session.commit()

        # Audit log for challenge itself
        log1 = AuditLog(
            admin_id=self.admin.id,
            action_type="create",
            target_type="challenge",
            target_id=challenge.id,
            timestamp=utcnow(),
        )
        # Audit log unrelated
        log2 = AuditLog(
            admin_id=self.admin.id,
            action_type="create",
            target_type="user",
            target_id=self.competitor.id,
            timestamp=utcnow(),
        )
        db.session.add_all([log1, log2])
        db.session.commit()

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        res = self.client.get(f"/api/admin/audit-logs?challenge_id={challenge.id}", headers=headers)
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["logs"]) == 1
        assert data["logs"][0]["target_id"] == str(challenge.id)

    def test_download_challenge_audit_logs_forbidden_for_jury(self):
        from datetime import timedelta

        from models import Challenge, db

        challenge = Challenge(
            title="Download Test Challenge",
            description="Test Description",
            max_eval_requests=3,
            start_time=utcnow(),
            end_time=utcnow() + timedelta(hours=2),
        )
        db.session.add(challenge)
        db.session.commit()

        # Jury token should get 403
        headers = {"Authorization": f"Bearer {self.jury_token}"}
        res = self.client.get(
            f"/api/challenges/{challenge.id}/audit-logs/download", headers=headers
        )
        assert res.status_code == 403

        # Admin token should get 200
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        res = self.client.get(
            f"/api/challenges/{challenge.id}/audit-logs/download", headers=headers
        )
        assert res.status_code == 200
