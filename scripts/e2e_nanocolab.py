#!/usr/bin/env python3
"""API-level end-to-end check of the admin, student and jury environment paths on `make dev-nanocolab`."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from api_smoke_test import (
    ACCURACY_METRICS,
    FAIL,
    PASS,
    SCORED_BASELINE_IPYNB,
    TINY_LABELS,
    Api,
    check,
    read_admin_credentials,
    section,
)

# 503 means nanoColab is still preparing and 429 a rate limit; every other answer is final
RETRY_CODES = (429, 503)


def iso(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def login(base: str, username: str, password: str) -> Api:
    api = Api(base)
    code, data = api.send("GET", "/api/auth/csrf-token")
    api.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    code, _ = api.send("POST", "/api/auth/login", {"username": username, "password": password})
    check(f"login {username}", code == 200)
    return api


def code_of(data: object) -> str | None:
    return data.get("code") if isinstance(data, dict) else None


def stage_environment(api: Api, cid: str, sid: str) -> tuple[int, dict]:
    """The stage's row of the competition's environment list."""
    code, data = api.send("GET", f"/api/challenges/{cid}/environments")
    rows = data.get("environments", []) if isinstance(data, dict) else []
    return code, next((row for row in rows if row.get("stage_id") == sid), {})


def wait_for(fetch: Callable[[], tuple[int, dict]], done, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        code, data = fetch()
        if code == 200 and done(data):
            return data
        if 400 <= code < 500 and code not in RETRY_CODES:
            return data
        time.sleep(5)
    return data


def retry(send: Callable[[], tuple[int, object]], timeout: float, interval: float = 15.0):
    """Repeat a request while it answers 429 or 503."""
    deadline = time.monotonic() + timeout
    code, data = send()
    while code in RETRY_CODES and time.monotonic() < deadline:
        time.sleep(interval)
        code, data = send()
    return code, data


def hub_launch(launch: dict, origin: str) -> int:
    """Form-POST the launch token like the browser does; the Hub redirects into JupyterLab."""
    body = urllib.parse.urlencode({"launch_token": launch["launch_token"]}).encode()
    request = urllib.request.Request(
        launch["launch_url"], data=body, method="POST", headers={"Origin": origin}
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5001")
    # The Hub accepts launches only from its LAUNCH_ORIGINS, which nanoColab's up.sh sets from it
    parser.add_argument(
        "--origin", default=os.environ.get("LAVBENCH_ORIGIN", "http://localhost:5173")
    )
    parser.add_argument("--admin-credentials", default=".local-nanocolab/admin_credentials.txt")
    parser.add_argument("--ready-timeout", type=float, default=900.0)
    args = parser.parse_args()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    section("1. Admin setup")
    admin = login(args.base, *read_admin_credentials(args.admin_credentials))
    code, catalog = admin.send("GET", "/api/environment/images")
    available = code == 200 and isinstance(catalog, dict) and bool(catalog.get("available"))
    check("nanoColab image list available", available, str(catalog))
    if not available:
        print(f"\nnanoColab is off, stopping: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    images = catalog["images"]
    setting = {
        "enabled": True,
        "image_id": next((i for i in images if i.get("default")), images[0])["image_id"],
        "profile_id": catalog["profiles"][0]["id"],
        "workspace_gib": catalog["workspace_gib"]["default"],
        "auto_publish": False,
        "archive_until": None,
    }
    code, data = admin.send(
        "POST",
        "/api/challenges",
        {
            "title": f"E2E nanoColab {now:%H%M%S}",
            "start_time": iso(now - datetime.timedelta(minutes=5)),
            "end_time": iso(now + datetime.timedelta(hours=3)),
            "timezone": "UTC",
            "gpu_required": False,
        },
    )
    cid = data.get("id", "") if isinstance(data, dict) else ""
    check("create competition", code == 201 and bool(cid), str(data))
    code, data = admin.send(
        "POST",
        f"/api/challenges/{cid}/stages",
        {
            "title": "Round 1",
            "start_time": iso(now - datetime.timedelta(minutes=1)),
            "end_time": iso(now + datetime.timedelta(hours=1)),
        },
    )
    sid = data.get("id", "") if isinstance(data, dict) else ""
    check("create stage", code == 201 and bool(sid), str(data))
    code, data = admin.create_task(
        cid,
        {"title": "Image Classification", "stage_id": sid, "metrics_config": ACCURACY_METRICS},
        {"baseline_notebook": ("baseline.ipynb", json.dumps(SCORED_BASELINE_IPYNB).encode())},
        [("labels.parquet", TINY_LABELS, "hidden"), ("train.csv", b"id,x\n1,2\n", "public")],
    )
    tid = data.get("id", "") if isinstance(data, dict) else ""
    check(
        "create task, folder generated, data files streamed",
        code == 201
        and isinstance(data, dict)
        and data.get("folder_name") == "image-classification",
        str(data),
    )
    code, data = admin.send(
        "POST",
        "/api/admin/register-competitor",
        {
            "name": "Ivo",
            "surname": "Georgiev",
            "middle_name": "P",
            "birth_date": "2008-04-04",
            "grade": "11",
            "school": "E2E",
            "city": "Sofia",
            "challenge_id": cid,
        },
    )
    student_user = data.get("generated_username", "") if isinstance(data, dict) else ""
    student_pass = data.get("generated_password", "") if isinstance(data, dict) else ""
    check("register student", code == 201 and bool(student_user), str(data))
    code, data = admin.send(
        "POST",
        "/api/admin/register-user",
        {"name": "Jury", "surname": "E2E", "role": "jury", "jury_challenges": [cid]},
    )
    jury_user = data.get("generated_username", "") if isinstance(data, dict) else ""
    jury_pass = data.get("generated_password", "") if isinstance(data, dict) else ""
    check("register jury", code == 201 and bool(jury_user), str(data))

    code, env = stage_environment(admin, cid, sid)
    check(
        "stage environment listed off before the setting",
        code == 200 and env.get("enabled") is False and env["status"]["state"] == "off",
        str(env),
    )
    # Workspaces are one competition-level setting; every stage derives its environment from it
    code, data = admin.send("PUT", f"/api/challenges/{cid}", {"workspace": setting})
    check("save the workspace setting once", code == 200, str(data))
    code, env = stage_environment(admin, cid, sid)
    eid = env.get("id") or ""
    check("stage environment derived", code == 200 and bool(eid) and env.get("enabled"), str(env))
    if FAIL:
        print(f"\nSetup failed, stopping: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    env = wait_for(
        lambda: stage_environment(admin, cid, sid),
        lambda d: d["status"]["state"] in ("ready", "problem"),
        args.ready_timeout,
    )
    check("package uploaded, draft ready", env.get("status", {}).get("state") == "ready", str(env))
    publish = f"/api/challenges/{cid}/environments/{eid}/publish"
    code, data = retry(lambda: admin.send("POST", publish), args.ready_timeout)
    check(
        "publish",
        code == 200 and isinstance(data, dict) and bool(data.get("published_at")),
        f"{code} {data}",
    )
    env = wait_for(
        lambda: stage_environment(admin, cid, sid),
        lambda d: d["status"]["state"] == "ready" and d["status"]["published"],
        args.ready_timeout,
    )
    check("nanoColab reports ready", env.get("status", {}).get("state") == "ready", str(env))

    section("2. Student")
    student = login(args.base, student_user, student_pass)
    card = f"/api/tasks/{tid}/environment"

    def fetch_card() -> tuple[int, dict]:
        code, body = student.send("GET", card)
        return code, body if isinstance(body, dict) else {}

    data = wait_for(fetch_card, lambda d: d.get("status") == "ready", args.ready_timeout)
    check(
        "task card status ready, opens the task folder",
        data.get("status") == "ready" and data.get("folder_name") == "image-classification",
        str(data),
    )
    launch = f"/api/tasks/{tid}/environment/launch"
    for attempt in ("first open", "re-entry"):
        started = time.monotonic()
        code, data = retry(lambda: student.send("POST", launch), args.ready_timeout)
        check(f"launch token ({attempt})", code == 200 and isinstance(data, dict), f"{code} {data}")
        if code == 200 and isinstance(data, dict):
            status = hub_launch(data, args.origin)
            check(
                f"Hub accepts the token ({attempt})",
                status in (302, 303),
                f"{status} from Origin {args.origin}",
            )
        print(f"  {attempt}: {time.monotonic() - started:.1f} s")

    section("3. Jury")
    jury = login(args.base, jury_user, jury_pass)
    code, data = stage_environment(jury, cid, sid)
    check(
        "jury reads the status without nanoColab's message",
        code == 200 and data.get("id") == eid and data["status"]["message"] is None,
        str(data),
    )
    code, data = jury.send("GET", f"/api/challenges/{cid}/environments/{eid}/workspaces")
    rows = data.get("workspaces", []) if isinstance(data, dict) else []
    check(
        "jury sees the workspace list by alias",
        code == 200 and any(r["opened"] and r["username"] is None for r in rows),
        str(data),
    )
    code, data = jury.send("PUT", f"/api/challenges/{cid}", {"workspace": setting})
    check("jury cannot change the workspace setting", code == 403, f"{code} {data}")
    code, data = jury.send("POST", publish)
    check("jury cannot publish", code == 403, f"{code} {data}")

    section("4. Failure paths")
    # A student has one workspace at a time, so stages may not overlap while workspaces are on
    code, data = admin.send(
        "POST",
        f"/api/challenges/{cid}/stages",
        {
            "title": "Overlapping",
            "start_time": iso(now + datetime.timedelta(minutes=30)),
            "end_time": iso(now + datetime.timedelta(hours=2)),
        },
    )
    check(
        "overlapping stage refused",
        code == 409 and code_of(data) == "ERR_ENVIRONMENT_OVERLAP",
        f"{code} {data}",
    )
    files = f"/api/tasks/{tid}/files"
    code, data = admin.put_raw(f"{files}/extra.csv?visibility=public", b"id,x\n2,3\n")
    check(
        "public file change after publish refused",
        code == 409 and code_of(data) == "ERR_TASK_FILES_LOCKED",
        f"{code} {data}",
    )
    code, data = admin.put_raw(f"{files}/labels.parquet?visibility=hidden", TINY_LABELS)
    check(
        "labels fix after publish needs a reason",
        code == 400 and code_of(data) == "ERR_REASON_REQUIRED",
        f"{code} {data}",
    )
    reason = "E2E labels correction"
    query = urllib.parse.urlencode({"visibility": "hidden", "reason": reason})
    code, data = admin.put_raw(f"{files}/labels.parquet?{query}", TINY_LABELS)
    check("labels fix after publish with a reason", code == 200, f"{code} {data}")
    code, data = admin.send(
        "GET", f"/api/admin/audit-logs?challenge_id={cid}&action_type=update&per_page=20"
    )
    logs = data.get("logs", []) if isinstance(data, dict) else []
    check(
        "labels fix audited with its reason",
        any(
            log.get("reason") == reason
            and (log.get("details") or {}).get("file") == "labels.parquet"
            and (log.get("details") or {}).get("hidden_files_after_publish")
            for log in logs
        ),
        str(logs)[:500],
    )

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
