"""Challenge model."""

import zoneinfo
from datetime import datetime

from models.base import GUID, db, uuid7
from utils.dates import utcnow


class Challenge(db.Model):
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

    def _now_local(self):
        try:
            tz = zoneinfo.ZoneInfo(self.timezone or "UTC")
            return datetime.now(tz).replace(tzinfo=None)
        except Exception:
            return utcnow()

    @property
    def is_started(self):
        if not self.start_time:
            return False
        return self._now_local() >= self.start_time

    @property
    def is_ended(self):
        if not self.end_time:
            return False
        return self._now_local() > self.end_time

    @property
    def computed_status(self):
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

    def to_dict(self):
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
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "is_frozen": self.is_frozen,
            "double_blind": self.double_blind,
            "timezone": self.timezone,
            "status": self.computed_status,
            "tasks": [t.to_dict() for t in self.tasks],
            "stages": [s.to_dict() for s in self.stages],
            "num_tasks": len(self.tasks),
            "deadline_grace_period_seconds": grace_period,
        }
