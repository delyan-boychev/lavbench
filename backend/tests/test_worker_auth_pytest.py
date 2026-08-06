"""Tests for per-worker authentication and scoped capabilities."""

import base64
import json
import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from utils.worker_auth import (
    check_worker_auth,
    issue_worker_capability,
    sign_worker_token,
    verify_worker_capability,
)


class _NonceStore:
    def __init__(self):
        self.keys = set()

    def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.keys:
            return False
        self.keys.add(key)
        return True


def _configure_worker(monkeypatch, worker_id="worker-a"):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("WORKER_ID", worker_id)
    monkeypatch.setenv(
        "WORKER_PRIVATE_KEY", base64.urlsafe_b64encode(key.private_bytes_raw()).decode()
    )
    monkeypatch.setenv(
        "WORKER_PUBLIC_KEYS_JSON",
        json.dumps(
            {worker_id: base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode()}
        ),
    )
    monkeypatch.setenv("WORKER_CAPABILITY_SECRET", "capability-test-secret")


def test_worker_token_is_registered_and_single_use(monkeypatch):
    _configure_worker(monkeypatch)
    nonce_store = _NonceStore()
    token = sign_worker_token()
    with patch("utils.worker_auth.get_coordination_client", return_value=nonce_store):
        assert check_worker_auth(token)["worker_id"] == "worker-a"
        assert check_worker_auth(token) is None


def test_unknown_worker_is_rejected(monkeypatch):
    _configure_worker(monkeypatch)
    token = sign_worker_token()
    monkeypatch.setenv("WORKER_PUBLIC_KEYS_JSON", "{}")
    with patch("utils.worker_auth.get_coordination_client", return_value=_NonceStore()):
        assert check_worker_auth(token) is None


def test_capability_rejects_cross_resource_and_method(monkeypatch):
    _configure_worker(monkeypatch)
    token = issue_worker_capability(
        worker_id="worker-a",
        method="POST",
        operation="report_submission",
        resource_type="submission",
        resource_id="sub-1",
        attempt_id="attempt-1",
    )
    assert verify_worker_capability(
        token,
        worker_id="worker-a",
        method="POST",
        operation="report_submission",
        resource_type="submission",
        resource_id="sub-1",
        attempt_id="attempt-1",
    )
    assert not verify_worker_capability(
        token,
        worker_id="worker-a",
        method="GET",
        operation="report_submission",
        resource_type="submission",
        resource_id="sub-1",
        attempt_id="attempt-1",
    )
    assert not verify_worker_capability(
        token,
        worker_id="worker-a",
        method="POST",
        operation="report_submission",
        resource_type="submission",
        resource_id="sub-2",
        attempt_id="attempt-1",
    )


def test_expired_capability_is_rejected(monkeypatch):
    _configure_worker(monkeypatch)
    with patch("utils.worker_auth.time.time", return_value=time.time() - 10):
        token = issue_worker_capability(
            worker_id="worker-a",
            method="GET",
            operation="task_file",
            resource_type="task",
            resource_id="task-1",
            attempt_id="attempt-1",
            ttl_seconds=1,
        )
    assert not verify_worker_capability(
        token,
        worker_id="worker-a",
        method="GET",
        operation="task_file",
        resource_type="task",
        resource_id="task-1",
        attempt_id="attempt-1",
    )
