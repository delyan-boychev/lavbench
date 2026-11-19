"""Request parsing helpers for route handlers."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, cast


def end_db_transaction() -> None:
    """End the request's open transaction so a slow request body never holds it.

    The web process aborts transactions idle for PG_IDLE_IN_TRANSACTION_TIMEOUT_MS;
    the auth checks open one, and reading a large upload can outlast that limit.
    """
    from models import db

    db.session.commit()


def release_db_before_body[T: Callable[..., Any]](f: T) -> T:
    """Call :func:`end_db_transaction` before the wrapped view reads the body.

    Place it below the auth decorators and above ``@api.validate``, which parses
    form bodies before the handler runs.
    """

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        end_db_transaction()
        return f(*args, **kwargs)

    return cast(T, wrapper)
