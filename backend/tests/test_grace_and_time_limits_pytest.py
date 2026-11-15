"""Tests for the grace period default and the Celery and task time-limit bounds (R3, R65)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Config
from schemas.challenge import CreateChallengeSchema
from schemas.task import CreateTaskMetaSchema


def test_grace_period_default_is_three_minutes():
    assert Config.DEADLINE_GRACE_PERIOD_SECONDS == 180


def test_challenge_payload_reports_the_configured_grace(sample_challenge):
    assert sample_challenge.to_dict()["deadline_grace_period_seconds"] == (
        Config.DEADLINE_GRACE_PERIOD_SECONDS
    )


def test_celery_limits_bound_the_task_time_limit():
    from tasks import evaluate_submission

    assert evaluate_submission.soft_time_limit == Config.CELERY_TASK_SOFT_TIME_LIMIT
    assert evaluate_submission.time_limit == Config.CELERY_TASK_TIME_LIMIT
    assert Config.CELERY_TASK_TIME_LIMIT > Config.CELERY_TASK_SOFT_TIME_LIMIT
    assert Config.MAX_TASK_TIME_LIMIT_SEC == Config.CELERY_TASK_SOFT_TIME_LIMIT - 60


def test_task_time_limit_above_the_bound_is_rejected():
    CreateTaskMetaSchema(title="t", time_limit_sec=Config.MAX_TASK_TIME_LIMIT_SEC)
    with pytest.raises(ValidationError):
        CreateTaskMetaSchema(title="t", time_limit_sec=Config.MAX_TASK_TIME_LIMIT_SEC + 1)


def test_challenge_time_limit_above_the_bound_is_rejected():
    base = {"title": "c", "start_time": "2027-01-01T00:00:00Z", "end_time": "2027-01-02T00:00:00Z"}
    CreateChallengeSchema(**base, time_limit_sec=Config.MAX_TASK_TIME_LIMIT_SEC)
    with pytest.raises(ValidationError):
        CreateChallengeSchema(**base, time_limit_sec=Config.MAX_TASK_TIME_LIMIT_SEC + 1)
