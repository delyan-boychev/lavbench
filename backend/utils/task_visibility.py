"""Which tasks of a competition a competitor may see: the one rule every competitor view uses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from utils.dates import utcnow
from utils.files import task_file_visibility


def competitor_visible_tasks(challenge: Any, now: datetime | None = None) -> list[Any]:
    """The tasks a registered competitor may see now, in the competition's task order.

    Before the start only a running test stage's tasks are shown. After it, a competition
    with regular stages shows the tasks of the stages that have started; one without
    stages shows every task.
    """
    now = now or utcnow()
    stages = list(challenge.stages)
    if challenge.start_time and now < challenge.start_time:
        running_test = {s.id for s in stages if s.is_test and s.start_time <= now <= s.end_time}
        return [t for t in challenge.tasks if t.stage_id in running_test]

    regular = [s for s in stages if not s.is_test]
    if not regular:
        return list(challenge.tasks)
    started = {s.id for s in regular if s.start_time and s.start_time <= now}
    return [t for t in challenge.tasks if t.stage_id in started]


def filter_challenge_for_competitor(challenge: Any) -> dict[str, Any]:
    """The competition as a competitor sees it: visible tasks only, public files only."""
    now = utcnow()
    challenge_dict: dict[str, Any] = challenge.to_dict()
    visible = {str(t.id) for t in competitor_visible_tasks(challenge, now)}
    tasks = []
    for t in challenge_dict.get("tasks", []):
        if str(t.get("id")) not in visible:
            continue
        # Hidden files never reach competitors
        if t.get("files"):
            t["files"] = [f for f in t["files"] if task_file_visibility(f) == "public"]
        tasks.append(t)
    challenge_dict["tasks"] = tasks
    if challenge.start_time and now < challenge.start_time:
        challenge_dict["stages"] = []
    return challenge_dict
