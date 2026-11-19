"""Challenge model."""

from typing import Any

from models.base import GUID, db, uuid7
from utils.dates import to_tz_iso, utcnow


class Challenge(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "challenges"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    max_eval_requests = db.Column(db.Integer, default=10)
    ram_limit_mb = db.Column(db.Integer, default=8192)
    time_limit_sec = db.Column(db.Integer, default=300)
    gpu_required = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_archived = db.Column(db.Boolean, default=False, index=True)
    scores_finalized = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False)
    double_blind = db.Column(db.Boolean, default=True, nullable=False)
    reveal_results = db.Column(db.Boolean, default=True, nullable=False)
    timezone = db.Column(db.String(50), nullable=False, default="UTC")

    # Creation order (UUIDv7 ids), as on the leaderboard, so every view numbers tasks alike
    tasks = db.relationship(
        "Task",
        backref="challenge",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Task.id",
    )
    submissions = db.relationship(
        "Submission", backref="challenge", lazy=True, cascade="all, delete-orphan"
    )
    stages = db.relationship(
        "Stage",
        backref="challenge",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Stage.stage_number",
    )

    @property
    def is_started(self) -> bool:
        if not self.start_time:
            return False
        return bool(utcnow() >= self.start_time)

    @property
    def is_ended(self) -> bool:
        if not self.end_time:
            return False
        return bool(utcnow() > self.end_time)

    @property
    def computed_status(self) -> str:
        if self.is_archived:
            return "archived"
        if self.scores_finalized:
            return "finalized"
        if not self.is_started:
            return "not_started"
        if self.is_frozen:
            return "frozen"
        if self.is_ended:
            return "ended"
        return "active"

    def task_dicts(self, view_role: str) -> list[dict[str, Any]]:
        from services.task_locks import task_locks

        tasks = list(self.tasks)
        locks = task_locks(tasks, view_role)
        return [t.to_dict(view_role=view_role, locks=locks[str(t.id)]) for t in tasks]

    def to_dict(self, view_role: str = "competitor") -> dict[str, Any]:
        from config import Config

        grace_period = Config.DEADLINE_GRACE_PERIOD_SECONDS

        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "max_eval_requests": self.max_eval_requests,
            "ram_limit_mb": self.ram_limit_mb,
            "time_limit_sec": self.time_limit_sec,
            "gpu_required": self.gpu_required,
            "is_active": self.is_active,
            "is_archived": self.is_archived,
            "scores_finalized": self.scores_finalized,
            "reveal_results": self.reveal_results,
            "start_time": to_tz_iso(self.start_time, self.timezone or "UTC")
            if self.start_time
            else None,
            "end_time": to_tz_iso(self.end_time, self.timezone or "UTC") if self.end_time else None,
            "is_frozen": self.is_frozen,
            "double_blind": self.double_blind,
            "timezone": self.timezone,
            "status": self.computed_status,
            "tasks": self.task_dicts(view_role),
            "stages": [s.to_dict(timezone=self.timezone or "UTC") for s in self.stages],  # type: ignore[attr-defined]
            "num_tasks": len(self.tasks),
            "deadline_grace_period_seconds": grace_period,
            "workspace": self.workspace_dict() if view_role in ("admin", "jury") else None,
            # Every role reads this, so students skip environment requests that would fail
            "workspaces_enabled": bool(Config.NANOCOLAB_API_URL)
            and bool(self.workspace_setting and self.workspace_setting.enabled),
        }

    def workspace_dict(self) -> dict[str, Any] | None:
        """The competition's student workspace setting, or None until one is saved."""
        setting = self.workspace_setting
        if setting is None:
            return None
        archive_until = setting.archive_until
        return {
            "enabled": setting.enabled,
            "auto_publish": setting.auto_publish,
            "image_id": setting.image_id,
            "profile_id": setting.profile_id,
            "cpu_cores": setting.cpu_cores,
            "memory_gib": setting.memory_gib,
            "workspace_gib": setting.workspace_gib,
            "archive_until": to_tz_iso(archive_until, self.timezone or "UTC")
            if archive_until
            else None,
        }
