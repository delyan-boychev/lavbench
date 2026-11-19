"""Route handlers for the submissions blueprint."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from collections.abc import Generator
from typing import Any

from flask import Blueprint, request
from flask import Response as FlaskResponse
from spectree import Response
from sqlalchemy.orm import joinedload

from config import Config
from models import Challenge, Submission, Task, User, db, decrypt_field
from schemas.responses import (
    BestSubmissionsResponse,
    ErrorResponse,
    MessageResponse,
    ParseNotebookResponse,
    SelectFinalResponse,
    SubmissionLightResponse,
    SubmissionResponse,
    SubmissionsListResponse,
)
from services.baseline_service import apply_baseline_outcome
from services.contest_rules import counted_run, is_submission_eligible, selection_window
from services.file_validation import validate_extension, validate_notebook_content
from services.submission_status import (
    ACTIVE_STATUSES,
    COMPLETED,
    FAILED,
    KILLED,
    TERMINAL_STATUSES,
    select_final,
    transition,
)
from utils.access import competitor_submissions_locked
from utils.auth_utils import jury_access_required, login_required, rate_limit, role_required
from utils.cache_utils import (
    get_redis_client,
    invalidate_leaderboard_cache,
    mark_attempt_ended,
    submission_logs_key,
)
from utils.dates import utcnow
from utils.error_utils import err, format_size
from utils.ipynb import (
    cells_to_ipynb_json,
    notebook_cells,
    sanitize_filename_part,
    wrap_raw_code_cells,
)
from utils.pagination import extract_pagination
from utils.request_helpers import end_db_transaction
from utils.spec import api
from utils.sse import (
    SSE_SOCKET_LIMIT_PAYLOAD,
    close_pubsub,
    jittered_idle_timeout,
    sse_data,
    sse_response,
    sse_retry_field,
    subscribe_channel,
)
from utils.sse_utils import (
    clear_submission_logs,
    get_submission_final_status,
    publish_queue_update,
    publish_submission_status,
    sse_connection_limit,
    sse_heartbeat,
    submission_logs_channel,
)
from utils.streaming import stream_file_response
from utils.task_visibility import filter_challenge_for_competitor

logger = logging.getLogger(__name__)


submissions_bp = Blueprint("submissions", __name__)


@submissions_bp.route("/challenges/<uuid:challenge_id>/parse-notebook", methods=["POST"])
@login_required
@jury_access_required
@rate_limit(max_requests=30, window_seconds=60)
@api.validate(
    tags=["Submissions"], resp=Response(HTTP_200=ParseNotebookResponse, HTTP_422=ErrorResponse)
)
def parse_notebook(challenge_id: Any) -> ParseNotebookResponse | tuple[FlaskResponse, int]:
    """Upload and parse a Jupyter Notebook (.ipynb) to preview cells."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

    # Reading the upload can be slow; do it outside a transaction
    end_db_transaction()
    if "file" not in request.files:
        return err("ERR_NO_FILE_UPLOADED", 400)
    file = request.files["file"]

    valid_ext, ext_err = validate_extension(file.filename, {".ipynb"})
    if not valid_ext:
        return err("ERR_INVALID_FILE_TYPE", 400, message=ext_err)

    # Read at most the limit plus one byte, so an oversized upload never fills memory
    limit = Config.MAX_NOTEBOOK_BYTES
    content = file.read(limit + 1)
    if len(content) > limit:
        return err(
            "ERR_FILE_TOO_LARGE",
            413,
            message=f"The notebook exceeds the {format_size(limit)} limit.",
            limit=format_size(limit),
        )

    valid_content, content_err, notebook = validate_notebook_content(content)
    if not valid_content:
        return err("ERR_PARSING_FAILED", 400, message=f"Invalid notebook file: {content_err}")

    return ParseNotebookResponse(filename=file.filename, cells=notebook_cells(notebook))


