#!/usr/bin/env python3
"""API-level end-to-end check of the admin, student and jury environment paths on `make dev-nanocolab`."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from api_smoke_test import FAIL, PASS, Api, check, read_admin_credentials, section

NOTEBOOK = json.dumps(
    {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{"cell_type": "code", "metadata": {}, "source": ["print('hello')"]}],
    }
).encode()


def iso(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def login(base: str, username: str, password: str) -> Api:
    api = Api(base)
    code, data = api.send("GET", "/api/auth/csrf-token")
    api.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    code, _ = api.send("POST", "/api/auth/login", {"username": username, "password": password})
    check(f"login {username}", code == 200)
    return api


def wait_for(api: Api, path: str, done, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    data: dict = {}
    while time.monotonic() < deadline:
        code, body = api.send("GET", path)
        data = body if isinstance(body, dict) else {}
        if code == 200 and done(data):
            return data
        if 400 <= code < 500:
            return data
        time.sleep(5)
    return data


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
    parser.add_argument("--origin", default="http://localhost:5173")
    parser.add_argument("--admin-credentials", default=".local-nanocolab/admin_credentials.txt")
    parser.add_argument("--ready-timeout", type=float, default=900.0)
    args = parser.parse_args()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    section("1. Admin setup")
    admin = login(args.base, *read_admin_credentials(args.admin_credentials))
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
    code, data = admin.multipart(
        "POST",
        f"/api/challenges/{cid}/tasks",
        {"title": "Image Classification", "stage_id": sid},
        {"baseline_notebook": ("baseline.ipynb", NOTEBOOK), "file0": ("train.csv", b"id,x\n1,2\n")},
    )
    tid = data.get("id", "") if isinstance(data, dict) else ""
    check(
        "create task, folder generated",
        code == 201 and isinstance(data, dict) and data.get("folder_name") == "image-classification",
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

    env_path = f"/api/challenges/{cid}/stages/{sid}/environment"
    code, data = admin.send("GET", env_path)
    check("environment defaults", code == 200 and isinstance(data, dict) and data["cpu_cores"] == 2)
    code, data = admin.send("PUT", env_path, {"enabled": True})
    eid = data.get("id", "") if isinstance(data, dict) else ""
    check("save environment once", code == 200 and bool(eid), str(data))
    if FAIL:
        print(f"\nSetup failed, stopping: {len(PASS)} passed, {len(FAIL)} failed")
        return 1
    data = wait_for(
        admin, env_path, lambda d: d["status"]["state"] in ("ready", "problem"), args.ready_timeout
    )
    check("package uploaded, draft ready", data.get("status", {}).get("state") == "ready", str(data))
    code, data = admin.send("POST", f"/api/challenges/{cid}/environments/{eid}/publish")
    check("publish", code == 200 and isinstance(data, dict) and bool(data.get("published_at")))
    data = wait_for(admin, env_path, lambda d: d["status"]["state"] == "ready", args.ready_timeout)
    check("nanoColab reports ready", data.get("status", {}).get("state") == "ready", str(data))

    section("2. Student")
    student = login(args.base, student_user, student_pass)
    code, data = student.send("GET", f"/api/tasks/{tid}/environment")
    check("task card status ready", code == 200 and isinstance(data, dict) and data["status"] == "ready")
    for attempt in ("first open", "re-entry"):
        started = time.monotonic()
        code, data = student.send("POST", f"/api/tasks/{tid}/environment/launch")
        check(f"launch token ({attempt})", code == 200 and isinstance(data, dict), str(data))
        if code == 200 and isinstance(data, dict):
            status = hub_launch(data, args.origin)
            check(f"Hub accepts the token ({attempt})", status in (302, 303), str(status))
        print(f"  {attempt}: {time.monotonic() - started:.1f} s")

    section("3. Jury")
    jury = login(args.base, jury_user, jury_pass)
    code, data = jury.send("GET", env_path)
    check("jury reads the status", code == 200 and isinstance(data, dict))
    code, data = jury.send("GET", f"/api/challenges/{cid}/environments/{eid}/workspaces")
    rows = data.get("workspaces", []) if isinstance(data, dict) else []
    check(
        "jury sees the workspace list by alias",
        code == 200 and any(r["opened"] and r["username"] is None for r in rows),
        str(data),
    )
    code, _ = jury.send("PUT", env_path, {"enabled": True})
    check("jury cannot change the environment", code == 403)

    section("4. Failure paths")
    code, data = admin.send(
        "POST",
        f"/api/challenges/{cid}/stages",
        {
            "title": "Overlapping",
            "start_time": iso(now + datetime.timedelta(minutes=30)),
            "end_time": iso(now + datetime.timedelta(hours=2)),
        },
    )
    second = data.get("id", "") if isinstance(data, dict) else ""
    code, data = admin.send("PUT", f"/api/challenges/{cid}/stages/{second}/environment", {"enabled": True})
    check("overlap refused", code == 409 and isinstance(data, dict) and data["code"] == "ERR_ENVIRONMENT_OVERLAP")
    code, data = admin.multipart("PUT", f"/api/tasks/{tid}", {}, {"file0": ("extra.csv", b"x")})
    check(
        "public file change after publish refused",
        code == 409 and isinstance(data, dict) and data["code"] == "ERR_TASK_FILES_LOCKED",
    )

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
