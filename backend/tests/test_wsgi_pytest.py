"""Tests for the web-process setup: psycogreen, web-only DB options and lazy heavy imports."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from config import Config, _postgres_engine_options

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")
HEAVY_MODULES = ("pandas", "numpy", "sklearn")


def _run_python(code: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///:memory:"
    env.pop("WORKER_ROLE", None)
    return subprocess.check_output(  # noqa: S603 -- fixed code strings from this module
        [sys.executable, "-c", code], env=env, cwd=BACKEND_DIR, text=True
    ).strip()


class TestEngineOptions:
    def test_pool_settings_come_from_config(self):
        options = _postgres_engine_options(
            "postgresql://u:p@db/lavbench", pool_size=7, max_overflow=3, statement_timeout_ms=100
        )
        assert options["pool_size"] == 7
        assert options["max_overflow"] == 3
        assert options["pool_pre_ping"] is True
        assert options["connect_args"]["options"] == "-c statement_timeout=100"

    def test_idle_in_transaction_timeout_only_when_requested(self):
        options = _postgres_engine_options(
            "postgresql://u:p@db/lavbench",
            pool_size=1,
            max_overflow=1,
            statement_timeout_ms=100,
            idle_in_transaction_timeout_ms=300000,
        )
        assert options["connect_args"]["options"] == (
            "-c statement_timeout=100 -c idle_in_transaction_session_timeout=300000"
        )

    def test_non_postgres_databases_get_no_options(self):
        assert (
            _postgres_engine_options(
                "sqlite:///:memory:", pool_size=1, max_overflow=1, statement_timeout_ms=1
            )
            == {}
        )

    def test_default_options_never_carry_the_idle_timeout(self):
        # Celery processes use these defaults; only utils/wsgi.py switches to web options
        options = Config.SQLALCHEMY_ENGINE_OPTIONS.get("connect_args", {}).get("options", "")
        assert "idle_in_transaction_session_timeout" not in options

    def test_web_process_switch_adds_the_idle_timeout(self, monkeypatch):
        monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "postgresql://u:p@db/lavbench")
        monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
        Config.use_web_process_engine_options()
        options = Config.SQLALCHEMY_ENGINE_OPTIONS
        assert options["pool_size"] == Config.DB_POOL_SIZE
        assert options["max_overflow"] == Config.DB_MAX_OVERFLOW
        assert (
            f"idle_in_transaction_session_timeout={Config.PG_IDLE_IN_TRANSACTION_TIMEOUT_MS}"
            in options["connect_args"]["options"]
        )


@pytest.mark.timeout(120)
class TestWebProcessImports:
    def test_idle_in_transaction_timeout_defaults_to_five_minutes(self):
        # Long multipart uploads touch ORM objects first, so 60 s would abort them
        out = _run_python(
            "import os; os.environ.pop('PG_IDLE_IN_TRANSACTION_TIMEOUT_MS', None); "
            "from config import Config; print(Config.PG_IDLE_IN_TRANSACTION_TIMEOUT_MS)"
        )
        assert out.splitlines()[-1] == "300000"

    def test_wsgi_patches_psycopg_for_gevent(self):
        out = _run_python(
            "import utils.wsgi, psycopg2.extensions as e; "
            "cb = e.get_wait_callback(); print(cb.__module__ if cb else None)"
        )
        assert out.splitlines()[-1] == "psycogreen.gevent"

    def test_web_app_import_loads_no_heavy_data_libraries(self):
        out = _run_python(
            "import sys, app; "
            f"print(','.join(m for m in {HEAVY_MODULES!r} if m in sys.modules) or 'none')"
        )
        assert out.splitlines()[-1] == "none"