@submissions_bp.route("/challenges/<uuid:challenge_id>/submissions", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=SubmissionsListResponse, HTTP_403=ErrorResponse),
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
)
def get_submissions(challenge_id: Any) -> dict[str, Any] | tuple[FlaskResponse, int]:
    """Get paginated submissions for a challenge."""
    challenge = db.get_or_404(Challenge, challenge_id)
    user_role = request.user["role"]
    user_id = request.user["user_id"]

    page, per_page = extract_pagination(request, default_per_page=50, max_per_page=200)

    # Restrict competitors to their registered challenge
    if user_role == "competitor":
        from utils.access import ensure_registered

        if not ensure_registered(user_id, challenge_id):
            return err("ERR_NOT_REGISTERED", 403)

        if competitor_submissions_locked(challenge):
            return err("ERR_SUBMISSIONS_LOCKED", 403)

        query = Submission.query.filter_by(challenge_id=challenge_id, user_id=user_id).options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )
    else:
        query = Submission.query.filter_by(challenge_id=challenge_id, is_baseline=False).options(
            joinedload(Submission.challenge),
            joinedload(Submission.user),
            joinedload(Submission.task),
        )

    pagination = query.order_by(Submission.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return {
        "submissions": [
            s.to_dict_light(view_role=user_role, current_user_id=user_id) for s in pagination.items
        ],
        "per_page": pagination.per_page,
        # Competitors get only the tasks they may already see, as on the competition page
        "challenge": filter_challenge_for_competitor(challenge)
        if user_role == "competitor"
        else challenge.to_dict(),
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
    }


@submissions_bp.route(
    "/challenges/<uuid:challenge_id>/users/<uuid:user_id>/best-submissions", methods=["GET"]
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(
        HTTP_200=BestSubmissionsResponse,
        HTTP_403=ErrorResponse,
        HTTP_404=ErrorResponse,
    ),
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
)
def get_user_best_submissions(
    challenge_id: Any, user_id: Any
) -> BestSubmissionsResponse | tuple[FlaskResponse, int]:
    """Get the canonical best submission for each challenge task."""
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return err("ERR_CHALLENGE_NOT_FOUND", 404)

    competitor = db.session.get(User, user_id)
    if not competitor or competitor.role != "competitor" or competitor.challenge_id != challenge.id:
        return err("ERR_USER_NOT_FOUND", 404)

    submissions = (
        Submission.query.filter_by(
            challenge_id=challenge.id,
            user_id=competitor.id,
            status=COMPLETED,
            is_baseline=False,
        )
        .options(
            joinedload(Submission.challenge),
            joinedload(Submission.task),
            joinedload(Submission.user),
        )
        .all()
    )
    submissions_by_task: dict[Any, list[Submission]] = {}
    for submission in submissions:
        submissions_by_task.setdefault(submission.task_id, []).append(submission)

    items: list[SubmissionLightResponse] = []
    for task in challenge.tasks:
        best = counted_run(task, submissions_by_task.get(task.id, []), challenge)
        if best:
            items.append(
                SubmissionLightResponse(
                    **best.to_dict_light(
                        view_role=request.user["role"], current_user_id=request.user["user_id"]
                    )
                )
            )

    return BestSubmissionsResponse(items=items)


@submissions_bp.route("/submissions/<uuid:submission_id>", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=SubmissionResponse, HTTP_422=ErrorResponse),
)
def get_submission_detail(submission_id: Any) -> SubmissionResponse | tuple[FlaskResponse, int]:
    """Get details of a specific submission."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.get_or_404(Submission, submission_id)

    if user_role == "competitor":
        if submission.user_id != user_id:
            return err("ERR_NOT_FOUND", 404)

        if competitor_submissions_locked(db.session.get(Challenge, submission.challenge_id)):
            return err("ERR_SUBMISSIONS_LOCKED", 403)

    return SubmissionResponse(**submission.to_dict(view_role=user_role, current_user_id=user_id))


@submissions_bp.route("/submissions/<uuid:submission_id>/select-final", methods=["POST"])
@login_required
# Only the competitor chooses their final submission; staff never change it
@role_required(["competitor"])
@rate_limit(max_requests=20, window_seconds=60)
@api.validate(
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
    resp=Response(HTTP_200=SelectFinalResponse, HTTP_422=ErrorResponse),
)
def select_final_submission(submission_id: Any) -> SelectFinalResponse | tuple[FlaskResponse, int]:
    """Select one of the competitor's own completed runs as their final submission."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.get_or_404(Submission, submission_id)
    if submission.user_id != user_id:
        return err("ERR_NOT_FOUND", 404)
    if submission.status != COMPLETED or submission.is_baseline:
        return err("ERR_SUBMISSION_NOT_SELECTABLE", 400)

    challenge = db.session.get(Challenge, submission.challenge_id)
    task = db.session.get(Task, submission.task_id)
    if challenge is None or task is None:
        return err("ERR_NOT_FOUND", 404)
    if challenge.scores_finalized:
        return err("ERR_COMPETITION_FINALIZED", 403)
    stage = task.stage if task.stage_id else None
    if stage is not None and stage.is_finalized:
        return err("ERR_SELECTION_WINDOW_CLOSED", 400)
    if not is_submission_eligible(submission, task, challenge):
        return err("ERR_SUBMISSION_LATE", 400)
    if not selection_window(user_id, task, challenge).open:
        return err("ERR_SELECTION_WINDOW_CLOSED", 400)

    if not select_final(submission.id, submission.user_id, submission.task_id):
        db.session.rollback()
        return err("ERR_SUBMISSION_NOT_SELECTABLE", 400)
    db.session.commit()

    # The leaderboard beat task rebuilds and signals live viewers
    invalidate_leaderboard_cache(submission.challenge_id)

    return SelectFinalResponse(
        message="Submission selected as final.",
        submission=SubmissionResponse(
            **submission.to_dict(view_role=user_role, current_user_id=user_id)
        ),
    )


