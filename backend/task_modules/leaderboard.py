"""Celery task for asynchronous leaderboard recalculation."""

from models import Challenge
from services.leaderboard_service import build_and_cache_leaderboard


def run_recalculate_all_leaderboards(app):

    with app.app_context():
        # Get active or recent challenges
        active_challenges = Challenge.query.filter_by(is_archived=False).all()
        for challenge in active_challenges:
            # Rebuild both frozen and unfrozen versions to keep both warm!
            build_and_cache_leaderboard(challenge.id, is_frozen_view=False)
            if challenge.is_frozen:
                build_and_cache_leaderboard(challenge.id, is_frozen_view=True)
