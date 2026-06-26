"""pytest configuration: app factory, DB fixtures, auth helpers, and common seed data.

Sets required environment variables before any application code is imported so
that config.py and models.py do not crash at module load time.
"""

import hashlib
import os
import sys
import uuid
from datetime import datetime, timedelta

# ── Critical: set these BEFORE any app/model imports ──────────────────────
os.environ.setdefault(
    "SECRET_KEY", "conftest-test-secret-key-2024-abcdefgh"
)  # 32+ chars for HMAC-SHA256
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import contextlib  # noqa: E402

import pytest  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app import create_app  # noqa: E402
from auth_utils import generate_token  # noqa: E402
from models import Challenge, Stage, Submission, Task, User, db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def download_nltk_data():
    """Ensure NLTK datasets are downloaded and available for metrics evaluation."""
    import nltk

    for corpus in ["wordnet", "punkt", "punkt_tab", "omw-1.4"]:
        with contextlib.suppress(Exception):
            nltk.download(corpus, quiet=True)


# ═══════════════════════════════════════════════════════════════════════════
# App & Context
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def app():
    """Flask application — created once per test session."""
    import shutil
    import tempfile

    # Create temporary directory for uploads isolation
    test_upload_dir = tempfile.mkdtemp()
    os.environ["UPLOAD_FOLDER"] = test_upload_dir

    _app = create_app()
    _app.config["TESTING"] = True
    _app.config["UPLOAD_FOLDER"] = test_upload_dir

    yield _app

    # Cleanup temporary directory
    with contextlib.suppress(Exception):
        shutil.rmtree(test_upload_dir)


@pytest.fixture(scope="function")
def app_ctx(app):
    """Pushed application context — cleaned up after each test."""
    ctx = app.app_context()
    ctx.push()
    yield ctx
    ctx.pop()


@pytest.fixture(scope="function")
def client(app, app_ctx):
    """Test client bound to the current app and active context."""
    # Using app_ctx as a dependency guarantees the application context
    # is active for any worker thread handling this test client.
    with app.test_client() as _client:
        yield _client


@pytest.fixture(scope="function")
def db_session(app, app_ctx):
    """Fresh database for every test function.

    Creates all tables before the test and drops them after.
    """
    db.create_all()
    yield db.session
    db.session.remove()
    db.drop_all()


# ═══════════════════════════════════════════════════════════════════════════
# Redis flush (no-op when Redis is unavailable)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="function")
def redis_flush():
    """Flush Redis data before a test. Safe to call when Redis is down."""
    try:
        from cache_utils import get_redis_client

        r = get_redis_client()
        if r:
            # If running in parallel with xdist, flushing the whole DB
            # causes race conditions across workers.
            worker_id = os.environ.get("PYTEST_XDIST_WORKER")
            if worker_id:
                # If your backend isolates keys with prefixes (e.g., test_gw0_*),
                # scan and clear only those keys.
                for key in r.scan_iter(f"*{worker_id}*"):
                    r.delete(key)
            else:
                r.flushdb()
    except Exception:  # noqa: S110
        pass


# ═══════════════════════════════════════════════════════════════════════════
# Auth helpers
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def auth_headers():
    """Return a helper that builds ``Authorization: Bearer <token>`` headers."""

    def _make(token):
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
def csrf_headers():
    """Return a helper that builds CSRF + Authorization headers."""

    def _make(token, csrf_token="test-csrf-token"):
        return {
            "Authorization": f"Bearer {token}",
            "X-CSRF-Token": csrf_token,
            "Cookie": "csrf_token=test-csrf-token",
        }

    return _make


# ═══════════════════════════════════════════════════════════════════════════
# Factory fixture — creates a User with sensible defaults
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def create_user(db_session):
    """Factory fixture — call ``create_user(username=..., role=...)``."""

    def _make(
        username="testuser",
        password="testpass123",
        role="competitor",
        alias_id=None,
        challenge_id=None,
        jury_challenges=None,
    ):
        if alias_id is None:
            alias_id = f"{role}-{username}-{uuid.uuid4().hex[:6]}"
        client_hash = hashlib.sha256(password.encode()).hexdigest()
        pw_hash = generate_password_hash(client_hash, method="pbkdf2:sha256")
        user = User(
            username=username,
            password_hash=pw_hash,
            role=role,
            alias_id=alias_id,
            challenge_id=challenge_id,
        )
        db_session.add(user)
        db_session.flush()

        return user

    return _make


