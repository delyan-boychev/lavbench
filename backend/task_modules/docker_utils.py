"""Shared Docker SDK wrapper — replaces subprocess calls to the docker CLI.

Provides a lazily-initialized client and helper functions so all callers
use the same ``docker.from_env()`` instance.
"""

from __future__ import annotations

import logging

import docker  # type: ignore[import-untyped]
from docker import DockerClient
from docker.errors import DockerException, ImageNotFound  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_client: DockerClient | None = None


def _get_client() -> DockerClient:
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
        except DockerException as e:
            logger.warning("Failed to create Docker client: %s", e)
            raise
    return _client


def check_docker_available() -> bool:
    """Return ``True`` if the Docker daemon is reachable."""
    try:
        result: bool = _get_client().ping()
        return result
    except Exception:
        return False


def image_exists(tag: str) -> bool:
    """Return ``True`` if a Docker image with *tag* exists locally."""
    try:
        _get_client().images.get(tag)
        return True
    except ImageNotFound:
        return False
    except Exception:
        return False


def prune_images() -> dict[str, str]:
    """Prune unused Docker images and return a status dict."""
    try:
        result = _get_client().images.prune()
        output = (
            f"Reclaimed: {result.get('SpaceReclaimed', 0)} bytes, "
            f"deleted: {len(result.get('ImagesDeleted', []))} images"
        )
        logger.info("Docker image prune succeeded: %s", output)
        return {"status": "success", "output": output}
    except Exception as e:
        logger.exception("Docker image prune failed: %s", e)
        return {"status": "failed", "error": str(e)}
