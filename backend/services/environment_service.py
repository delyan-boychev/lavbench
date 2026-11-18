"""nanoColab environments: derived from the competition setting, synced, published and launched."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Response
from sqlalchemy.exc import IntegrityError

from config import Config
from models import (
    Challenge,
    Environment,
    Stage,
    Submission,
    Task,
    User,
    Workspace,
    WorkspaceSetting,
    db,
)
from schemas.environment import DEFAULT_PROFILES, WORKSPACE_DEFAULT_GIB
from services.audit_service import log_action
from services.environment_package import (
    PackageError,
    build,
    content_version,
    data_gib,
    export_paths,
    fingerprint,
    package_entries,
    solution_path,
)
from services.nanocolab_client import (
    ExportIntegrityError,
    NanoColabClient,
    NanoColabError,
    NanoColabUnavailableError,
)
from utils.cache_utils import cache_lock, get_cached, set_cached
from utils.dates import to_tz_iso, utcnow
from utils.error_utils import err, format_size, with_retry_after
from utils.sse_utils import publish_environment_update
from utils.text import numbered_folder_name

logger = logging.getLogger(__name__)

ErrorResult = tuple[Response, int]

READY = "READY"
FAILED = "FAILED"
UPLOADING = "UPLOADING"
VALIDATING = "VALIDATING"
NANOCOLAB_VALIDATING = frozenset({"UPLOADING", "QUEUED", "PROCESSING"})
SYNC_ACTOR = "lavbench-sync"
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 365
MAX_ATTENDANCE = 10000
MIN_ATTENDANCE_HEADROOM = 2
SYNC_LOCK_TTL = 3600
READINESS_TTL = 86400
EXPORT_RETRY_SECONDS = 10
RECONCILE_LOCK = "nanocolab_reconcile"
SETTING_FIELDS = (
    "enabled",
    "auto_publish",
    "image_id",
    "profile_id",
    "cpu_cores",
    "memory_gib",
    "workspace_gib",
    "archive_until",
)


def event_external_id(stage_id: Any, challenge_id: Any) -> str:
    """nanoColab's id for the event of a stage, or of a competition without stages."""
    return f"stage-{stage_id}" if stage_id else f"challenge-{challenge_id}"


@dataclass(frozen=True)
class Owner:
    """The stage, or the competition when it has no stages, that an environment belongs to."""

    challenge: Challenge
    stage: Stage | None

    @property
    def start(self) -> datetime:
        return (self.stage or self.challenge).start_time  # type: ignore[no-any-return]

    @property
    def end(self) -> datetime:
        return (self.stage or self.challenge).end_time  # type: ignore[no-any-return]

    @property
    def ends_at(self) -> datetime:
        """Workspaces stay open through the submission grace period."""
        return self.end + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)

    @property
    def external_id(self) -> str:
        return event_external_id(self.stage.id if self.stage else None, self.challenge.id)

    @property
    def title(self) -> str:
        return str((self.stage or self.challenge).title)

    @property
    def name(self) -> str:
        title = self.challenge.title
        if self.stage is not None:
            title = f"{title} - {self.stage.title}"
        return title if len(title) >= 3 else f"LavBench {title}"

    def tasks(self) -> list[Task]:
        query = Task.query.filter_by(challenge_id=self.challenge.id)
        if self.stage is not None:
            query = Task.query.filter_by(stage_id=self.stage.id)
        else:
            query = query.filter(Task.stage_id.is_(None))
        return list(query.order_by(Task.id).all())

    def environment(self) -> Environment | None:
        if self.stage is not None:
            env: Environment | None = Environment.query.filter_by(stage_id=self.stage.id).first()
        else:
            env = Environment.query.filter_by(challenge_id=self.challenge.id).first()
        return env


def nanocolab_enabled() -> bool:
    return bool(Config.NANOCOLAB_API_URL)


def owner_of(env: Environment) -> Owner:
    stage = db.session.get(Stage, env.stage_id) if env.stage_id else None
    if stage is not None:
        return Owner(challenge=stage.challenge, stage=stage)
    return Owner(challenge=db.get_or_404(Challenge, env.challenge_id), stage=None)


def workspace_owners(challenge: Challenge) -> list[Owner]:
    """Every stage of the competition, or the competition itself when it has none."""
    stages = (
        Stage.query.filter_by(challenge_id=challenge.id)
        .order_by(Stage.start_time, Stage.stage_number)
        .all()
    )
    if not stages:
        return [Owner(challenge=challenge, stage=None)]
    return [Owner(challenge=challenge, stage=stage) for stage in stages]


def owner_of_task(task: Task) -> Owner:
    stage = db.session.get(Stage, task.stage_id) if task.stage_id else None
    return Owner(challenge=task.challenge, stage=stage)


def environment_for_task(task: Task) -> Environment | None:
    return owner_of_task(task).environment()


def _utc_iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat()


def _actor(user_id: Any) -> str:
    return str(user_id)


def attendance(owner: Owner) -> int:
    """Registered students plus a headroom percentage, at least two spare seats."""
    registered = int(
        User.query.filter_by(role="competitor", challenge_id=owner.challenge.id).count()
    )
    headroom = max(
        math.ceil(registered * Config.NANOCOLAB_ATTENDANCE_HEADROOM_PERCENT / 100),
        MIN_ATTENDANCE_HEADROOM,
    )
    return min(registered + headroom, MAX_ATTENDANCE)


def default_archive_until(owner: Owner) -> datetime:
    return owner.ends_at + timedelta(days=DEFAULT_RETENTION_DAYS)


def retention_days(env: Environment, owner: Owner) -> int:
    archive_until = env.archive_until or default_archive_until(owner)
    days = math.ceil((archive_until - owner.ends_at).total_seconds() / 86400)
    return max(1, min(days, MAX_RETENTION_DAYS))