@submissions_bp.route("/submissions/<uuid:submission_id>/kill", methods=["POST"])
@login_required
@jury_access_required
@api.validate(
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
    resp=Response(
        HTTP_200=MessageResponse,
        HTTP_400=ErrorResponse,
        HTTP_403=ErrorResponse,
        HTTP_404=ErrorResponse,
    ),
)
def kill_submission(submission_id: Any) -> MessageResponse | tuple[FlaskResponse, int]:
    """Kill a queued or running submission. Admins/jury can kill any;
    competitors can only kill their own."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.session.get(Submission, submission_id)
    if not submission:
        return err("ERR_NOT_FOUND", 404)

    if user_role == "competitor":
        if submission.user_id != user_id:
            return err("ERR_SUBMISSION_KILL_DENIED", 403)
    elif user_role not in ("admin", "jury"):
        return err("ERR_SUBMISSION_KILL_DENIED", 403)

    if submission.status not in ACTIVE_STATUSES:
        return err("ERR_SUBMISSION_NOT_KILLABLE", 400)
    # The run may have ended since it was read; a completed run is never overwritten
    if not transition(submission.id, FAILED, from_statuses=ACTIVE_STATUSES, detailed_status=KILLED):
        db.session.rollback()
        return err("ERR_SUBMISSION_NOT_KILLABLE", 400)

    log_line = f"[{utcnow().isoformat()}] Submission killed by {user_role} ({user_id})"
    existing_logs = submission.logs or ""
    submission.logs = f"{existing_logs}\n{log_line}".strip()

    db.session.commit()
    if submission.celery_task_id:
        with contextlib.suppress(Exception):
            from tasks import celery

            celery.control.revoke(submission.celery_task_id, terminate=True)
    # The worker removes the sandbox of an ended attempt within a minute
    mark_attempt_ended(submission.celery_task_id)
    # A killed baseline blocks its task until a new baseline completes
    apply_baseline_outcome(submission)

    publish_queue_update()
    publish_submission_status(submission.id, FAILED)
    clear_submission_logs(submission.id)

    return MessageResponse(message="Submission killed successfully.")


_LOG_MESSAGE_WAIT_SECONDS = 2.0
_LOG_STATUS_CHECK_SECONDS = 10.0


def _log_replay(submission: Submission) -> list[str]:
    """Return the lines a new log stream replays: the live Redis list, else stored logs."""
    cache_r = get_redis_client()
    if cache_r:
        try:
            cached = cache_r.lrange(submission_logs_key(submission.id), 0, -1)
        except Exception as e:
            logger.warning("Failed to read live logs for submission %s: %s", submission.id, e)
            cached = None
        if cached:
            return [
                line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
                for line in cached
            ]
    return (submission.logs or "").splitlines()


def _relay_log_message(raw: Any) -> tuple[list[str], bool]:
    """Turn one pub/sub message into SSE events; True when it carries a final status."""
    data_str = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    try:
        parsed: Any = json.loads(data_str)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("logs"), list):
        return [sse_data({"log": line}) for line in parsed["logs"]], False
    finished = isinstance(parsed, dict) and parsed.get("status") in TERMINAL_STATUSES
    return [f"data: {data_str}\n\n"], finished


def _follow_live_logs(
    pubsub: Any | None, submission_id: Any, member: str, user_id: Any
) -> Generator[str, None, None]:
    """Relay published log lines until a final status, the idle timeout or eviction.

    Queued messages are relayed before the stored final status is consulted, so the
    last lines before the end are never dropped. The caller owns ``pubsub``.
    """
    deadline = time.monotonic() + jittered_idle_timeout()
    # The first idle moment checks the stored final status: a stream that subscribed
    # After the final publish ends there
    next_status_check = time.monotonic()
    try:
        while True:
            if time.monotonic() >= deadline:
                yield sse_data({"event": "timeout"})
                return
            if member and not sse_heartbeat(member, user_id):
                yield sse_data({"event": "evicted"})
                return
            message = None
            if pubsub is None:
                time.sleep(_LOG_MESSAGE_WAIT_SECONDS)
            else:
                message = pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_LOG_MESSAGE_WAIT_SECONDS
                )
            if message:
                events, finished = _relay_log_message(message["data"])
                yield from events
                if finished:
                    return
                continue
            if time.monotonic() >= next_status_check:
                next_status_check = time.monotonic() + _LOG_STATUS_CHECK_SECONDS
                final_status = get_submission_final_status(submission_id)
                if final_status:
                    yield sse_data({"status": final_status})
                    return
            yield ": keep-alive\n\n"
    except Exception as e:
        logger.warning("SSE log stream for submission %s ended: %s", submission_id, e)


@submissions_bp.route("/submissions/<uuid:submission_id>/logs/live", methods=["GET"])
@login_required
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
)
def stream_submission_logs(
    submission_id: Any,
) -> tuple[FlaskResponse, int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Stream live logs for a submission using Server-Sent Events (SSE)."""
    user_id = request.user["user_id"]
    user_role = request.user["role"]

    submission = db.session.get(Submission, submission_id)
    if not submission:
        return err("ERR_NOT_FOUND", 404)

    if user_role == "competitor":
        if submission.user_id != user_id:
            return err("ERR_ACCESS_DENIED", 403)

        if competitor_submissions_locked(db.session.get(Challenge, submission.challenge_id)):
            return err("ERR_SUBMISSIONS_LOCKED", 403)

    # Everything the stream needs is read now: the session is released before
    # Streaming and the generator never queries the database
    initial_status = submission.status
    pubsub = None
    if initial_status not in TERMINAL_STATUSES:
        # Subscribe before reading the replay, so a line published in between still
        # Arrives; one published right between the two calls may appear twice
        pubsub = subscribe_channel(submission_logs_channel(submission_id))
    try:
        replay = _log_replay(submission)
    except Exception:
        close_pubsub(pubsub)
        raise

    def event_generator():
        try:
            with sse_connection_limit(user_id=user_id) as (allowed, member):
                if not allowed:
                    yield sse_data(SSE_SOCKET_LIMIT_PAYLOAD)
                    return
                yield sse_retry_field()
                yield sse_data({"info": "connected"})
                for line in replay:
                    yield sse_data({"log": line})
                if initial_status in TERMINAL_STATUSES:
                    yield sse_data({"status": initial_status})
                    return
                yield from _follow_live_logs(pubsub, submission_id, member, user_id)
        finally:
            close_pubsub(pubsub)

    # Also closed when the client leaves before the generator ever starts
    return sse_response(event_generator, on_close=lambda: close_pubsub(pubsub))


