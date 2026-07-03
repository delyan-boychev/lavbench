"""User and JuryChallenge models."""

import contextlib
import json
import logging

from utils.dates import utcnow

from models.base import GUID, db, decrypt_field, encrypt_field, uuid7
from models.naming import generate_pseudonym

logger = logging.getLogger(__name__)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(GUID, primary_key=True, default=uuid7)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=False, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)

    name = db.Column(db.Text, nullable=True)
    surname = db.Column(db.Text, nullable=True)
    middle_name = db.Column(db.Text, nullable=True)
    birth_date = db.Column(db.Text, nullable=True)
    grade = db.Column(db.Text, nullable=True)
    school = db.Column(db.Text, nullable=True)
    city = db.Column(db.Text, nullable=True)

    role = db.Column(db.String(50), default="competitor", index=True)
    alias_id = db.Column(db.String(100), unique=True, nullable=False, default=generate_pseudonym)
    challenge_id = db.Column(GUID, db.ForeignKey("challenges.id"), nullable=True, index=True)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    manual_points = db.Column(db.JSON, default=dict, nullable=False)

    submissions = db.relationship(
        "Submission", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_demographics(
        self, name, surname, grade, school, city, middle_name=None, birth_date=None
    ):
        self.name = encrypt_field(name)
        self.surname = encrypt_field(surname)
        self.middle_name = encrypt_field(middle_name) if middle_name is not None else None
        self.birth_date = encrypt_field(birth_date) if birth_date is not None else None
        self.grade = encrypt_field(grade)
        self.school = encrypt_field(school)
        self.city = encrypt_field(city)

    def to_dict(
        self,
        view_role="competitor",
        scores_finalized=False,
        current_user_id=None,
        challenge_cache=None,
        jury_challenge_map=None,
    ):
        from models.challenge import Challenge

        has_started = False
        challenge_finalized = scores_finalized
        double_blind = True
        challenge_reveal_results = True

        if self.challenge_id:
            challenge = (
                challenge_cache.get(self.challenge_id)
                if challenge_cache
                else db.session.get(Challenge, self.challenge_id)
            )
            if challenge:
                double_blind = challenge.double_blind
                challenge_reveal_results = challenge.reveal_results
                if challenge.start_time:
                    has_started = utcnow() >= challenge.start_time
                if challenge.scores_finalized:
                    challenge_finalized = True

        is_self = current_user_id is not None and current_user_id == self.id

        if double_blind:
            show_details = (
                (view_role == "admin")
                or (view_role == "jury" and (not has_started or challenge_finalized))
                or is_self
                or challenge_finalized
            )
        else:
            show_details = True

        if (
            self.is_anonymous
            and view_role == "competitor"
            and not is_self
            and not challenge_finalized
        ):
            show_details = False

        show_manual_points = True
        if view_role == "competitor" or (is_self and self.role == "competitor"):
            show_manual_points = challenge_finalized and challenge_reveal_results

        manual_pts = {}
        if self.manual_points and show_manual_points:
            if isinstance(self.manual_points, dict):
                manual_pts = self.manual_points
            elif isinstance(self.manual_points, str):
                try:
                    manual_pts = json.loads(self.manual_points)
                except Exception as e:
                    logger.warning("Failed to parse manual_points for user %s: %s", self.id, e)
                    manual_pts = {}

        jury_ch_ids = []
        if self.role == "jury":
            if jury_challenge_map is not None:
                jury_ch_ids = jury_challenge_map.get(self.id, [])
            else:
                with contextlib.suppress(Exception):
                    jury_ch_ids = [
                        str(jc.challenge_id)
                        for jc in JuryChallenge.query.filter_by(jury_id=self.id).all()
                    ]

        if not show_details:
            res = {
                "id": self.id,
                "alias_id": self.alias_id,
                "role": self.role,
                "challenge_id": self.challenge_id,
                "is_anonymous": self.is_anonymous,
            }
            if self.role == "jury":
                res["jury_challenges"] = jury_ch_ids
            return res

        dec_name = decrypt_field(self.name)
        dec_surname = decrypt_field(self.surname)
        dec_middle_name = (
            decrypt_field(self.middle_name) if getattr(self, "middle_name", None) else ""
        )
        dec_birth_date = decrypt_field(self.birth_date) if getattr(self, "birth_date", None) else ""
        dec_grade = decrypt_field(self.grade)
        dec_school = decrypt_field(self.school)
        dec_city = decrypt_field(self.city)

        res = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "name": dec_name,
            "surname": dec_surname,
            "middle_name": dec_middle_name,
            "birth_date": dec_birth_date,
            "grade": dec_grade,
            "school": dec_school,
            "city": dec_city,
            "role": self.role,
            "alias_id": self.alias_id,
            "challenge_id": self.challenge_id,
            "is_anonymous": self.is_anonymous,
            "manual_points": manual_pts,
        }
        if self.role == "jury":
            res["jury_challenges"] = jury_ch_ids
        return res


class JuryChallenge(db.Model):
    __tablename__ = "jury_challenges"

    jury_id = db.Column(GUID, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    challenge_id = db.Column(
        GUID, db.ForeignKey("challenges.id", ondelete="CASCADE"), primary_key=True
    )

    jury = db.relationship(
        "User", backref=db.backref("jury_assignments", cascade="all, delete-orphan")
    )
    challenge = db.relationship(
        "Challenge",
        backref=db.backref("jury_assignments", cascade="all, delete-orphan"),
    )
