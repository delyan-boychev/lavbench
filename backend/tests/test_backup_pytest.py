"""Tests for the backup task."""

import os
import subprocess
import sys
import tarfile
from datetime import timedelta
from unittest.mock import ANY, MagicMock, patch

import pytest

from utils.dates import utcnow

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config
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


class TestBackupArchive:
    """The uploads archive skips rebuildable packages and uses fast gzip."""

    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, tmp_path, monkeypatch):
        self.app = app
        self.uploads = tmp_path / "uploads"
        (self.uploads / "task_1").mkdir(parents=True)
        (self.uploads / "task_1" / "x-data.parquet").write_bytes(b"task data")
        (self.uploads / "environment_packages").mkdir()
        (self.uploads / "environment_packages" / "environment-1.zip").write_bytes(b"package")
        monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(self.uploads))
        monkeypatch.setattr(Config, "BACKUPS_DIR", str(tmp_path / "backups"))
        monkeypatch.setattr(Config, "BACKUP_TIMEOUT", 11)
        monkeypatch.setattr(Config, "BACKUP_UPLOADS_TIMEOUT", 22)
        self.backups = tmp_path / "backups"

    def _run(self, db_only: bool = False):
        real_run = subprocess.run
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            if "pg_dump" in args:
                with open(args[args.index("-f") + 1], "w") as fh:
                    fh.write("-- dump")
                return MagicMock(returncode=0, stderr="")
            return real_run(args, **kwargs)

        with (
            patch("tasks.task_modules.system.subprocess.run", side_effect=fake_run),
            self.app.app_context(),
        ):
            filename = run_backup(self.app, auto=False, db_only=db_only)
        return self.backups / filename, calls

    def test_full_backup_excludes_packages_and_uses_fast_gzip(self):
        archive, calls = self._run()
        tar_args, tar_kwargs = calls[-1]
        assert "--use-compress-program=gzip -1" in tar_args
        assert tar_kwargs["timeout"] == 22
        assert calls[0][1]["timeout"] == 11
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        assert "uploads/task_1/x-data.parquet" in names
        assert "db_dump.sql" in names
        assert not any("environment_packages" in name for name in names)

    def test_database_only_backup_uses_the_same_tar_timeout(self):
        archive, calls = self._run(db_only=True)
        assert calls[-1][1]["timeout"] == 22
        with tarfile.open(archive, "r:gz") as tar:
            assert not any(name.startswith("uploads") for name in tar.getnames())

    def test_dispatch_claim_outlives_the_uploads_archive(self):
        from tasks.task_modules.system import backup_dispatch_ttl

        assert backup_dispatch_ttl() >= 11 + 22


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


def test_backup_list_is_newest_first_by_modification_time(tmp_path):
    from routes.admin import _list_backup_files

    # By name, every auto_db_* would sort above every auto_2026...; by time they interleave
    written = [
        ("auto_20261114_060000.tar.gz", 1_000),
        ("auto_db_20261114_062000.tar.gz", 2_000),
        ("manual_20261114_063000.tar.gz", 3_000),
        ("auto_db_20261114_064000.tar.gz", 4_000),
        ("auto_20261114_120000.tar.gz", 5_000),
        ("auto_db_20261114_120000.tar.gz", 5_000),
    ]
    for name, mtime in written:
        path = tmp_path / name
        path.write_bytes(b"x")
        os.utime(path, (mtime, mtime))
    (tmp_path / "notes.txt").write_text("not a backup")

    listed = [entry["filename"] for entry in _list_backup_files(str(tmp_path))]
    assert listed == [
        # Same modification time: the filename breaks the tie, newest first
        "auto_db_20261114_120000.tar.gz",
        "auto_20261114_120000.tar.gz",
        "auto_db_20261114_064000.tar.gz",
        "manual_20261114_063000.tar.gz",
        "auto_db_20261114_062000.tar.gz",
        "auto_20261114_060000.tar.gz",
    ]
    types = {entry["filename"]: entry["type"] for entry in _list_backup_files(str(tmp_path))}
    assert types["manual_20261114_063000.tar.gz"] == "manual"
    assert types["auto_db_20261114_064000.tar.gz"] == "auto"


def _fake_backup_commands(args, **kwargs):
    """Stand in for pg_dump and tar; tar still leaves the archive it would have written."""
    if "tar" in args:
        target = args[args.index("-cf") + 1]
        with open(target, "wb") as f:
            f.write(b"new")
    result = MagicMock()
    result.returncode = 0
    return result


