from __future__ import annotations


def invalidate_entity_cache(
    challenge_id: str | None = None, leaderboard_delete_only: bool = False
) -> None:
    if challenge_id is not None:
        from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

        invalidate_challenge_cache(challenge_id)
        invalidate_leaderboard_cache(challenge_id, delete_only=leaderboard_delete_only)
