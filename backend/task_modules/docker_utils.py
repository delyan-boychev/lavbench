"""Shared Docker SDK wrapper — replaces subprocess calls to the docker CLI.

Provides a lazily-initialized client and helper functions so all callers
use the same ``docker.from_env()`` instance.
"""

import logging

import docker
from docker.errors import DockerException, ImageNotFound

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
        except DockerException as e:
            logger.warning("Failed to create Docker client: %s", e)
            raise
    return _client


def check_docker_available():
    """Return ``True`` if the Docker daemon is reachable."""
    try:
        return _get_client().ping()
    except Exception:
        return False


def image_exists(tag):
    """Return ``True`` if a Docker image with *tag* exists locally."""
    try:
        _get_client().images.get(tag)
        return True
    except ImageNotFound:
        return False
    except Exception:
        return False


def prune_images():
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
