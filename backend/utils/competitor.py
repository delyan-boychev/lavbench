from __future__ import annotations

from collections.abc import Callable
from typing import Any


def norm(s: str | None) -> str:
    return s.strip().lower() if s else ""


def demographics_tuple(
    user_or_dict: Any, decrypt_field: Callable[[str], str] | None = None
) -> tuple[str, ...]:
    """Build a normalized 7-field demographics tuple from a User or dict with decrypt support."""
    if hasattr(user_or_dict, "name"):
        fields = ["name", "middle_name", "surname", "birth_date", "grade", "school", "city"]
        values = []
        for f in fields:
            raw = getattr(user_or_dict, f, None)
            if decrypt_field:
                raw = decrypt_field(raw) if raw else raw
            values.append(norm(raw))
        return tuple(values)
    return tuple(
        norm(user_or_dict.get(k, ""))
        for k in ["name", "middle_name", "surname", "birth_date", "grade", "school", "city"]
    )


def check_duplicate_demographics(
    existing_users: list[Any],
    name: str,
    middle_name: str,
    surname: str,
    birth_date: str,
    grade: str,
    school: str,
    city: str,
    decrypt_field_fn: Callable[[str], str] | None = None,
    exclude_id: str | None = None,
) -> bool:
    target = demographics_tuple(
        {
            "name": name,
            "middle_name": middle_name,
            "surname": surname,
            "birth_date": birth_date,
            "grade": grade,
            "school": school,
            "city": city,
        }
    )
    for c in existing_users:
        if exclude_id is not None and c.id == exclude_id:
            continue
        if demographics_tuple(c, decrypt_field=decrypt_field_fn) == target:
            return True
    return False
