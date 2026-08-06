"""Typed failures raised when an evaluation cannot produce a trustworthy score."""

from __future__ import annotations


class EvaluationError(RuntimeError):
    """Represent a scoring failure that must fail the submission."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
