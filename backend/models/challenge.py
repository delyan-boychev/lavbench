"""Challenge model."""

import zoneinfo
from datetime import datetime
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
    gpu_required = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_archived = db.Column(db.Boolean, default=False, index=True)
    scores_finalized = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_frozen = db.Column(db.Boolean, default=False, nullable=False)
    double_blind = db.Column(db.Boolean, default=True, nullable=False)
    reveal_results = db.Column(db.Boolean, default=True, nullable=False)
    timezone = db.Column(db.String(50), nullable=False, default="UTC")

    tasks = db.relationship("Task", backref="challenge", lazy=True, cascade="all, delete-orphan")
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

    def _now_local(self) -> datetime:
        try:
            tz = zoneinfo.ZoneInfo(self.timezone or "UTC")
            return datetime.now(tz).replace(tzinfo=None)
        except Exception:
            return utcnow()

    @property
    def is_started(self) -> bool:
        if not self.start_time:
            return False
        return bool(self._now_local() >= self.start_time)

    @property
    def is_ended(self) -> bool:
        if not self.end_time:
            return False
        return bool(self._now_local() > self.end_time)

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

    def to_dict(self, view_role: str = "competitor") -> dict[str, Any]:
        try:
            from flask import current_app

            grace_period = current_app.config.get("DEADLINE_GRACE_PERIOD_SECONDS", 60)
        except Exception:
            grace_period = 60

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
            "tasks": [t.to_dict(view_role=view_role) for t in self.tasks],  # type: ignore[attr-defined]
            "stages": [s.to_dict(timezone=self.timezone or "UTC") for s in self.stages],  # type: ignore[attr-defined]
            "num_tasks": len(self.tasks),
            "deadline_grace_period_seconds": grace_period,
        }
