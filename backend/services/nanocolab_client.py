"""Server-side client for the nano-colab /v1 compute API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from config import Config

logger = logging.getLogger(__name__)

RETRY_STATUS = frozenset({502, 503, 504})
RETRY_DELAYS = (0.5, 1.5)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_http(url: str) -> bool:
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        return False
    return parts.scheme == "http" and hostname in LOOPBACK_HOSTS and not parts.username


class NanoColabError(Exception):
    def __init__(self, status: int, detail: Any = None, retry_after: int | None = None) -> None:
        super().__init__(f"nano-colab returned status {status}")
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


class NanoColabUnavailableError(NanoColabError):
    pass


@dataclass(frozen=True)
class NanoColabClient:
    base_url: str
    api_key: str
    timeout: float
    upload_timeout: float = 600.0

    @classmethod
    def from_config(cls) -> NanoColabClient | None:
        if not Config.NANOCOLAB_API_URL or not Config.NANOCOLAB_API_KEY:
            return None
        return cls(
            Config.NANOCOLAB_API_URL, Config.NANOCOLAB_API_KEY, Config.NANOCOLAB_TIMEOUT_SECONDS
        )

    def _once(self, method: str, path: str, json: dict[str, Any] | None) -> Any:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.warning("nano-colab %s %s failed: %s", method, path, type(exc).__name__)
            raise NanoColabUnavailableError(503) from None
        if response.status_code < 400:
            return response.json()
        logger.warning("nano-colab %s %s returned %s", method, path, response.status_code)
        error_class = NanoColabUnavailableError if response.status_code >= 500 else NanoColabError
        raise error_class(response.status_code, _detail(response), _retry_after(response))

    def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None, retry: bool
    ) -> Any:
        delays = RETRY_DELAYS if retry else ()
        for delay in delays:
            try:
                return self._once(method, path, json)
            except NanoColabUnavailableError as exc:
                if exc.retry_after is not None or exc.status not in RETRY_STATUS:
                    raise
                time.sleep(delay)
        return self._once(method, path, json)

    def list_images(self) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", "/v1/images", retry=True)
        return result

    def start_asset_upload(self, version: str, size_bytes: int, sha256: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST",
            f"/v1/assets/{version}/uploads",
            json={"size_bytes": size_bytes, "sha256": sha256},
            retry=True,
        )
        return result

    def upload_asset(self, target: dict[str, Any], path: str) -> None:
        url = str(target.get("url") or "")
        if not (
            url.startswith("https://")
            or url.startswith(f"{self.base_url}/")
            or _is_loopback_http(url)
        ):
            raise NanoColabError(502, "Storage upload URL must use HTTPS")
        extra = target.get("headers") or {}
        headers = {str(name): str(value) for name, value in extra.items()}
        if any(name.lower() == "authorization" for name in headers):
            raise NanoColabError(502, "Storage upload URL must not carry credentials")
        headers.setdefault("Content-Type", "application/zip")
        try:
            with open(path, "rb") as body:
                response = requests.put(
                    url,
                    data=body,
                    headers=headers,
                    timeout=self.upload_timeout,
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            logger.warning("Task package upload failed: %s", type(exc).__name__)
            raise NanoColabUnavailableError(503) from None
        if response.status_code >= 400:
            logger.warning("Task package upload returned %s", response.status_code)
            raise NanoColabError(response.status_code)

    def complete_asset_upload(self, version: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("POST", f"/v1/assets/{version}/complete", retry=True)
        return result

    def get_asset(self, version: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request("GET", f"/v1/assets/{version}", retry=True)
        return result

    def put_event(self, external_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "PUT", f"/v1/events/{external_id}", json=payload, retry=True
        )
        return result

    def get_readiness(self, external_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "GET", f"/v1/events/{external_id}/readiness", retry=True
        )
        return result

    def ensure_workspace(self, external_id: str, external_user_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "PUT", f"/v1/events/{external_id}/workspaces/{external_user_id}", retry=True
        )
        return result

    def launch(self, workspace_id: str, external_user_id: str) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/launch",
            json={"external_user_id": external_user_id},
            retry=False,
        )
        return result

    def export(self, workspace_id: str, external_user_id: str, paths: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/export",
            json={"external_user_id": external_user_id, "paths": paths},
            retry=True,
        )
        return result


def _retry_after(response: requests.Response) -> int | None:
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else None


def _detail(response: requests.Response) -> Any:
    try:
        return response.json().get("detail")
    except ValueError:
        return None
