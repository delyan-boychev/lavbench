"""Who may see private scores: the one rule every API path applies."""

from __future__ import annotations

from typing import Any


def scores_final(challenge: Any, stage: Any = None) -> bool:
    """Return whether a task's scores are final: its challenge or its stage is finalised."""
    if challenge is not None and challenge.scores_finalized:
        return True
    return bool(stage is not None and stage.is_finalized)


def private_scores_revealed(challenge: Any, stage: Any = None) -> bool:
    """Return whether competitors may see a task's private scores and manual points.

    The reveal flag of whichever level finalised the scores decides: the challenge's
    once the challenge is finalised, otherwise the task's stage's.
    """
    if challenge is not None and challenge.scores_finalized:
        return bool(challenge.reveal_results)
    return bool(stage is not None and stage.is_finalized and stage.reveal_results)


def can_view_private_scores(view_role: str, challenge: Any, stage: Any = None) -> bool:
    """Return whether a viewer may see private scores for a task in this challenge.

    Admins always may. The jury may once the scores are final, so private results
    cannot steer manual points before then. Competitors may once final and revealed.
    """
    if view_role == "admin":
        return True
    if view_role == "jury":
        return scores_final(challenge, stage)
    return private_scores_revealed(challenge, stage)
