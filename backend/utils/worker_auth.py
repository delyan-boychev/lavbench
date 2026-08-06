"""Authenticate workers and authorize narrowly scoped worker operations."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any

from config import Config
from utils.cache_utils import get_coordination_client

logger = logging.getLogger(__name__)

_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_AUTH_VERSION = "v1"
_AUTH_WINDOW_SECONDS = 300


class WorkerCapabilityClaimError(RuntimeError):
    """Signal that capability claiming failed and the Celery delivery must retry."""

    def __init__(self, message: str, retry_after: int = 15) -> None:
        super().__init__(message)
        self.retry_after = max(1, retry_after)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _public_key_registry() -> dict[str, str]:
    raw = os.environ.get("WORKER_PUBLIC_KEYS_JSON", Config.WORKER_PUBLIC_KEYS_JSON)
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        logger.critical("WORKER_PUBLIC_KEYS_JSON is not valid JSON")
        return {}
    if not isinstance(parsed, dict):
        logger.critical("WORKER_PUBLIC_KEYS_JSON must be a JSON object")
        return {}
    return {str(key): str(value) for key, value in parsed.items() if value}


def sign_worker_token() -> str:
    """Create a fresh per-request Ed25519 worker authentication token."""
    worker_id = os.environ.get("WORKER_ID", Config.WORKER_ID)
    private_key_b64 = os.environ.get("WORKER_PRIVATE_KEY", Config.WORKER_PRIVATE_KEY)
    if not worker_id or not _WORKER_ID_RE.fullmatch(worker_id) or not private_key_b64:
        return ""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(18)
        message = ".".join((_AUTH_VERSION, worker_id, timestamp, nonce))
        key = Ed25519PrivateKey.from_private_bytes(_b64decode(private_key_b64))
        return f"{message}.{_b64encode(key.sign(message.encode()))}"
    except Exception as exc:
        logger.warning("Failed to sign worker token: %s", exc)
        return ""


def check_worker_auth(token: str | None) -> dict[str, str] | None:
    """Verify a registered worker token and atomically consume its nonce."""
    if not token:
        return None
    try:
        version, worker_id, timestamp, nonce, signature = token.split(".", 4)
        if version != _AUTH_VERSION or not _WORKER_ID_RE.fullmatch(worker_id):
            return None
        timestamp_int = int(timestamp)
        if abs(time.time() - timestamp_int) > _AUTH_WINDOW_SECONDS:
            return None
        public_key_b64 = _public_key_registry().get(worker_id)
        if not public_key_b64:
            logger.warning("Worker auth rejected unknown worker %s", worker_id)
            return None

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        message = ".".join((version, worker_id, timestamp, nonce))
        key = Ed25519PublicKey.from_public_bytes(_b64decode(public_key_b64))
        key.verify(_b64decode(signature), message.encode())
    except Exception as exc:
        logger.warning("Worker auth failed: %s", exc)
        return None

    redis_client = get_coordination_client()
    if redis_client is None:
        logger.error("Worker auth rejected because replay protection is unavailable")
        return None
    nonce_digest = hashlib.sha256(f"{worker_id}:{nonce}".encode()).hexdigest()
    try:
        consumed = redis_client.set(
            f"worker:auth:nonce:{nonce_digest}", "1", nx=True, ex=_AUTH_WINDOW_SECONDS
        )
    except Exception as exc:
        logger.error("Worker auth replay protection failed: %s", exc)
        return None
    if not consumed:
        logger.warning("Worker auth rejected replay from worker %s", worker_id)
        return None
    return {"worker_id": worker_id, "ts": timestamp, "nonce": nonce}


def issue_worker_capability(
    *,
    worker_id: str,
    method: str,
    operation: str,
    resource_type: str,
    resource_id: Any,
    attempt_id: str,
    ttl_seconds: int | None = None,
) -> str:
    """Issue a server-signed capability for one worker operation and resource."""
    now = int(time.time())
    payload = {
        "v": 1,
        "worker_id": worker_id,
        "method": method.upper(),
        "operation": operation,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "attempt_id": attempt_id,
        "iat": now,
        "exp": now + (ttl_seconds or Config.WORKER_CAPABILITY_TTL),
        "jti": secrets.token_urlsafe(16),
    }
    encoded = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    secret = os.environ.get("WORKER_CAPABILITY_SECRET", Config.WORKER_CAPABILITY_SECRET)
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_worker_capability(
    token: str | None,
    *,
    worker_id: str,
    method: str,
    operation: str,
    resource_type: str,
    resource_id: Any,
    attempt_id: str | None = None,
) -> dict[str, Any] | None:
    """Verify the signature, expiry, scope, resource, worker, and attempt claims."""
    if not token:
        return None
    try:
        encoded, signature = token.split(".", 1)
        secret = os.environ.get("WORKER_CAPABILITY_SECRET", Config.WORKER_CAPABILITY_SECRET)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(signature), expected):
            return None
        payload = json.loads(_b64decode(encoded))
        if not isinstance(payload, dict):
            return None
        expected_claims = {
            "worker_id": worker_id,
            "method": method.upper(),
            "operation": operation,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
        }
        if any(payload.get(key) != value for key, value in expected_claims.items()):
            return None
        if attempt_id is not None and payload.get("attempt_id") != attempt_id:
            return None
        now = int(time.time())
        if payload.get("v") != 1 or int(payload.get("iat", 0)) > now + 30:
            return None
        if int(payload.get("exp", 0)) < now:
            return None
        if not payload.get("attempt_id") or not payload.get("jti"):
            return None
        return payload
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def worker_request_headers(metadata: dict[str, Any], operation: str) -> dict[str, str]:
    """Build fresh authentication headers for a metadata-scoped worker request."""
    capabilities = metadata.get("worker_capabilities") or {}
    capability = capabilities.get(operation) if isinstance(capabilities, dict) else None
    return {
        "X-Worker-Token": sign_worker_token(),
        "X-Worker-Capability": str(capability or ""),
    }


def fetch_submission_capabilities(metadata: dict[str, Any]) -> None:
    """Claim an attempt and fetch its server-issued worker capability set."""
    if metadata.get("worker_capabilities"):
        return
    main_server_url = metadata.get("main_server_url")
    submission_id = metadata.get("submission_id")
    attempt_id = metadata.get("attempt_id")
    if not main_server_url or not submission_id or not attempt_id:
        raise WorkerCapabilityClaimError("Submission attempt metadata is incomplete.")
    try:
        import requests

        response = requests.post(
            f"{str(main_server_url).rstrip('/')}/api/worker/capabilities/{submission_id}",
            json={"attempt_id": str(attempt_id)},
            headers={"X-Worker-Token": sign_worker_token()},
            timeout=Config.WORKER_REPORT_TIMEOUT,
        )
        if response.status_code != 200:
            logger.error("Capability claim failed with HTTP %s", response.status_code)
            retry_after = 15
            with contextlib.suppress(TypeError, ValueError):
                retry_after = int(response.json().get("retry_after", retry_after))
            raise WorkerCapabilityClaimError(
                f"Capability claim failed with HTTP {response.status_code}.", retry_after
            )
        capabilities = response.json().get("capabilities")
        if not isinstance(capabilities, dict):
            raise WorkerCapabilityClaimError("Capability claim returned an invalid response.")
        metadata["worker_capabilities"] = capabilities
    except WorkerCapabilityClaimError:
        raise
    except Exception as exc:
        logger.error("Capability claim failed: %s", exc)
        raise WorkerCapabilityClaimError("Capability claim request failed.") from exc


def build_submission_capabilities(metadata: dict[str, Any], worker_id: str) -> dict[str, str]:
    """Build the complete least-privilege capability set for one dispatch."""
    attempt_id = str(metadata["attempt_id"])
    submission_id = metadata["submission_id"]
    task_id = metadata["task_id"]
    return {
        "submission_run_content": issue_worker_capability(
            worker_id=worker_id,
            attempt_id=attempt_id,
            method="GET",
            operation="submission_run_content",
            resource_type="submission",
            resource_id=submission_id,
        ),
        "report_submission": issue_worker_capability(
            worker_id=worker_id,
            attempt_id=attempt_id,
            method="POST",
            operation="report_submission",
            resource_type="submission",
            resource_id=submission_id,
        ),
        "task_file": issue_worker_capability(
            worker_id=worker_id,
            attempt_id=attempt_id,
            method="GET",
            operation="task_file",
            resource_type="task",
            resource_id=task_id,
        ),
        "task_hf_key": issue_worker_capability(
            worker_id=worker_id,
            attempt_id=attempt_id,
            method="GET",
            operation="task_hf_key",
            resource_type="task",
            resource_id=task_id,
        ),
        "report_build_error": issue_worker_capability(
            worker_id=worker_id,
            attempt_id=attempt_id,
            method="POST",
            operation="report_build_error",
            resource_type="task",
            resource_id=task_id,
        ),
    }