# ═══════════════════════════════════════════════════════════════════════════
# Common seed-data fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_challenge(db_session):
    """Active challenge used across many route tests."""
    challenge = Challenge(
        title="Sample Challenge",
        description="A sample challenge for testing",
        max_eval_requests=10,
        start_time=datetime.utcnow() - timedelta(hours=2),
        end_time=datetime.utcnow() + timedelta(hours=2),
        is_archived=False,
        double_blind=True,
        timezone="UTC",
    )
    db_session.add(challenge)
    db_session.flush()
    return challenge


@pytest.fixture
def sample_future_challenge(db_session):
    """Challenge that hasn't started yet."""
    challenge = Challenge(
        title="Future Challenge",
        description="A challenge that starts in the future",
        max_eval_requests=10,
        start_time=datetime.utcnow() + timedelta(days=1),
        end_time=datetime.utcnow() + timedelta(days=8),
        is_archived=False,
        double_blind=True,
        timezone="UTC",
    )
    db_session.add(challenge)
    db_session.flush()
    return challenge


@pytest.fixture
def archived_challenge(db_session):
    """Archived (ended) challenge."""
    challenge = Challenge(
        title="Archived Challenge",
        description="An archived competition",
        max_eval_requests=10,
        start_time=datetime.utcnow() - timedelta(days=10),
        end_time=datetime.utcnow() - timedelta(days=5),
        is_archived=True,
        double_blind=True,
        timezone="UTC",
    )
    db_session.add(challenge)
    db_session.flush()
    return challenge


@pytest.fixture
def sample_task(db_session, sample_challenge):
    """Task belonging to *sample_challenge*."""
    task = Task(
        title="Sample Task",
        challenge_id=sample_challenge.id,
        base_docker_image="python:3.10-slim",
        time_limit_sec=300,
        ram_limit_mb=512,
        max_submissions_per_period=10,
    )
    db_session.add(task)
    db_session.flush()
    return task


@pytest.fixture
def sample_stage(db_session, sample_challenge):
    """Stage within *sample_challenge*."""
    stage = Stage(
        title="Sample Stage",
        challenge_id=sample_challenge.id,
        stage_number=1,
        start_time=datetime.utcnow() - timedelta(hours=24),
        end_time=datetime.utcnow() + timedelta(hours=24),
    )
    db_session.add(stage)
    db_session.flush()
    return stage


@pytest.fixture
def sample_competitor(db_session, sample_challenge, create_user):
    """Ready-to-use competitor registered in *sample_challenge*."""
    return create_user(
        username="sample_comp",
        role="competitor",
        alias_id="Comp-001",
        challenge_id=sample_challenge.id,
    )


@pytest.fixture
def sample_admin(db_session, create_user):
    """Ready-to-use admin user."""
    return create_user(
        username="sample_admin",
        role="admin",
        alias_id="Admin-001",
    )


@pytest.fixture
def sample_other_competitor(db_session, sample_challenge, create_user):
    """Another competitor in the same challenge."""
    return create_user(
        username="other_comp",
        role="competitor",
        alias_id="Comp-002",
        challenge_id=sample_challenge.id,
    )


@pytest.fixture
def sample_comp_in_future_challenge(db_session, sample_future_challenge, create_user):
    """Competitor registered in the future challenge."""
    return create_user(
        username="future_comp",
        role="competitor",
        alias_id="Comp-003",
        challenge_id=sample_future_challenge.id,
    )


@pytest.fixture
def tokens(sample_competitor, sample_admin, sample_other_competitor):
    """JWT tokens for the three standard users."""

    class Tokens:
        competitor = generate_token(sample_competitor.id, "competitor")
        admin = generate_token(sample_admin.id, "admin")
        other = generate_token(sample_other_competitor.id, "competitor")

    return Tokens()


@pytest.fixture
def sample_submission(db_session, sample_challenge, sample_task, sample_competitor):
    """Minimal completed submission."""
    sub = Submission(
        user_id=sample_competitor.id,
        challenge_id=sample_challenge.id,
        task_id=sample_task.id,
        status="completed",
    )
    db_session.add(sub)
    db_session.flush()
    return sub
