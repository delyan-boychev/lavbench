"""Server-side client for the nanoColab /v1 API."""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import urlsplit

import requests

from config import Config

logger = logging.getLogger(__name__)

RETRY_STATUS = frozenset({502, 503, 504})
RETRY_DELAYS = (0.5, 1.5)
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
UPLOAD_READ_TIMEOUT_SECONDS = 600.0
EXPORT_CHUNK = 1024 * 1024
_SHA256_DIGEST = re.compile(r"(?:^|,)\s*sha-256=:([A-Za-z0-9+/=]+):")


class NanoColabError(Exception):
    """A nanoColab call failed; ``message`` is nanoColab's reason, safe for admins only."""

    def __init__(self, status: int, message: str = "", retry_after: int | None = None) -> None:
        super().__init__(f"nanoColab returned status {status}")
        self.status = status
        self.message = message
        self.retry_after = retry_after


class NanoColabUnavailableError(NanoColabError):
    """nanoColab could not be reached or answered 5xx."""


class ExportIntegrityError(NanoColabError):
    """An exported file ended early or did not match its announced size or sha256."""

    def __init__(self, message: str) -> None:
        super().__init__(502, message)


def repr_digest_sha256(header: str) -> str | None:
    """The hex sha-256 of an RFC 9530 ``Repr-Digest`` header, or None."""
    found = _SHA256_DIGEST.search(header or "")
    if not found:
        return None
    try:
        raw = base64.b64decode(found.group(1), validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw.hex() if len(raw) == 32 else None


def url_allowed(url: str, allow_insecure_http: bool) -> bool:
    """HTTPS everywhere; plain http only to a local host when the dev flag is on."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.username or parts.password or not host:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and allow_insecure_http and host in LOCAL_HOSTS


def detail_message(detail: Any) -> str:
    """Flatten nanoColab's ``detail`` (a string, a dict or a 422 list) into one sentence."""
    if isinstance(detail, str):
        return detail[:500]
    if isinstance(detail, dict):
        message = str(detail.get("message") or "")
        fields = detail.get("fields")
        if isinstance(fields, list) and fields:
            message = f"{message} ({', '.join(str(f) for f in fields)})"
        return message[:500]
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                location = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                parts.append(f"{location}: {item.get('msg', '')}".strip(": "))
        return "; ".join(parts)[:500]
    return ""


def _retry_after(response: requests.Response) -> int | None:
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


def _error_from(response: requests.Response) -> NanoColabError:
    try:
        message = detail_message(response.json().get("detail"))
    except (ValueError, AttributeError):
        message = ""
    error_class = NanoColabUnavailableError if response.status_code >= 500 else NanoColabError
    return error_class(response.status_code, message, _retry_after(response))


def read_api_key(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        logger.error("Cannot read NANOCOLAB_API_KEY_FILE")
        return ""


class _ProgressReader:
    """File wrapper that reports how many bytes requests has sent."""

    def __init__(self, handle: IO[bytes], size: int, progress: Callable[[int], None]) -> None:
        self._handle = handle
        self._size = size
        self._sent = 0
        self._progress = progress

    def __len__(self) -> int:
        return self._size

    def read(self, amount: int = -1) -> bytes:
        chunk = self._handle.read(amount)
        self._sent += len(chunk)
        self._progress(self._sent)
        return chunk


def _new_session() -> requests.Session:
    return requests.Session()


@dataclass
class NanoColabClient:
    base_url: str
    api_key: str
    timeout: float
    allow_insecure_http: bool = False
    session: requests.Session = field(default_factory=lambda: _new_session())

    @classmethod
    def from_config(cls) -> NanoColabClient | None:
        """Build the client, or None when the integration is off or misconfigured."""
        if not Config.NANOCOLAB_API_URL:
            return None
        if not url_allowed(Config.NANOCOLAB_API_URL, Config.NANOCOLAB_ALLOW_INSECURE_HTTP):
            logger.error("NANOCOLAB_API_URL must use https")
            return None
        api_key = read_api_key(Config.NANOCOLAB_API_KEY_FILE)
        if not api_key:
            return None
        return cls(
            Config.NANOCOLAB_API_URL,
            api_key,
            Config.NANOCOLAB_TIMEOUT_SECONDS,
            Config.NANOCOLAB_ALLOW_INSECURE_HTTP,
        )

    def _once(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("nanoColab %s %s failed: %s", method, path, type(exc).__name__)
            raise NanoColabUnavailableError(503, "nanoColab is unreachable") from None
        if response.status_code >= 300:
            error = _error_from(response)
            logger.warning(
                "nanoColab %s %s returned %s: %s", method, path, error.status, error.message
            )
            raise error
        try:
            return response.json()
        except ValueError:
            raise NanoColabUnavailableError(502, "nanoColab sent an invalid response") from None

    def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None, retry: bool
    ) -> dict[str, Any]:
        for delay in RETRY_DELAYS if retry else ():
            try:
                return dict(self._once(method, path, body))
            except NanoColabUnavailableError as exc:
                if exc.retry_after is not None or exc.status not in RETRY_STATUS:
                    raise
                time.sleep(delay)
        return dict(self._once(method, path, body))

    def catalog(self) -> dict[str, Any]:
        """Workspace images, and the compute profiles when this nanoColab lists them."""
        body = self._request("GET", "/v1/images", retry=True)
        images = [image for image in body.get("images") or [] if isinstance(image, dict)]
        profiles = body.get("profiles")
        return {"images": images, "profiles": profiles if isinstance(profiles, list) else None}

    def start_asset_upload(self, version: str, size_bytes: int, sha256: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/assets/{version}/uploads",
            body={"size_bytes": size_bytes, "sha256": sha256},
            retry=True,
        )

    def upload_asset(
        self, target: dict[str, Any], path: str, progress: Callable[[int], None]
    ) -> None:
        """PUT the package to the signed URL; the URL carries the grant, so no API key."""
        url = str(target.get("url") or "")
        if target.get("method", "PUT") != "PUT" or not url_allowed(url, self.allow_insecure_http):
            raise NanoColabError(502, "The storage upload URL is not an allowed HTTPS URL")
        headers = {str(k): str(v) for k, v in (target.get("headers") or {}).items()}
        if any(name.lower() == "authorization" for name in headers):
            raise NanoColabError(502, "The storage upload URL must not carry credentials")
        headers.setdefault("Content-Type", "application/zip")
        size = os.path.getsize(path)
        try:
            with open(path, "rb") as handle:
                response = self.session.put(
                    url,
                    data=_ProgressReader(handle, size, progress),
                    headers=headers,
                    timeout=(self.timeout, UPLOAD_READ_TIMEOUT_SECONDS),
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            logger.warning("Environment package upload failed: %s", type(exc).__name__)
            raise NanoColabUnavailableError(503, "The package upload failed") from None
        if response.status_code >= 300:
            logger.warning("Environment package upload returned %s", response.status_code)
            raise _error_from(response)

    def complete_asset_upload(self, version: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/assets/{version}/complete", retry=True)

    def get_asset(self, version: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/assets/{version}", retry=True)

    def put_event(self, external_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/v1/events/{external_id}", body=payload, retry=True)

    def get_readiness(self, external_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/events/{external_id}/readiness", retry=True)

    def ensure_workspace(self, external_id: str, external_user_id: str) -> dict[str, Any]:
        return self._request(
            "PUT", f"/v1/events/{external_id}/workspaces/{external_user_id}", retry=True
        )

    def launch(self, workspace_id: str, external_user_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/launch",
            body={"external_user_id": external_user_id},
            retry=False,
        )

    def list_events(self) -> list[dict[str, Any]]:
        """Every event this API client owns, cancelled ones included."""
        body = self._request("GET", "/v1/events", retry=True)
        return [event for event in body.get("events") or [] if isinstance(event, dict)]

    def cancel_event(self, external_id: str, actor: str, reason: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/events/{external_id}/cancel",
            body={"actor": actor, "reason": reason},
            retry=True,
        )

    def export_metadata(
        self, workspace_id: str, external_user_id: str, path: str
    ) -> dict[str, Any]:
        """Size and sha256 of one declared file, without its content."""
        return self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/export/metadata",
            body={"external_user_id": external_user_id, "path": path},
            retry=True,
        )

    def export_raw(
        self,
        workspace_id: str,
        external_user_id: str,
        path: str,
        target: IO[bytes],
        max_bytes: int,
    ) -> dict[str, Any]:
        """Stream one declared file into *target*, checked against its length and digest."""
        try:
            response = self.session.post(
                f"{self.base_url}/v1/workspaces/{workspace_id}/export/raw",
                json={"external_user_id": external_user_id, "path": path},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=(self.timeout, Config.NANOCOLAB_EXPORT_TIMEOUT_SECONDS),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            logger.warning("nanoColab raw export failed: %s", type(exc).__name__)
            raise NanoColabUnavailableError(503, "nanoColab is unreachable") from None
        with contextlib.closing(response):
            if response.status_code >= 300:
                error = _error_from(response)
                logger.warning("nanoColab raw export returned %s: %s", error.status, error.message)
                raise error
            length = response.headers.get("Content-Length", "")
            expected_sha = repr_digest_sha256(response.headers.get("Repr-Digest", ""))
            if not length.isdigit() or expected_sha is None:
                raise ExportIntegrityError("The export has no Content-Length or Repr-Digest")
            expected_size = int(length)
            if expected_size > max_bytes:
                raise NanoColabError(413, "The file exceeds the export limit")
            digest = hashlib.sha256()
            received = 0
            try:
                for chunk in response.iter_content(chunk_size=EXPORT_CHUNK):
                    received += len(chunk)
                    if received > expected_size:
                        raise ExportIntegrityError("The export is longer than announced")
                    digest.update(chunk)
                    target.write(chunk)
            except requests.RequestException:
                raise ExportIntegrityError("The export ended early") from None
            if received != expected_size or digest.hexdigest() != expected_sha:
                raise ExportIntegrityError("The export does not match its size or digest")
            return {
                "size": received,
                "sha256": expected_sha,
                "source": response.headers.get("X-Export-Source") or None,
                "modified_at": response.headers.get("Last-Modified") or None,
            }