class TestBackupPolicy:
    """Retention per kind, the free-space rule, rotated-log exclusion and the schedule."""

    @staticmethod
    def _make_backups(directory, prefix, count, size=1024):
        import time as _time

        paths = []
        for i in range(count):
            p = directory / f"{prefix}_2026111{i}_000000.tar.gz"
            p.write_bytes(b"x" * size)
            paths.append(p)
            _time.sleep(0.01)
        return paths

    @staticmethod
    def _remaining(directory):
        db_only = sorted(p.name for p in directory.glob("auto_db_*.tar.gz"))
        full = sorted(
            p.name for p in directory.glob("auto_*.tar.gz") if not p.name.startswith("auto_db_")
        )
        return db_only, full

    @staticmethod
    def _backup(app, tmp_path, db_only):
        with (
            patch("tasks.task_modules.system.Config.BACKUPS_DIR", str(tmp_path)),
            patch("tasks.task_modules.system.Config.BACKUP_RETENTION_COUNT", 2),
            patch("tasks.task_modules.system.Config.BACKUP_DB_RETENTION_COUNT", 4),
            patch("tasks.task_modules.system.Config.MIN_BACKUP_DISK_GB", 0),
            patch("tasks.task_modules.system.subprocess.run", side_effect=_fake_backup_commands),
            app.app_context(),
        ):
            return run_backup(app, auto=True, db_only=db_only)

    def test_db_only_backups_keep_their_own_retention_count(self, app, db_session, tmp_path):
        full = self._make_backups(tmp_path, "auto", 5)
        db_only = self._make_backups(tmp_path, "auto_db", 5)
        filename = self._backup(app, tmp_path, db_only=True)

        assert filename.startswith("auto_db_")
        remaining_db, remaining_full = self._remaining(tmp_path)
        assert len(remaining_db) == 4
        assert filename in remaining_db
        assert {p.name for p in db_only[-3:]} <= set(remaining_db)
        assert remaining_full == sorted(p.name for p in full)

    def test_full_backups_keep_backup_retention_count(self, app, db_session, tmp_path):
        full = self._make_backups(tmp_path, "auto", 5)
        db_only = self._make_backups(tmp_path, "auto_db", 5)
        filename = self._backup(app, tmp_path, db_only=False)

        assert filename.startswith("auto_")
        assert not filename.startswith("auto_db_")
        remaining_db, remaining_full = self._remaining(tmp_path)
        assert remaining_full == sorted([full[-1].name, filename])
        assert remaining_db == sorted(p.name for p in db_only)

    def test_db_only_history_spans_the_gap_between_full_backups(self):
        import tasks
        from config import Config

        assert Config.BACKUP_DB_RETENTION_COUNT == 18
        history = Config.BACKUP_DB_RETENTION_COUNT * tasks._ACTIVE_BACKUP_INTERVAL
        assert history >= timedelta(seconds=Config.BACKUP_UPLOADS_INTERVAL_SECONDS)

    def test_free_space_must_be_twice_the_last_backup(self, tmp_path):
        from tasks.task_modules import system

        self._make_backups(tmp_path, "auto", 1, size=4096)
        with patch.object(system.Config, "MIN_BACKUP_DISK_GB", 0):
            assert system._required_free_bytes(str(tmp_path), db_only=False) == 8192
            with patch.object(system.shutil, "disk_usage") as usage:
                usage.return_value.free = 8191
                with pytest.raises(RuntimeError, match="Insufficient disk space"):
                    system._check_free_space(str(tmp_path), db_only=False)
                usage.return_value.free = 8192
                system._check_free_space(str(tmp_path), db_only=False)

    def test_free_space_floor_applies_without_previous_backup(self, tmp_path):
        from tasks.task_modules import system

        with patch.object(system.Config, "MIN_BACKUP_DISK_GB", 2):
            assert system._required_free_bytes(str(tmp_path), db_only=True) == 2 * 1024**3

    def test_free_space_uses_the_last_backup_of_the_same_kind(self, tmp_path):
        from tasks.task_modules import system

        self._make_backups(tmp_path, "auto", 1, size=10_000)
        self._make_backups(tmp_path, "auto_db", 1, size=100)
        with patch.object(system.Config, "MIN_BACKUP_DISK_GB", 0):
            assert system._required_free_bytes(str(tmp_path), db_only=True) == 200
            assert system._required_free_bytes(str(tmp_path), db_only=False) == 20_000

    def test_rotated_log_files_are_excluded(self, app, db_session, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        with (
            patch("tasks.task_modules.system.Config.BACKUPS_DIR", str(tmp_path / "b")),
            patch("tasks.task_modules.system.Config.LOG_DIR", str(log_dir)),
            patch("tasks.task_modules.system.Config.MIN_BACKUP_DISK_GB", 0),
            patch("tasks.task_modules.system.subprocess.run") as run,
            patch("tasks.task_modules.system.shutil.copytree") as copytree,
            patch("tasks.task_modules.system.os.path.getsize", return_value=1),
            app.app_context(),
        ):
            run.return_value.returncode = 0
            run_backup(app, auto=True, db_only=True)
        ignore = copytree.call_args.kwargs["ignore"]
        names = ["backend.log", "backend.log.1", "celery.log.12", "old.gz", "worker_remote.log"]
        assert ignore(str(log_dir), names) == {"backend.log.1", "celery.log.12", "old.gz"}


class TestBackupSchedule:
    @pytest.fixture(autouse=True)
    def setup(self, app, db_session, redis_flush):
        import tasks

        tasks.app = app
        self.challenge = Challenge(
            title="Backup Schedule",
            description="Test",
            max_eval_requests=5,
            start_time=utcnow() - timedelta(hours=1),
            end_time=utcnow() + timedelta(hours=2),
            is_frozen=False,
        )
        db.session.add(self.challenge)
        db.session.commit()

    @staticmethod
    def _set_markers(last=None, last_full=None):
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if r is None:
            pytest.skip("Redis unavailable")
        r.delete("backup:auto_dispatched")
        for key, value in (("backup:last_auto", last), ("backup:last_auto_full", last_full)):
            if value is None:
                r.delete(key)
            else:
                r.set(key, value.isoformat(), ex=3600)

    @staticmethod
    def _broker():
        from utils.cache_utils import get_coordination_client

        r = get_coordination_client()
        if r is None:
            pytest.skip("Redis unavailable")
        return r

    @staticmethod
    def _value(r, key):
        raw = r.get(key)
        return raw.decode() if isinstance(raw, bytes) else raw

    @staticmethod
    def _dispatch():
        """Run the check with the Celery send mocked; return the queued kwargs (or None)."""
        with patch("tasks.run_backup.delay") as delay:
            result = check_and_backup()
        return (delay.call_args.kwargs if delay.called else None), result

    @staticmethod
    def _run_task(tmp_path, kwargs, fail=False):
        """Run the queued backup task in-process, as the internal worker would."""
        import tasks

        with (
            patch.object(tasks, "RUNS_INTERNAL", True),
            patch("tasks.task_modules.system.Config.BACKUPS_DIR", str(tmp_path)),
            patch("tasks.task_modules.system.Config.MIN_BACKUP_DISK_GB", 0),
            patch("tasks.task_modules.system.subprocess.run", side_effect=_fake_backup_commands),
        ):
            if not fail:
                return tasks.run_backup(**kwargs)
            with (
                patch(
                    "tasks.task_modules.system._check_free_space",
                    side_effect=RuntimeError("Insufficient disk space for backup"),
                ),
                pytest.raises(RuntimeError, match="Insufficient disk space"),
            ):
                tasks.run_backup(**kwargs)
            return None

    def test_claim_and_markers_live_on_the_broker_redis(self, monkeypatch):
        from tasks.task_modules import system

        broker, cache = MagicMock(), MagicMock()
        broker.get.return_value = None
        broker.set.return_value = True
        monkeypatch.setattr("utils.cache_utils.get_coordination_client", lambda: broker)
        monkeypatch.setattr("utils.cache_utils.get_redis_client", lambda: cache)
        with patch("tasks.run_backup.delay"):
            check_and_backup()
        # The check only claims the dispatch; the markers wait for a written archive
        assert {call.args[0] for call in broker.set.call_args_list} == {"backup:auto_dispatched"}

        broker.set.reset_mock()
        system._record_auto_backup(db_only=False, started_at="2026-11-14T10:00:00")
        written = {call.args[0] for call in broker.set.call_args_list}
        assert written == {"backup:last_auto", "backup:last_auto_full"}
        cache.set.assert_not_called()

    def test_failed_backup_leaves_no_marker_and_is_retried_at_the_next_check(self, tmp_path):
        self._set_markers()
        r = self._broker()
        queued, _ = self._dispatch()
        assert queued is not None
        assert queued["scheduled_at"]

        self._run_task(tmp_path, queued, fail=True)
        assert r.get("backup:last_auto") is None
        assert r.get("backup:last_auto_full") is None
        assert r.get("backup:auto_dispatched") is None

        retried, result = self._dispatch()
        assert retried is not None
        assert retried["db_only"] is False
        assert result["backup"] == "full"

    def test_successful_backup_records_its_scheduled_time(self, tmp_path):
        now = utcnow()
        last_full = now - timedelta(hours=1)
        self._set_markers(last=now - timedelta(minutes=20), last_full=last_full)
        r = self._broker()
        queued, _ = self._dispatch()
        assert queued is not None
        assert queued["db_only"] is True

        filename = self._run_task(tmp_path, queued)
        assert filename.startswith("auto_db_")
        assert self._value(r, "backup:last_auto") == queued["scheduled_at"]
        # A database-only backup leaves the full-backup marker alone
        assert self._value(r, "backup:last_auto_full") == last_full.isoformat()
        assert r.get("backup:auto_dispatched") is None

        again, result = self._dispatch()
        assert again is None
        assert "backup" not in result

    def test_successful_full_backup_sets_both_markers(self, tmp_path):
        self._set_markers()
        r = self._broker()
        queued, _ = self._dispatch()
        assert queued is not None
        assert queued["db_only"] is False

        self._run_task(tmp_path, queued)
        assert self._value(r, "backup:last_auto") == queued["scheduled_at"]
        assert self._value(r, "backup:last_auto_full") == queued["scheduled_at"]

    def test_no_duplicate_is_queued_while_a_backup_runs(self):
        from tasks.task_modules.system import backup_dispatch_ttl

        self._set_markers()
        r = self._broker()
        first, _ = self._dispatch()
        assert first is not None

        second, result = self._dispatch()
        assert second is None
        assert result["backup"] == "in_progress"
        # The claim expires on its own, so a backup that never finishes cannot block forever
        assert 0 < r.ttl("backup:auto_dispatched") <= backup_dispatch_ttl()

    def test_a_late_release_never_frees_a_newer_claim(self):
        from tasks.task_modules.system import release_backup_dispatch

        r = self._broker()
        r.set("backup:auto_dispatched", "2026-11-14T10:20:00", ex=60)
        release_backup_dispatch("2026-11-14T10:00:00")
        assert self._value(r, "backup:auto_dispatched") == "2026-11-14T10:20:00"
        release_backup_dispatch("2026-11-14T10:20:00")
        assert r.get("backup:auto_dispatched") is None

    def test_first_run_takes_a_full_backup(self):
        self._set_markers()
        with patch("tasks.run_backup.delay") as delay:
            result = check_and_backup()
        delay.assert_called_once_with(auto=True, db_only=False, scheduled_at=ANY)
        assert result["backup"] == "full"

    def test_active_contest_backs_up_db_only_every_20_minutes(self):
        now = utcnow()
        self._set_markers(last=now - timedelta(minutes=20), last_full=now - timedelta(hours=1))
        with patch("tasks.run_backup.delay") as delay:
            result = check_and_backup()
        delay.assert_called_once_with(auto=True, db_only=True, scheduled_at=ANY)
        assert result["backup"] == "db_only"

    def test_uploads_are_included_once_their_interval_passed(self):
        from config import Config

        now = utcnow()
        self._set_markers(
            last=now - timedelta(minutes=21),
            last_full=now - timedelta(seconds=Config.BACKUP_UPLOADS_INTERVAL_SECONDS + 60),
        )
        with patch("tasks.run_backup.delay") as delay:
            check_and_backup()
        delay.assert_called_once_with(auto=True, db_only=False, scheduled_at=ANY)

    def test_nothing_runs_before_the_interval(self):
        now = utcnow()
        self._set_markers(last=now - timedelta(minutes=5), last_full=now - timedelta(minutes=5))
        with patch("tasks.run_backup.delay") as delay:
            result = check_and_backup()
        delay.assert_not_called()
        assert "backup" not in result

    def test_idle_backups_run_every_6_hours(self):
        self.challenge.end_time = utcnow() - timedelta(hours=1)
        db.session.commit()
        now = utcnow()
        self._set_markers(last=now - timedelta(hours=1), last_full=now - timedelta(hours=1))
        with patch("tasks.run_backup.delay") as delay:
            check_and_backup()
        delay.assert_not_called()

        self._set_markers(last=now - timedelta(hours=6), last_full=now - timedelta(hours=7))
        with patch("tasks.run_backup.delay") as delay:
            check_and_backup()
        delay.assert_called_once_with(auto=True, db_only=False, scheduled_at=ANY)


def test_list_backups_returns_size_and_type(client, tokens, auth_headers, monkeypatch, tmp_path):
    import routes.admin as admin_routes

    (tmp_path / "manual_20260101_000000.tar.gz").write_bytes(b"x" * 1024)
    (tmp_path / "auto_20260101_000000.tar.gz").write_bytes(b"x")
    monkeypatch.setattr(admin_routes, "BACKUPS_DIR", str(tmp_path))
    resp = client.get("/api/admin/backups", headers=auth_headers(tokens.admin))
    assert resp.status_code == 200
    rows = {row["filename"]: row for row in resp.get_json()["backups"]}
    assert rows["manual_20260101_000000.tar.gz"]["type"] == "manual"
    assert rows["auto_20260101_000000.tar.gz"]["type"] == "auto"
    assert rows["manual_20260101_000000.tar.gz"]["size_mb"] == 0.0