def event_payload(
    env: Environment,
    owner: Owner,
    actor: str,
    published: bool,
    extension_reason: str | None = None,
) -> dict[str, Any]:
    """The full desired state; after publish nanoColab only accepts a later end and metadata."""
    frozen = env.is_published
    payload: dict[str, Any] = {
        "name": owner.name[:200],
        "starts_at": _utc_iso(owner.start),
        "ends_at": _utc_iso(owner.ends_at),
        "profile": {
            "compute_kind": env.compute_kind,
            "cpu_cores": env.cpu_cores,
            "memory_gib": env.memory_gib,
            "disk_gib": env.disk_gib,
            "gpu_type": env.gpu_type if env.compute_kind == "GPU" else None,
        },
        "image_id": env.image_id,
        "asset_version": env.asset_version,
        "max_attendance": env.max_attendance if frozen else attendance(owner),
        "retention_days": env.retention_days if frozen else retention_days(env, owner),
        "published": published,
        "export_paths": export_paths(owner.tasks()),
        "actor": actor,
    }
    if extension_reason:
        payload["extension_reason"] = extension_reason
    return payload


def _window(env: Environment) -> tuple[datetime, datetime]:
    owner = owner_of(env)
    return owner.start, owner.ends_at


def find_overlap(
    challenge_id: Any, start: datetime, ends_at: datetime, exclude_id: Any = None
) -> Environment | None:
    """Another enabled environment of the competition whose window overlaps this one."""
    # A student has one Hub server, and every student of a competition is in all of its stages
    stage_ids = [s.id for s in Stage.query.filter_by(challenge_id=challenge_id).all()]
    candidates: list[Environment] = Environment.query.filter(
        Environment.enabled.is_(True),
        db.or_(
            Environment.challenge_id == challenge_id,
            Environment.stage_id.in_(stage_ids) if stage_ids else db.false(),
        ),
    ).all()
    for other in candidates:
        if exclude_id is not None and str(other.id) == str(exclude_id):
            continue
        other_start, other_end = _window(other)
        if other_start < ends_at and start < other_end:
            return other
    return None


def overlap_error(first: str, second: str) -> ErrorResult:
    return err(
        "ERR_ENVIRONMENT_OVERLAP",
        409,
        message=f"{first}, {second} would have workspaces open at the same time, counting the "
        "grace period after each end. A student has one workspace at a time, so leave a gap "
        "between them.",
        stages=f"{first}, {second}",
    )


def _overlap_with(owner_title: str, other: Environment) -> ErrorResult:
    return overlap_error(owner_title, owner_of(other).title)


def windows_overlap(windows: list[tuple[str, datetime, datetime]]) -> ErrorResult | None:
    """The first two of these ``(title, start, ends_at)`` windows that overlap, as an error."""
    for index, (title, start, ends_at) in enumerate(windows):
        for other_title, other_start, other_ends_at in windows[index + 1 :]:
            if start < other_ends_at and other_start < ends_at:
                return overlap_error(title, other_title)
    return None


def owner_windows(owners: list[Owner]) -> list[tuple[str, datetime, datetime]]:
    return [(owner.title, owner.start, owner.ends_at) for owner in owners]


# ── Locks used by the stage, competition and task routes ──


def window_change_blocked(
    env: Environment | None, owner: Owner, new_start: datetime, new_end: datetime
) -> ErrorResult | None:
    if env is None or not env.enabled:
        return None
    if env.is_published and (new_start != owner.start or new_end != owner.end):
        return err(
            "ERR_ENVIRONMENT_LOCKED",
            409,
            message="The environment is published: the start is fixed, and the end only "
            "moves later through an extension.",
        )
    grace = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    other = find_overlap(owner.challenge.id, new_start, new_end + grace, exclude_id=env.id)
    if other is not None:
        return _overlap_with(owner.title, other)
    return None


def delete_blocked(envs: list[Environment | None]) -> ErrorResult | None:
    if any(env is not None and env.is_published for env in envs):
        return err("ERR_ENVIRONMENT_LOCKED", 409)
    return None


def stage_create_blocked(
    challenge: Challenge, title: str, start: datetime, end: datetime
) -> ErrorResult | None:
    """A published competition environment keeps its tasks; a new stage must not overlap."""
    env = Owner(challenge=challenge, stage=None).environment()
    if env is not None and env.is_published:
        return err(
            "ERR_ENVIRONMENT_LOCKED",
            409,
            message="The competition's workspaces are published, so it can no longer get stages.",
        )
    setting = challenge.workspace_setting
    if setting is None or not setting.enabled:
        return None
    ends_at = end + timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    for owner in workspace_owners(challenge):
        if owner.stage is not None and start < owner.ends_at and owner.start < ends_at:
            return overlap_error(title, owner.title)
    return None


def challenge_environments(challenge: Challenge) -> list[Environment | None]:
    envs: list[Environment | None] = [Owner(challenge=challenge, stage=None).environment()]
    stages = Stage.query.filter_by(challenge_id=challenge.id).all()
    envs.extend(Owner(challenge=challenge, stage=stage).environment() for stage in stages)
    return envs


def task_files_locked(challenge: Challenge, stage_ids: list[Any]) -> ErrorResult | None:
    """Public task files ship in the published package, so they freeze with it."""
    for stage_id in stage_ids:
        stage = db.session.get(Stage, stage_id) if stage_id else None
        env = Owner(challenge=challenge, stage=stage).environment()
        if env is not None and env.is_published:
            return err("ERR_TASK_FILES_LOCKED", 409)
    return None


def _stage_folders(challenge_id: Any, stage_id: Any, exclude_task_id: Any = None) -> set[str]:
    """Folder names used in the stage, or by the competition's tasks without a stage."""
    query = db.session.query(Task.folder_name).filter(Task.challenge_id == challenge_id)
    query = query.filter(Task.stage_id == stage_id if stage_id else Task.stage_id.is_(None))
    if exclude_task_id is not None:
        query = query.filter(Task.id != exclude_task_id)
    return {name for (name,) in query.all() if name}


def folder_name_taken(
    challenge_id: Any, stage_id: Any, folder_name: str, exclude_task_id: Any = None
) -> bool:
    return folder_name in _stage_folders(challenge_id, stage_id, exclude_task_id)


