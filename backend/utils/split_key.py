"""Per-task evaluation split keys, importable without loading the evaluation engine.

The web process derives a key for every submission; importing it from
``services.evaluation`` would load pandas, numpy and scikit-learn into every web
worker.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any


def derive_task_split_key(secret: str, task_id: Any) -> str:
    """Derive a task-scoped key without disclosing the root split secret."""
    if not secret:
        # Misconfiguration only: the engine import is acceptable on this path
        from services.evaluation.exceptions import EvaluationError

        raise EvaluationError(
            "EVALUATION_SPLIT_SECRET_MISSING",
            "Evaluation split secret is not configured.",
        )
    return hmac.new(secret.encode(), str(task_id).encode(), hashlib.sha256).hexdigest()
