"""Stage model."""

from typing import Any

from models.base import GUID, db, uuid7


class Stage(db.Model):  # type: ignore[misc, name-defined]
    __tablename__ = "stages"

    __table_args__ = (
        db.UniqueConstraint("challenge_id", "stage_number", name="uq_stage_challenge_number"),
    )

    id = db.Column(GUID, primary_key=True, default=uuid7)
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_number = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(255), nullable=False)

    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)

    is_finalized = db.Column(db.Boolean, default=False, nullable=False)
    reveal_results = db.Column(db.Boolean, default=False, nullable=False)
    is_test = db.Column(db.Boolean, default=False, nullable=False)

    tasks = db.relationship("Task", backref="stage", lazy=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "challenge_id": self.challenge_id,
            "stage_number": self.stage_number,
            "title": self.title,
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
            "is_finalized": self.is_finalized,
            "reveal_results": self.reveal_results,
            "is_test": self.is_test,
        }