def unique_folder_name(
    challenge_id: Any, stage_id: Any, folder_name: str, exclude_task_id: Any = None
) -> str:
    """The name, or the first free ``name-2``, ``name-3``... in the stage."""
    taken = _stage_folders(challenge_id, stage_id, exclude_task_id)
    candidate, number = folder_name, 2
    while candidate in taken:
        candidate = numbered_folder_name(folder_name, number)
        number += 1
    return candidate


def folder_locked(task: Task) -> ErrorResult | None:
    env = environment_for_task(task)
    if env is not None and env.is_published:
        return err(
            "ERR_ENVIRONMENT_LOCKED",
            409,
            message="The environment is published, so the folder name is fixed.",
        )
    return None


# ── Readiness cache and status ──


def _readiness_key(env_id: Any) -> str:
    return f"nanocolab:readiness:{env_id}"


def cached_readiness(env: Environment) -> dict[str, Any] | None:
    value = get_cached(_readiness_key(env.id))
    return value if isinstance(value, dict) else None


def _store_readiness(env: Environment, readiness: dict[str, Any]) -> None:
    now = utcnow()
    status = str(readiness.get("status") or "PREPARING")
    previous = cached_readiness(env) or {}
    since = previous.get("preparing_since") if previous.get("status") == status else None
    entry = {
        "status": status,
        "message": str(readiness.get("message") or "")[:500],
        "retry_after": int(readiness.get("retry_after_seconds") or 10),
        "fetched_at": _utc_iso(now),
        "preparing_since": since or (_utc_iso(now) if status == "PREPARING" else None),
    }
    set_cached(_readiness_key(env.id), entry, timeout=READINESS_TTL)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return None


def environment_status(env: Environment | None, timezone: str = "UTC") -> dict[str, Any]:
    """Admin and jury chip: off, uploading, preparing, ready, problem or unknown."""
    status: dict[str, Any] = {
        "state": "off",
        "published": bool(env and env.is_published),
        "progress": None,
        "since": None,
        "alert": False,
        "code": None,
        "message": None,
        "limit": None,
        "fetched_at": None,
    }
    if env is None or not env.enabled:
        return status
    if env.package_state == FAILED:
        return {
            **status,
            "state": "problem",
            "code": env.package_error_code,
            "message": env.package_error,
            "limit": env.package_error_limit,
        }
    if env.sync_error:
        return {
            **status,
            "state": "problem",
            "code": "ERR_ENVIRONMENT_SYNC_FAILED",
            "message": env.sync_error,
        }
    if env.package_state == UPLOADING:
        return {**status, "state": "uploading", "progress": env.package_progress}
    if env.package_state != READY or not env.event_id:
        return {**status, "state": "preparing"}
    if not env.is_published:
        return {**status, "state": "ready"}
    readiness = cached_readiness(env)
    fetched_at = _parse_iso(readiness.get("fetched_at")) if readiness else None
    if readiness is None or fetched_at is None:
        return {**status, "state": "unknown"}
    status["fetched_at"] = to_tz_iso(fetched_at, timezone)
    if (utcnow() - fetched_at).total_seconds() > Config.NANOCOLAB_STATUS_STALE_SECONDS:
        return {**status, "state": "unknown"}
    if readiness["status"] == "READY":
        return {**status, "state": "ready"}
    if readiness["status"] == "BLOCKED":
        return {**status, "state": "problem", "message": readiness.get("message")}
    since = _parse_iso(readiness.get("preparing_since")) or fetched_at
    alert_after = timedelta(minutes=Config.NANOCOLAB_PREPARING_ALERT_MINUTES)
    return {
        **status,
        "state": "preparing",
        "since": to_tz_iso(since, timezone),
        "alert": utcnow() - since > alert_after,
        "message": readiness.get("message"),
    }


def student_status(env: Environment, owner: Owner) -> str:
    """One word for the task card: not_open, preparing, ready, unknown or closed."""
    now = utcnow()
    if now >= owner.ends_at:
        return "closed"
    if not env.is_published or now < owner.start:
        return "not_open"
    state = environment_status(env)["state"]
    return state if state in ("ready", "unknown") else "preparing"


def environment_data_gib(env: Environment | None, owner: Owner) -> int:
    """The task data's size in GiB: frozen once published, measured from the files before."""
    if env is not None and env.is_published:
        return max(0, int(env.disk_gib) - int(env.workspace_gib))
    try:
        return data_gib(package_entries(owner.tasks()))
    except PackageError:
        return 0


def environment_dict(
    env: Environment | None, owner: Owner, show_message: bool = True
) -> dict[str, Any]:
    """Settings and status; the status message, nanoColab's raw text, is for admins only."""
    timezone = owner.challenge.timezone or "UTC"
    setting = owner.challenge.workspace_setting
    source: Environment | WorkspaceSetting | None = env or setting
    archive_until = env.archive_until if env else None
    status = environment_status(env, timezone)
    if not show_message:
        status["message"] = None
    workspace_gib = int(source.workspace_gib) if source else WORKSPACE_DEFAULT_GIB
    data = environment_data_gib(env, owner)
    published = env is not None and env.is_published
    return {
        "id": env.id if env else None,
        "challenge_id": owner.challenge.id,
        "stage_id": owner.stage.id if owner.stage else None,
        "stage_title": owner.stage.title if owner.stage else None,
        "enabled": bool(env and env.enabled),
        "auto_publish": bool(env and env.auto_publish),
        "published_at": to_tz_iso(env.published_at, timezone) if env and env.published_at else None,
        "compute_kind": env.compute_kind if env else "CPU",
        "cpu_cores": source.cpu_cores if source else 2,
        "memory_gib": source.memory_gib if source else 8,
        "workspace_gib": workspace_gib,
        "data_gib": data,
        "disk_gib": env.disk_gib if published and env else workspace_gib + data,
        "gpu_type": env.gpu_type if env else None,
        "image_id": source.image_id if source else "",
        "image_digest": env.image_digest if env else None,
        "archive_until": to_tz_iso(archive_until or default_archive_until(owner), timezone),
        "max_attendance": env.max_attendance if env and env.is_published else attendance(owner),
        "starts_at": to_tz_iso(owner.start, timezone),
        "ends_at": to_tz_iso(owner.ends_at, timezone),
        "asset_version": env.asset_version if env else None,
        "folders": [task.folder_name for task in owner.tasks()],
        "status": status,
    }


