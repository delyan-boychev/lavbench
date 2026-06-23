import json
import pytest
import uuid
from unittest.mock import patch


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
            self._log(action_type="delete", target_type="task", target_id=self.dummy_uuids[3 + i])
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