def _owner_label(user: User, challenge: Challenge, view_role: str) -> str:
    """The name in a download's file name: the alias while the jury judges double-blind."""
    if challenge.double_blind and view_role != "admin" and not challenge.scores_finalized:
        return sanitize_filename_part(str(user.alias_id))
    name = decrypt_field(user.name) or ""
    surname = decrypt_field(user.surname) or ""
    return sanitize_filename_part(f"{name}_{surname}_{user.alias_id}")


SUBMISSION_FILE_KINDS = {
    "parquet": ("artifact_path", "artifact_sha256", "parquet", "application/octet-stream"),
    "notebook": ("notebook_path", "notebook_sha256", "ipynb", "application/x-ipynb+json"),
}


@submissions_bp.route("/submissions/<uuid:submission_id>/files/<string:kind>", methods=["GET"])
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_403=ErrorResponse, HTTP_404=ErrorResponse),
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
)
def download_submission_file(
    submission_id: Any, kind: str
) -> tuple[Generator[bytes, None, None], int, dict[str, str]] | tuple[FlaskResponse, int]:
    """Download the Parquet or the notebook of a file-task submission."""
    submission = db.get_or_404(Submission, submission_id)
    if kind not in SUBMISSION_FILE_KINDS:
        return err("ERR_NOT_FOUND", 404)
    path_attr, sha_attr, extension, mimetype = SUBMISSION_FILE_KINDS[kind]
    path = getattr(submission, path_attr)
    if not path or not os.path.isfile(path):
        return err("ERR_FILE_NOT_FOUND", 404)
    owner = (
        "baseline"
        if submission.is_baseline or submission.user is None
        else _owner_label(submission.user, submission.challenge, request.user["role"])
    )
    task_part = sanitize_filename_part(submission.task.folder_name or submission.task.title)
    filename = f"{owner}_{task_part}_sub_{submission.id}.{extension}"
    return stream_file_response(path, mimetype, filename, sha256=getattr(submission, sha_attr))