# ── Competition setting ──


def workspace_profiles(listed: Any) -> list[dict[str, Any]]:
    """nanoColab's compute profiles, or the built-in ones when it lists none."""
    profiles = []
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict):
            continue
        profile: dict[str, Any] = {
            key: item.get(key) for key in ("id", "name", "cpu_cores", "memory_gib")
        }
        named = all(isinstance(profile[key], str) and profile[key] for key in ("id", "name"))
        sized = all(
            type(profile[key]) is int and profile[key] > 0 for key in ("cpu_cores", "memory_gib")
        )
        if named and sized:
            profiles.append(profile)
    return profiles or [dict(profile) for profile in DEFAULT_PROFILES]


def workspace_catalog() -> dict[str, Any] | ErrorResult:
    """Images and profiles from nanoColab, for the setting form and its checks."""
    client = NanoColabClient.from_config()
    if client is None:
        return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    try:
        catalog = client.catalog()
    except NanoColabError as exc:
        logger.warning("nanoColab image catalog failed: %s", exc.message)
        return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    return {"images": catalog["images"], "profiles": workspace_profiles(catalog["profiles"])}


def _setting_values(setting: WorkspaceSetting | None) -> dict[str, Any] | None:
    return {key: getattr(setting, key) for key in SETTING_FIELDS} if setting else None


def check_workspace_setting(
    challenge: Challenge, values: dict[str, Any], ends_at: datetime
) -> dict[str, Any] | ErrorResult:
    """Check a setting against the competition's end plus grace; adds the profile's resources."""
    setting = challenge.workspace_setting
    stored = _setting_values(setting)
    resolved = {
        **values,
        "cpu_cores": setting.cpu_cores if setting else DEFAULT_PROFILES[0]["cpu_cores"],
        "memory_gib": setting.memory_gib if setting else DEFAULT_PROFILES[0]["memory_gib"],
    }
    if values["enabled"]:
        archive_until = values["archive_until"]
        latest = ends_at + timedelta(days=MAX_RETENTION_DAYS)
        if archive_until is not None and not ends_at < archive_until <= latest:
            return err(
                "ERR_INVALID_ARCHIVE_DATE",
                422,
                message="Keep archives until a date after the competition ends, "
                "at most 365 days later.",
                field="workspace.archive_until",
            )
        choice_changed = (
            stored is None
            or not stored["enabled"]
            or values["image_id"] != stored["image_id"]
            or values["profile_id"] != stored["profile_id"]
        )
        # Only a new image or profile asks nanoColab, so other edits work while it is down
        if choice_changed:
            catalog = workspace_catalog()
            if isinstance(catalog, tuple):
                return catalog
            if not any(i.get("image_id") == values["image_id"] for i in catalog["images"]):
                return err("ERR_INVALID_WORKSPACE_IMAGE", 422, field="workspace.image_id")
            profiles = catalog["profiles"]
            profile = next((p for p in profiles if p["id"] == values["profile_id"]), None)
            if profile is None:
                names = ", ".join(p["name"] for p in profiles)
                return err(
                    "ERR_INVALID_WORKSPACE_PROFILE",
                    422,
                    message=f"Profile must be one of: {names}.",
                    field="workspace.profile_id",
                    allowed=names,
                )
            resolved["cpu_cores"] = profile["cpu_cores"]
            resolved["memory_gib"] = profile["memory_gib"]
    if stored is not None and resolved != stored:
        envs = [owner.environment() for owner in workspace_owners(challenge)]
        if envs and all(env is not None and env.is_published for env in envs):
            return err(
                "ERR_ENVIRONMENT_LOCKED",
                409,
                message="Every stage's workspaces are published, so this setting can no longer "
                "change.",
            )
    return resolved


def save_workspace_setting(challenge: Challenge, values: dict[str, Any]) -> bool:
    """Store a checked setting; True when it changed."""
    setting = challenge.workspace_setting
    if setting is None:
        setting = WorkspaceSetting(challenge_id=challenge.id)
        db.session.add(setting)
        challenge.workspace_setting = setting
    changed = _setting_values(setting) != values
    for key in SETTING_FIELDS:
        setattr(setting, key, values[key])
    return changed


def _derive(env: Environment, setting: WorkspaceSetting | None, owner: Owner) -> None:
    if setting is None:
        env.enabled = False
        return
    for key in ("enabled", "auto_publish", "image_id", "cpu_cores", "memory_gib"):
        setattr(env, key, getattr(setting, key))
    env.compute_kind, env.gpu_type = "CPU", None
    env.workspace_gib = setting.workspace_gib
    env.archive_until = setting.archive_until
    env.disk_gib = env.workspace_gib + environment_data_gib(None, owner)
    env.sync_error = None


def apply_workspace_setting(challenge: Challenge) -> None:
    """Derive every unpublished environment of the competition from its setting, then sync."""
    setting = challenge.workspace_setting
    owners = workspace_owners(challenge)
    to_sync = []
    for owner in owners:
        env = owner.environment()
        if env is None:
            if setting is None or not setting.enabled:
                continue
            env = Environment(
                stage_id=owner.stage.id if owner.stage else None,
                challenge_id=None if owner.stage else challenge.id,
            )
            db.session.add(env)
        if not env.is_published:
            _derive(env, setting, owner)
        if env.enabled:
            to_sync.append(env)
    if owners[0].stage is not None:
        # Once the competition has stages, its own environment no longer serves anyone
        own = Owner(challenge=challenge, stage=None).environment()
        if own is not None and not own.is_published:
            own.enabled = False
    db.session.commit()
    for env in to_sync:
        enqueue_sync(env.id)
    publish_environment_update(challenge.id)


