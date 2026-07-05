"""AuditLog model."""

from models.base import GUID, db, uuid7
from utils.dates import utcnow


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    admin_id = db.Column(GUID, db.ForeignKey("users.id"), nullable=False, index=True)

    action_type = db.Column(db.String(50), nullable=True, index=True)
    target_type = db.Column(db.String(50), nullable=True, index=True)
    target_id = db.Column(GUID, nullable=True, index=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    target_user_id = db.Column(GUID, db.ForeignKey("users.id"), nullable=True, index=True)
    task_id = db.Column(GUID, db.ForeignKey("tasks.id"), nullable=True, index=True)
    old_score = db.Column(db.Integer, nullable=True)
    new_score = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.Text, nullable=True)

    timestamp = db.Column(db.DateTime, default=lambda: utcnow(), index=True)

    admin = db.relationship("User", foreign_keys=[admin_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])
    task = db.relationship("Task")

    def to_dict(self):
        result = {
            "id": self.id,
            "admin_id": self.admin_id,
            "admin_username": self.admin.username if self.admin else None,
            "action_type": self.action_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "timestamp": self.timestamp.isoformat() + "Z" if self.timestamp else None,
        }
        if self.target_user_id is not None:
            result["target_user_id"] = self.target_user_id
            result["target_user_username"] = self.target_user.username if self.target_user else None
        if self.task_id is not None:
            result["task_id"] = self.task_id
            result["task_title"] = self.task.title if self.task else None
        if self.old_score is not None or self.new_score is not None:
            result["old_score"] = self.old_score
            result["new_score"] = self.new_score
        if self.reason:
            result["reason"] = self.reason
        return result
