"""Tests for the backup task."""

import os
import sys
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from utils.dates import utcnow

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Challenge, User, db
from routes.admin import _resolve_backup_path
from tasks import check_and_backup
from tasks.task_modules.system import run_backup
from utils.auth_utils import generate_token


class TestRunBackup:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["UPLOAD_FOLDER"] = "/tmp/test_uploads"
        os.makedirs(self.app.config["UPLOAD_FOLDER"], exist_ok=True)

    def _ctx(self):
        return self.app.app_context()

    @patch("tasks.task_modules.system.subprocess.run")
    @patch("tasks.task_modules.system.os.makedirs")
    @patch("tasks.task_modules.system.os.path.getsize")
    def test_run_backup_auto(self, mock_getsize, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_getsize.return_value = 1024
        with self._ctx():
            filename = run_backup(self.app, auto=True)
        assert filename is not None
        assert filename.startswith("auto_")

        # Verify nice -n 19 is prepended
        assert mock_run.call_count == 2
        pg_dump_args = mock_run.call_args_list[0][0][0]
        assert pg_dump_args[0:4] == ["nice", "-n", "19", "pg_dump"]

        tar_args = mock_run.call_args_list[1][0][0]
        assert tar_args[0:4] == ["nice", "-n", "19", "tar"]
        assert "audit_logs.json" in tar_args

    @patch("tasks.task_modules.system.subprocess.run")
    @patch("tasks.task_modules.system.os.makedirs")
    @patch("tasks.task_modules.system.os.path.getsize")
    def test_run_backup_manual(self, mock_getsize, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 0
        mock_getsize.return_value = 1024
        with self._ctx():
            filename = run_backup(self.app, auto=False)
        assert filename.startswith("manual_")

        # Verify nice -n 19 is NOT prepended
        assert mock_run.call_count == 2
        pg_dump_args = mock_run.call_args_list[0][0][0]
        assert pg_dump_args[0] == "pg_dump"

        tar_args = mock_run.call_args_list[1][0][0]
        assert tar_args[0] == "tar"
        assert "audit_logs.json" in tar_args

    @patch("tasks.task_modules.system.subprocess.run")
    @patch("tasks.task_modules.system.os.makedirs")
    def test_run_backup_pg_dump_failure(self, mock_makedirs, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "connection refused"
        with self._ctx(), pytest.raises(RuntimeError) as ctx:
            run_backup(self.app)
        assert "pg_dump failed" in str(ctx.value)

    @patch("tasks.task_modules.system.subprocess.run")
    @patch("tasks.task_modules.system.os.makedirs")
    def test_run_backup_tar_failure(self, mock_makedirs, mock_run):
        def side_effect(*args, **kwargs):
            if "pg_dump" in args[0]:
                result = MagicMock()
                result.returncode = 0
                return result
            result = MagicMock()
            result.returncode = 1
            result.stderr = "tar error"
            return result

        mock_run.side_effect = side_effect
        with self._ctx(), pytest.raises(RuntimeError) as ctx:
            run_backup(self.app)
        assert "tar failed" in str(ctx.value)

    @patch("tasks.task_modules.system.subprocess.run")
    @patch("tasks.task_modules.system.os.makedirs")
    @patch("tasks.task_modules.system.os.path.getsize")
    @patch("tasks.task_modules.system.glob.glob")
    @patch("tasks.task_modules.system.os.remove")
    @patch("tasks.task_modules.system.os.path.getctime")
    def test_run_backup_rotation_respects_custom_dir(
        self,
        mock_getctime,
        mock_remove,
        mock_glob,
        mock_getsize,
        mock_makedirs,
        mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_getsize.return_value = 1024
        mock_glob.return_value = [
            "/custom_backups/auto_1.tar.gz",
            "/custom_backups/auto_2.tar.gz",
            "/custom_backups/auto_3.tar.gz",
            "/custom_backups/auto_4.tar.gz",
            "/custom_backups/auto_5.tar.gz",
            "/custom_backups/auto_6.tar.gz",
            "/custom_backups/auto_7.tar.gz",
            "/custom_backups/auto_8.tar.gz",
        ]
        mock_getctime.side_effect = lambda path: {
            "/custom_backups/auto_1.tar.gz": 1,
            "/custom_backups/auto_2.tar.gz": 2,
            "/custom_backups/auto_3.tar.gz": 3,
            "/custom_backups/auto_4.tar.gz": 4,
            "/custom_backups/auto_5.tar.gz": 5,
            "/custom_backups/auto_6.tar.gz": 6,
            "/custom_backups/auto_7.tar.gz": 7,
            "/custom_backups/auto_8.tar.gz": 8,
        }.get(path, 0)
        with patch("tasks.task_modules.system.Config.BACKUPS_DIR", "/custom_backups"), self._ctx():
            run_backup(self.app, auto=True)
        mock_glob.assert_called_with("/custom_backups/auto_*.tar.gz")
        assert mock_remove.call_count == 5
        mock_remove.assert_any_call("/custom_backups/auto_1.tar.gz")
        mock_remove.assert_any_call("/custom_backups/auto_2.tar.gz")
        mock_remove.assert_any_call("/custom_backups/auto_3.tar.gz")
        mock_remove.assert_any_call("/custom_backups/auto_4.tar.gz")
        mock_remove.assert_any_call("/custom_backups/auto_5.tar.gz")


class TestCheckAndBackup:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, redis_flush):
        self.app = app
        import tasks

        tasks.app = app
        self.seed_basic_data()

    def seed_basic_data(self):
        self.challenge = Challenge(
            title="Backup Test",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=48),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.commit()

    def test_check_and_backup_returns_dict(self):
        result = check_and_backup()
        assert isinstance(result, dict)

    def test_check_and_backup_with_active_competition(self):
        result = check_and_backup()
        assert "active_competitions" in result

    def test_check_and_backup_expired_challenge(self):
        self.challenge.end_time = utcnow() - timedelta(hours=24)
        db.session.commit()
        result = check_and_backup()
        assert "active_competitions" in result


class TestAdminBackupEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, redis_flush):
        self.client = app.test_client()
        self.admin = User(
            username="backup_admin",
            password_hash="pbkdf2:sha256:...",
            role="admin",
            alias_id="Admin-Backup",
        )
        db.session.add(self.admin)
        db.session.commit()
        self.admin_token = generate_token(self.admin.id, role="admin")

        self.user = User(
            username="normal_user",
            password_hash="pbkdf2:sha256:...",
            role="competitor",
            alias_id="User-001",
        )
        db.session.add(self.user)
        db.session.commit()
        self.user_token = generate_token(self.user.id, role="competitor")

        self.jury = User(
            username="backup_jury",
            password_hash="pbkdf2:sha256:...",
            role="jury",
            alias_id="Jury-Backup",
        )
        db.session.add(self.jury)
        db.session.commit()
        self.jury_token = generate_token(self.jury.id, role="jury")

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_list_backups_admin_access(self):
        resp = self.client.get("/api/admin/backups", headers=self._auth(self.admin_token))
        assert resp.status_code == 200

    def test_list_backups_competitor_forbidden(self):
        resp = self.client.get("/api/admin/backups", headers=self._auth(self.user_token))
        assert resp.status_code == 403

    def test_list_backups_jury_forbidden(self):
        resp = self.client.get("/api/admin/backups", headers=self._auth(self.jury_token))
        assert resp.status_code == 403

    def test_list_backups_unauthenticated(self):
        resp = self.client.get("/api/admin/backups")
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "ERR_TOKEN_INVALID"

    def test_force_backup_admin_access(self):
        resp = self.client.post("/api/admin/backups/force", headers=self._auth(self.admin_token))
        assert resp.status_code not in (403, 401)

    def test_force_backup_competitor_forbidden(self):
        resp = self.client.post("/api/admin/backups/force", headers=self._auth(self.user_token))
        assert resp.status_code == 403

    def test_force_backup_jury_forbidden(self):
        resp = self.client.post("/api/admin/backups/force", headers=self._auth(self.jury_token))
        assert resp.status_code == 403

    def test_download_backup_not_found(self):
        resp = self.client.get(
            "/api/admin/backups/nonexistent.tar.gz/download",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 404

    def test_download_backup_competitor_forbidden(self):
        resp = self.client.get(
            "/api/admin/backups/test.tar.gz/download",
            headers=self._auth(self.user_token),
        )
        assert resp.status_code == 403

    def test_download_backup_jury_forbidden(self):
        resp = self.client.get(
            "/api/admin/backups/test.tar.gz/download",
            headers=self._auth(self.jury_token),
        )
        assert resp.status_code == 403

    def test_delete_backup_not_found(self):
        resp = self.client.delete(
            "/api/admin/backups/nonexistent.tar.gz",
            headers=self._auth(self.admin_token),
        )
        assert resp.status_code == 404

    def test_delete_backup_competitor_forbidden(self):
        resp = self.client.delete(
            "/api/admin/backups/test.tar.gz", headers=self._auth(self.user_token)
        )
        assert resp.status_code == 403

    def test_delete_backup_jury_forbidden(self):
        resp = self.client.delete(
            "/api/admin/backups/test.tar.gz", headers=self._auth(self.jury_token)
        )
        assert resp.status_code == 403


def test_resolve_backup_path_rejects_prefix_sibling(tmp_path):
    backup_dir = tmp_path / "backups"
    sibling_dir = tmp_path / "backups-stolen"
    backup_dir.mkdir()
    sibling_dir.mkdir()

    with patch("routes.admin.BACKUPS_DIR", str(backup_dir)):
        assert _resolve_backup_path("../backups-stolen/secret.tar.gz") is None


def test_resolve_backup_path_rejects_symlink_escape(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    outside_backup = tmp_path / "secret.tar.gz"
    outside_backup.write_bytes(b"secret")
    (backup_dir / "linked.tar.gz").symlink_to(outside_backup)

    with patch("routes.admin.BACKUPS_DIR", str(backup_dir)):
        assert _resolve_backup_path("linked.tar.gz") is None


def test_resolve_backup_path_accepts_contained_backup(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "manual_test.tar.gz"
    backup.write_bytes(b"backup")

    with patch("routes.admin.BACKUPS_DIR", str(backup_dir)):
        assert _resolve_backup_path(backup.name) == backup.resolve()
