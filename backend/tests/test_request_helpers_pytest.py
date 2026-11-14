"""Tests for request helpers: large-upload routes end their DB transaction before the body."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from models import db
from utils.request_helpers import release_db_before_body


def test_release_db_before_body_commits_before_the_view(app_ctx):
    order: list[str] = []

    @release_db_before_body
    def view() -> str:
        order.append("view")
        return "ok"

    with patch.object(db.session, "commit", side_effect=lambda: order.append("commit")):
        assert view() == "ok"
    assert order == ["commit", "view"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/challenges/{challenge_id}/tasks"),
        ("PUT", "/api/tasks/{task_id}"),
        ("POST", "/api/challenges/import"),
        ("POST", "/api/admin/import-competitors-csv"),
    ],
)
def test_upload_routes_end_the_transaction_before_parsing_the_body(
    client, tokens, auth_headers, sample_challenge, sample_task, method, path
):
    url = path.format(challenge_id=sample_challenge.id, task_id=sample_task.id)
    with patch("utils.request_helpers.end_db_transaction") as end:
        client.open(url, method=method, headers=auth_headers(tokens.admin), data={"title": "T"})
    end.assert_called_once_with()


def test_parse_notebook_ends_the_transaction_before_reading_the_upload(
    client, tokens, auth_headers, sample_challenge
):
    with patch("routes.submissions.end_db_transaction") as end:
        res = client.post(
            f"/api/challenges/{sample_challenge.id}/parse-notebook",
            headers=auth_headers(tokens.admin),
            data={},
        )
    assert res.get_json()["code"] == "ERR_NO_FILE_UPLOADED"
    end.assert_called_once_with()
