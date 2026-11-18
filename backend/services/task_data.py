"""Task data on the web host: streamed data files and the shared Hugging Face ZIP store."""

from __future__ import annotations

import contextlib
import logging
import os

from models import Task
from services import hf_zip
from utils.uploads import store_lock

logger = logging.getLogger(__name__)

HF_STORE_LOCK = "hf"


def hf_zip_referenced(sha256: str) -> bool:
    return Task.query.filter_by(hf_zip_sha256=sha256).first() is not None


def remove_hf_zip_if_unreferenced(sha256: str) -> None:
    """Delete a stored ZIP no task uses; call while holding the HF store lock."""
    if hf_zip_referenced(sha256):
        return
    with contextlib.suppress(OSError):
        os.remove(hf_zip.hf_zip_path(sha256))


def remove_unreferenced_hf_zip(sha256: str) -> None:
    """Take the HF store lock, then delete the ZIP if no task references it any more."""
    with store_lock(HF_STORE_LOCK) as got:
        if not got:
            logger.warning("HF store busy; %s.zip stays until the next removal", sha256)
            return
        remove_hf_zip_if_unreferenced(sha256)
