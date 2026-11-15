"""Regression tests for bounded submission request and code storage sizes."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config import Config
from models import Submission
from schemas.submission import SelectedCellsSchema


def test_selected_cells_rejects_excessive_cell_count() -> None:
    cells = [{"source": "print(1)"} for _ in range(Config.MAX_SELECTED_CELLS + 1)]

    with pytest.raises(ValidationError, match="at most"):
        SelectedCellsSchema(selected_cells=cells)


def test_selected_cells_rejects_oversized_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "MAX_CODE_CELL_CHARS", 8)

    with pytest.raises(ValidationError, match="single cell"):
        SelectedCellsSchema(selected_cells=[{"source": "x" * 9}])


def test_submission_model_rejects_oversized_serialized_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Config, "MAX_CODE_CELLS_CHARS", 8)
    submission = Submission()

    with pytest.raises(ValueError, match="maximum is 8"):
        submission.code_cells = json.dumps([{"source": "too large"}])


def test_submission_endpoint_rejects_body_before_authentication(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Config, "MAX_SUBMISSION_REQUEST_BYTES", 32)

    response = client.post(
        "/api/tasks/00000000-0000-0000-0000-000000000001/submit",
        json={"selected_cells": [{"source": "x" * 64}]},
    )

    assert response.status_code == 413
    assert response.get_json()["code"] == "ERR_PAYLOAD_TOO_LARGE"