def enqueue_sync(environment_id: Any) -> None:
    from tasks import sync_environment as sync_task

    try:
        sync_task.apply_async(
            args=[str(environment_id)],
            queue="internal",
            expires=Config.NANOCOLAB_SYNC_INTERVAL_SECONDS,
        )
    except Exception:
        logger.exception("Could not queue the environment sync for %s", environment_id)


# ── Sync loop ──


def _problem_signature(env: Environment) -> tuple[str | None, str | None]:
    return env.package_error_code, env.sync_error


def _package_failed(env: Environment, code: str, message: str, limit: str | None = None) -> None:
    env.package_state = FAILED
    env.package_error_code = code
    env.package_error = message[:500]
    env.package_error_limit = limit
    env.package_progress = 0


def _apply_asset(env: Environment, asset: dict[str, Any]) -> None:
    state = str(asset.get("state") or "")
    if state == READY:
        env.package_state, env.package_progress = READY, 100
        env.package_error_code = env.package_error = env.package_error_limit = None
    elif state in NANOCOLAB_VALIDATING:
        env.package_state = VALIDATING
    else:
        message = str(asset.get("error") or "nanoColab rejected the package.")
        _package_failed(env, "ERR_ENVIRONMENT_PACKAGE_FAILED", message)


def _upload_progress(env: Environment, size: int, challenge_id: Any) -> Any:
    def report(sent: int) -> None:
        percent = min(99, sent * 100 // max(size, 1))
        if percent >= env.package_progress + 10:
            env.package_progress = percent
            db.session.commit()
            publish_environment_update(challenge_id)

    return report


def ensure_package(env: Environment, owner: Owner, client: NanoColabClient) -> None:
    """Build and upload the package when the tasks' files changed since the last upload."""
    try:
        entries = package_entries(owner.tasks())
    except PackageError as exc:
        _package_failed(env, exc.code, exc.message, exc.limit)
        env.package_fingerprint = None
        return
    env.disk_gib = env.workspace_gib + data_gib(entries)
    current = fingerprint(entries)
    if current == env.package_fingerprint and env.asset_version:
        if env.package_state in (READY, FAILED):
            return
        if env.package_state == VALIDATING:
            _apply_asset(env, client.get_asset(env.asset_version))
            return
    version = content_version(entries)
    env.package_fingerprint = current
    if version == env.asset_version and env.package_state == READY:
        return
    try:
        existing = client.get_asset(version)
    except NanoColabError as exc:
        if exc.status != 404:
            raise
    else:
        if existing.get("state") != "UPLOADING":
            env.asset_version = version
            _apply_asset(env, existing)
            return
    env.package_state, env.package_progress = UPLOADING, 0
    env.package_error_code = env.package_error = env.package_error_limit = None
    env.asset_version = version
    db.session.commit()
    publish_environment_update(owner.challenge.id)
    built = build(entries, version, os.path.join(Config.UPLOAD_FOLDER, "environment_packages"))
    try:
        asset = client.start_asset_upload(built.version, built.size, built.sha256)
        if asset.get("upload"):
            client.upload_asset(
                asset["upload"], built.path, _upload_progress(env, built.size, owner.challenge.id)
            )
        if asset.get("state") in ("UPLOADING", "QUEUED"):
            asset = client.complete_asset_upload(built.version)
    finally:
        os.unlink(built.path)
    _apply_asset(env, asset)


def _put_event(
    env: Environment,
    owner: Owner,
    client: NanoColabClient,
    actor: str,
    published: bool,
    extension_reason: str | None = None,
) -> None:
    payload = event_payload(env, owner, actor, published, extension_reason)
    event = client.put_event(owner.external_id, payload)
    env.event_id = str(event.get("event_id") or "")[:64] or None
    env.image_digest = str(event.get("environment_digest") or "")[:500] or None
    env.max_attendance = payload["max_attendance"]
    env.retention_days = payload["retention_days"]
    env.synced_at = utcnow()
    env.sync_error = None


def _auto_publish_due(env: Environment, owner: Owner, now: datetime) -> bool:
    lead = timedelta(hours=Config.NANOCOLAB_AUTO_PUBLISH_LEAD_HOURS)
    return env.auto_publish and not env.is_published and now >= owner.start - lead


def _audit_publish(env: Environment, actor_id: Any) -> None:
    log_action(
        admin_id=actor_id,
        action_type="publish",
        target_type="environment",
        target_id=env.id,
        details={"asset_version": env.asset_version, "max_attendance": env.max_attendance},
    )


def sync_environment(environment_id: Any) -> str:
    """One sync run: package, event, auto-publish and readiness. Returns a short result."""
    client = NanoColabClient.from_config()
    if client is None:
        return "disabled"
    with cache_lock(f"nanocolab_sync:{environment_id}", ttl=SYNC_LOCK_TTL) as got:
        if not got:
            return "busy"
        env = db.session.get(Environment, environment_id)
        if env is None or not env.enabled:
            return "skipped"
        owner = owner_of(env)
        now = utcnow()
        if now >= owner.ends_at:
            return "ended"
        before = _problem_signature(env)
        try:
            if not env.is_published:
                ensure_package(env, owner, client)
            if env.package_state == READY:
                publish_now = env.is_published or _auto_publish_due(env, owner, now)
                _put_event(env, owner, client, SYNC_ACTOR, publish_now)
                if publish_now and not env.is_published:
                    env.published_at = now
                    _audit_publish(env, None)
                if env.is_published:
                    _store_readiness(env, client.get_readiness(owner.external_id))
            elif _auto_publish_due(env, owner, now) and env.package_state != UPLOADING:
                env.sync_error = "Automatic publish is due, but the package is not ready."
        except NanoColabError as exc:
            env.sync_error = (exc.message or f"nanoColab returned {exc.status}")[:500]
        after = _problem_signature(env)
        if after != before:
            log_action(
                admin_id=None,
                action_type="sync",
                target_type="environment",
                target_id=env.id,
                details={"code": after[0], "message": after[1] or env.package_error},
            )
        db.session.commit()
    publish_environment_update(owner.challenge.id)
    return "problem" if any(after) else "ok"


def enabled_environment_ids() -> list[str]:
    """Enabled environments whose owner has not yet passed its end plus the grace period."""
    cutoff = utcnow() - timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    query = (
        db.session.query(Environment.id)
        .outerjoin(Stage, Environment.stage_id == Stage.id)
        .outerjoin(Challenge, Environment.challenge_id == Challenge.id)
        .filter(
            Environment.enabled.is_(True),
            db.func.coalesce(Stage.end_time, Challenge.end_time) > cutoff,
        )
    )
    return [str(env_id) for (env_id,) in query.all()]


# ── Publish and extension ──


def _package_error(exc: PackageError) -> ErrorResult:
    if exc.code == "ERR_ENVIRONMENT_PACKAGE_EMPTY":
        return err("ERR_ENVIRONMENT_PACKAGE_EMPTY", 422, message=exc.message)
    if exc.code == "ERR_ENVIRONMENT_PACKAGE_TOO_LARGE":
        return err("ERR_ENVIRONMENT_PACKAGE_TOO_LARGE", 413, message=exc.message, limit=exc.limit)
    if exc.code == "ERR_ENVIRONMENT_TOO_MANY_TASKS":
        return err("ERR_ENVIRONMENT_TOO_MANY_TASKS", 409, message=exc.message, limit=exc.limit)
    return err("ERR_ENVIRONMENT_PACKAGE_FAILED", 422, message=exc.message)


def _sync_failed(exc: NanoColabError) -> ErrorResult:
    message = exc.message or f"nanoColab returned {exc.status}"
    return err("ERR_ENVIRONMENT_SYNC_FAILED", 502, message=message)


def _preparing() -> ErrorResult:
    return with_retry_after(
        err("ERR_ENVIRONMENT_PREPARING", 503), Config.NANOCOLAB_SYNC_INTERVAL_SECONDS
    )


def publish_environment(env: Environment, actor_id: Any) -> ErrorResult | None:
    if not env.enabled:
        return err("ERR_ENVIRONMENT_NOT_ENABLED", 409)
    if env.is_published:
        return None
    owner = owner_of(env)
    if utcnow() >= owner.ends_at:
        return err("ERR_ENVIRONMENT_NOT_OPEN", 409, message="The environment window has ended.")
    try:
        current = fingerprint(package_entries(owner.tasks()))
    except PackageError as exc:
        return _package_error(exc)
    if env.package_state == FAILED and current == env.package_fingerprint:
        return err("ERR_ENVIRONMENT_PACKAGE_FAILED", 422, message=env.package_error)
    if current != env.package_fingerprint:
        enqueue_sync(env.id)
        return _preparing()
    if env.package_state != READY or not env.event_id:
        return _preparing()
    other = find_overlap(owner.challenge.id, owner.start, owner.ends_at, exclude_id=env.id)
    if other is not None:
        return _overlap_with(owner.title, other)
    client = NanoColabClient.from_config()
    if client is None:
        return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    with cache_lock(f"nanocolab_sync:{env.id}", ttl=SYNC_LOCK_TTL) as got:
        if not got:
            return _preparing()
        try:
            _put_event(env, owner, client, _actor(actor_id), published=True)
        except NanoColabError as exc:
            db.session.rollback()
            return _sync_failed(exc)
        env.published_at = utcnow()
        db.session.commit()
        _audit_publish(env, actor_id)
        db.session.commit()
    enqueue_sync(env.id)
    publish_environment_update(owner.challenge.id)
    return None


def extend_environment(
    env: Environment, new_end: datetime, reason: str, actor_id: Any
) -> ErrorResult | None:
    """Move the owner's end later, before the current end plus grace has passed."""
    owner = owner_of(env)
    if utcnow() >= owner.ends_at:
        return err("ERR_EXTENSION_TOO_LATE", 409)
    if new_end <= owner.end:
        return err("ERR_INVALID_DATE_RANGE", 400, message="The new end must be later.")
    if owner.stage is not None and new_end > owner.challenge.end_time:
        return err(
            "ERR_STAGE_OUT_OF_COMPETITION_BOUNDS",
            400,
            message="Extend the competition first: the stage must end within it.",
        )
    grace = timedelta(seconds=Config.DEADLINE_GRACE_PERIOD_SECONDS)
    other = (
        find_overlap(owner.challenge.id, owner.start, new_end + grace, exclude_id=env.id)
        if env.enabled
        else None
    )
    if other is not None:
        return _overlap_with(owner.title, other)
    old_end = owner.end
    target = owner.stage or owner.challenge
    target.end_time = new_end
    if env.archive_until is not None:
        env.archive_until += new_end - old_end
    if env.is_published:
        client = NanoColabClient.from_config()
        if client is None:
            db.session.rollback()
            return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
        with cache_lock(f"nanocolab_sync:{env.id}", ttl=SYNC_LOCK_TTL) as got:
            if not got:
                db.session.rollback()
                return _preparing()
            try:
                _put_event(env, owner, client, _actor(actor_id), True, reason)
            except NanoColabError as exc:
                db.session.rollback()
                return _sync_failed(exc)
            db.session.commit()
    db.session.commit()
    log_action(
        admin_id=actor_id,
        action_type="extend",
        target_type="environment",
        target_id=env.id,
        details={"old_end": _utc_iso(old_end), "new_end": _utc_iso(new_end)},
        reason=reason,
    )
    db.session.commit()
    if env.enabled and not env.is_published:
        enqueue_sync(env.id)
    publish_environment_update(owner.challenge.id)
    return None


# ── Students ──


def _launch_error(exc: NanoColabError) -> ErrorResult:
    if isinstance(exc, NanoColabUnavailableError) and exc.retry_after:
        return with_retry_after(err("ERR_ENVIRONMENT_PREPARING", 503), exc.retry_after)
    if exc.status == 409 and "maximum attendance" in exc.message:
        return err("ERR_ENVIRONMENT_FULL", 409)
    if exc.status == 409 and "window" in exc.message:
        return err("ERR_ENVIRONMENT_NOT_OPEN", 409)
    logger.warning("Workspace launch failed with %s: %s", exc.status, exc.message)
    result = err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    return with_retry_after(result, exc.retry_after) if exc.retry_after else result


def _workspace_row(env: Environment, user_id: Any, workspace_id: str) -> Workspace:
    row: Workspace | None = Workspace.query.filter_by(
        environment_id=env.id, user_id=user_id
    ).first()
    if row is not None:
        return row
    row = Workspace(environment_id=env.id, user_id=user_id, workspace_id=workspace_id)
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        row = Workspace.query.filter_by(environment_id=env.id, user_id=user_id).one()
    return row


def launch_workspace(task: Task, user_id: Any) -> dict[str, Any] | ErrorResult:
    """Create the student's workspace on the first click, then mint a launch token."""
    owner = owner_of_task(task)
    env = owner.environment()
    if env is None or not env.enabled:
        return err("ERR_ENVIRONMENT_NOT_ENABLED", 409)
    now = utcnow()
    if not env.is_published or not owner.start <= now < owner.ends_at:
        return err("ERR_ENVIRONMENT_NOT_OPEN", 409)
    readiness = cached_readiness(env)
    if readiness and readiness.get("status") == "PREPARING":
        return with_retry_after(
            err("ERR_ENVIRONMENT_PREPARING", 503), int(readiness.get("retry_after") or 10)
        )
    client = NanoColabClient.from_config()
    if client is None:
        return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    subject = str(user_id).lower()
    try:
        workspace = client.ensure_workspace(owner.external_id, subject)
        workspace_id = str(workspace["workspace_id"])
        row = _workspace_row(env, user_id, workspace_id)
        row.workspace_id = workspace_id
        launch = client.launch(workspace_id, subject)
    except NanoColabError as exc:
        return _launch_error(exc)
    except KeyError:
        return err("ERR_NANOCOLAB_UNAVAILABLE", 503)
    row.last_launched_at = now
    log_action(
        admin_id=None,
        action_type="launch",
        target_type="environment",
        target_id=env.id,
        details={"task_id": str(task.id)},
        target_user_id=user_id,
    )
    db.session.commit()
    return {
        "launch_url": str(launch.get("launch_url") or ""),
        "launch_token": str(launch.get("launch_token") or ""),
        "expires_at": str(launch.get("expires_at") or ""),
        "open_path": solution_path(task),
    }


def _latest_submissions(task_ids: list[Any]) -> dict[str, Any]:
    """Each user's latest submission to these tasks, as ``created_at`` and ``status``."""
    if not task_ids:
        return {}
    newest = (
        db.session.query(Submission.user_id, db.func.max(Submission.created_at).label("latest"))
        .filter(Submission.task_id.in_(task_ids))
        .group_by(Submission.user_id)
        .subquery()
    )
    rows = (
        db.session.query(Submission.user_id, Submission.created_at, Submission.status)
        .join(
            newest,
            (Submission.user_id == newest.c.user_id) & (Submission.created_at == newest.c.latest),
        )
        .filter(Submission.task_id.in_(task_ids))
        .order_by(Submission.id)
        .all()
    )
    return {str(row.user_id): row for row in rows}


def workspace_rows(env: Environment, owner: Owner, show_identity: bool) -> list[dict[str, Any]]:
    """Every registered student with their workspace and latest submission in this owner."""
    timezone = owner.challenge.timezone or "UTC"
    students = (
        User.query.filter_by(role="competitor", challenge_id=owner.challenge.id)
        .order_by(User.alias_id)
        .all()
    )
    workspaces = {str(w.user_id): w for w in Workspace.query.filter_by(environment_id=env.id)}
    latest = _latest_submissions([task.id for task in owner.tasks()])
    rows = []
    for user in students:
        workspace = workspaces.get(str(user.id))
        sub = latest.get(str(user.id))
        rows.append(
            {
                "user_id": user.id,
                "alias": user.alias_id,
                "username": user.username if show_identity else None,
                "opened": workspace is not None,
                "created_at": to_tz_iso(workspace.created_at, timezone) if workspace else None,
                "last_launched_at": to_tz_iso(workspace.last_launched_at, timezone)
                if workspace and workspace.last_launched_at
                else None,
                "last_submission_at": to_tz_iso(sub.created_at, timezone) if sub else None,
                "last_submission_status": sub.status if sub else None,
            }
        )
    return rows


# ── Workspace exports ──


@dataclass(frozen=True)
class ExportedFile:
    """A file read from the student's workspace into a local path."""

    path: str
    size: int
    sha256: str
    source: str | None
    modified_at: str | None


def _missing(filename: str, folder: str) -> ErrorResult:
    if filename == "solution.ipynb":
        return err(
            "ERR_WORKSPACE_NOTEBOOK_MISSING",
            404,
            message=f"No solution.ipynb in {folder}/ of your workspace.",
            folder=folder,
        )
    return err(
        "ERR_WORKSPACE_FILE_MISSING",
        404,
        message=(
            f"No {filename} in {folder}/ of your workspace. "
            "Save it from solution.ipynb, then Submit again."
        ),
        file=filename,
        folder=folder,
    )


def _too_large() -> ErrorResult:
    limit = format_size(Config.NANOCOLAB_EXPORT_MAX_BYTES)
    return err(
        "ERR_WORKSPACE_FILE_TOO_LARGE",
        413,
        message=f"The file exceeds the {limit} limit.",
        limit=limit,
    )


def _export_error(exc: NanoColabError, missing: ErrorResult) -> ErrorResult:
    if isinstance(exc, ExportIntegrityError):
        return err("ERR_WORKSPACE_EXPORT_INTEGRITY", 502)
    if isinstance(exc, NanoColabUnavailableError):
        # A 503 with Retry-After is nanoColab's own "archive storage busy"; the rest is an outage
        if exc.retry_after:
            return with_retry_after(err("ERR_WORKSPACE_EXPORT_UNAVAILABLE", 503), exc.retry_after)
        return with_retry_after(err("ERR_NANOCOLAB_UNAVAILABLE", 503), EXPORT_RETRY_SECONDS)
    if exc.status == 404:
        return missing
    if exc.status == 409:
        return with_retry_after(
            err("ERR_WORKSPACE_EXPORT_UNAVAILABLE", 409), exc.retry_after or EXPORT_RETRY_SECONDS
        )
    if exc.status == 410:
        return err("ERR_WORKSPACE_ARCHIVE_PURGED", 410)
    if exc.status == 413:
        return _too_large()
    logger.warning("Workspace export failed with %s: %s", exc.status, exc.message)
    return with_retry_after(err("ERR_NANOCOLAB_UNAVAILABLE", 503), EXPORT_RETRY_SECONDS)


def published_environment(task: Task) -> Environment | ErrorResult:
    """The task's environment when students can read files from it."""
    if not nanocolab_enabled():
        return err("ERR_NANOCOLAB_DISABLED", 404)
    env = environment_for_task(task)
    if env is None or not env.enabled or not env.is_published:
        return err("ERR_TASK_NOT_WORKSPACE_BACKED", 409)
    return env


def export_workspace_file(
    task: Task, user_id: Any, filename: str, directory: str
) -> ExportedFile | ErrorResult:
    """Stream ``<folder>/<filename>`` from the user's workspace, checked against its metadata."""
    env = published_environment(task)
    if not isinstance(env, Environment):
        return env
    row: Workspace | None = Workspace.query.filter_by(
        environment_id=env.id, user_id=user_id
    ).first()
    folder, task_id = str(task.folder_name), str(task.id)
    missing = _missing(filename, folder)
    if row is None:
        return with_retry_after(
            err(
                "ERR_WORKSPACE_EXPORT_UNAVAILABLE",
                409,
                message="Open your workspace and save your work first.",
            ),
            EXPORT_RETRY_SECONDS,
        )
    workspace_id, env_id = row.workspace_id, env.id
    # The export is a network call; never hold a transaction open across it
    db.session.commit()
    client = NanoColabClient.from_config()
    if client is None:
        return with_retry_after(err("ERR_NANOCOLAB_UNAVAILABLE", 503), EXPORT_RETRY_SECONDS)
    subject = str(user_id).lower()
    remote = f"{folder}/{filename}"
    limit = Config.NANOCOLAB_EXPORT_MAX_BYTES
    try:
        meta = client.export_metadata(workspace_id, subject, remote)
    except NanoColabError as exc:
        if exc.status == 404:
            logger.warning("nanoColab does not know workspace %s", workspace_id)
            return with_retry_after(err("ERR_NANOCOLAB_UNAVAILABLE", 503), EXPORT_RETRY_SECONDS)
        return _export_error(exc, missing)
    size = meta.get("size")
    if meta.get("status") == "MISSING":
        return missing
    if meta.get("status") == "TOO_LARGE" or (isinstance(size, int) and size > limit):
        return _too_large()
    local = os.path.join(directory, filename)
    try:
        with open(local, "wb") as target:
            got = client.export_raw(workspace_id, subject, remote, target, limit)
    except NanoColabError as exc:
        return _export_error(exc, missing)
    if got["sha256"] != meta.get("sha256") or got["size"] != size:
        return err("ERR_WORKSPACE_EXPORT_INTEGRITY", 502)
    exported = ExportedFile(
        path=local,
        size=int(got["size"]),
        sha256=str(got["sha256"]),
        source=str(got.get("source") or meta.get("source") or "") or None,
        modified_at=str(meta.get("modified_at") or "") or None,
    )
    log_action(
        admin_id=None,
        action_type="export",
        target_type="environment",
        target_id=env_id,
        details={
            "task_id": task_id,
            "path": remote,
            "size": exported.size,
            "sha256": exported.sha256,
            "source": exported.source,
        },
        target_user_id=user_id,
    )
    db.session.commit()
    return exported


# ── Event cancel and orphan reconciliation ──


def _cancel(client: NanoColabClient, external_id: str, reason: str) -> bool:
    try:
        client.cancel_event(external_id, SYNC_ACTOR, reason)
    except NanoColabError as exc:
        if exc.status == 404:
            return True
        logger.warning("Could not cancel nanoColab event %s: %s", external_id, exc.message)
        return False
    return True


def cancel_events(external_ids: list[str], reason: str) -> None:
    """Cancel the nanoColab events of owners being deleted; the reconciliation retries failures."""
    if not external_ids or not nanocolab_enabled():
        return
    client = NanoColabClient.from_config()
    if client is None:
        return
    for external_id in external_ids:
        _cancel(client, external_id, reason)


def synced_external_ids(envs: list[Environment | None]) -> list[str]:
    """The event ids of the environments that reached nanoColab."""
    return [
        event_external_id(env.stage_id, env.challenge_id)
        for env in envs
        if env is not None and env.event_id
    ]


def known_external_ids() -> set[str]:
    rows = db.session.query(Environment.stage_id, Environment.challenge_id).all()
    return {event_external_id(stage_id, challenge_id) for stage_id, challenge_id in rows}


def reconcile_events() -> dict[str, int]:
    """Cancel nanoColab events of this client whose environment LavBench no longer has."""
    client = NanoColabClient.from_config()
    if client is None:
        return {"cancelled": 0, "failed": 0}
    with cache_lock(RECONCILE_LOCK, ttl=SYNC_LOCK_TTL) as got:
        if not got:
            return {"cancelled": 0, "failed": 0}
        try:
            events = client.list_events()
        except NanoColabError as exc:
            logger.warning("Could not list nanoColab events: %s", exc.message)
            return {"cancelled": 0, "failed": 0}
        known = known_external_ids()
        orphans = [
            str(event.get("external_id") or "")
            for event in events
            if not event.get("cancelled_at") and str(event.get("external_id") or "") not in known
        ]
        cancelled = failed = 0
        for external_id in filter(None, orphans):
            if _cancel(client, external_id, "LavBench no longer has this environment"):
                cancelled += 1
                log_action(
                    admin_id=None,
                    action_type="cancel",
                    target_type="environment",
                    target_id=None,
                    details={"external_id": external_id},
                )
            else:
                failed += 1
        db.session.commit()
    return {"cancelled": cancelled, "failed": failed}
