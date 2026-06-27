def invalidate_entity_cache(challenge_id=None, leaderboard_delete_only=False):
    if challenge_id is not None:
        from cache_utils import invalidate_challenge_cache, invalidate_leaderboard_cache

        invalidate_challenge_cache(challenge_id)
        invalidate_leaderboard_cache(challenge_id, delete_only=leaderboard_delete_only)