@submissions_bp.route(
    "/challenges/<uuid:challenge_id>/tasks/<uuid:task_id>/users/<uuid:user_id>/download",
    methods=["GET"],
)
@role_required(["admin", "jury"])
@jury_access_required
@api.validate(
    resp=Response(HTTP_200=None, HTTP_404=ErrorResponse),
    tags=["Submissions"],
    security=[{"cookieAuth": []}],
)
def download_competitor_submission(
    challenge_id: Any, task_id: Any, user_id: Any
) -> (
    tuple[bytes, int, dict[str, str]]
    | tuple[Generator[bytes, None, None], int, dict[str, str]]
    | tuple[FlaskResponse, int]
):
    """Download a competitor's final selection or highest-scoring submission."""
    user = db.session.get(User, user_id)
    task = db.session.get(Task, task_id)
    challenge = db.session.get(Challenge, challenge_id)

    if (
        user is None
        or task is None
        or challenge is None
        or str(user.challenge_id) != str(challenge_id)
        or str(task.challenge_id) != str(challenge_id)
    ):
        return err("ERR_NOT_FOUND", 404)

    subs = Submission.query.filter_by(
        challenge_id=challenge_id,
        task_id=task_id,
        user_id=user_id,
        status=COMPLETED,
    ).all()

    best_sub = counted_run(task, subs, challenge)

    if not best_sub:
        return err("ERR_NO_COMPLETED_SUBMISSIONS", 404)

    comp_name = _owner_label(user, challenge, request.user["role"])
    task_title = sanitize_filename_part(task.title)

    filename = f"{comp_name}_{task_title}_sub_{best_sub.id}.ipynb"
    if best_sub.notebook_path:
        if not os.path.isfile(best_sub.notebook_path):
            return err("ERR_FILE_NOT_FOUND", 404)
        return stream_file_response(
            best_sub.notebook_path,
            "application/x-ipynb+json",
            filename,
            sha256=best_sub.notebook_sha256,
        )

    if best_sub.code_storage_path and os.path.exists(best_sub.code_storage_path):
        file_size = os.path.getsize(best_sub.code_storage_path)
        logger.info("Download submission %s code_cells file size: %d bytes", best_sub.id, file_size)

    notebook_bytes = wrap_raw_code_cells(best_sub.code_storage_path)
    if notebook_bytes is None:
        logger.warning(
            "wrap_raw_code_cells failed for submission %s, path=%s",
            best_sub.id,
            best_sub.code_storage_path,
        )
        notebook_bytes = cells_to_ipynb_json([]).encode("utf-8")

    return (
        notebook_bytes,
        200,
        {
            "Content-Type": "application/x-ipynb+json",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
