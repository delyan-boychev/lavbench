#!/usr/bin/env python3
"""Seed a running LavBench stack with realistic data for the UI visual check.

Creates one challenge with a stage, a scorable task with files, a long-running "live log"
task, two file-mode tasks (one with Hugging Face data, one with the emergency upload on and a
file submission through it), three competitors (a 1.0 score, a lower score, a traceback), a
platform-failure submission, a jury member, and an empty challenge with its own competitor.
When the stack has nanoColab on, it also seeds two competitions with workspace environments.
Writes seed.json plus the upload fixtures (an oversized notebook, a competitor CSV, a Hugging
Face ZIP) to --out.

Needs a throwaway stack with an evaluation worker (see README.md) and, on the host,
pandas and pyarrow. Run from the repository root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import api_smoke_test as smoke  # noqa: E402
import pandas as pd  # noqa: E402

CHALLENGE_TITLE = "National AI Olympiad 2027: qualifier"
TASK_TITLE = "Binary classification warm-up"
LIVE_TASK_TITLE = "Live log demo"
FILE_TASK_TITLE = "Tabular file task"
EMERGENCY_TASK_TITLE = "Emergency upload task"
STAGE_TITLE = "Round 1"
# The default cap (CELERY_TASK_SOFT_TIME_LIMIT minus 60 s), so the live run outlasts its scenarios
LIVE_TIME_LIMIT_SEC = 1140
WORKSPACE_TITLE = "Olympiad workspace trial"
WORKSPACE_PRACTICE_TITLE = "Workspace practice without stages"
# Titles share no phrase with the other seeded ones, so row and text lookups stay unambiguous
WORKSPACE_STAGES = {
    "closed": ("Closed warm-up stage", -180, -120),
    "live": ("Live workspace stage", -60, 24 * 60),
    "next": ("Upcoming workspace stage", 24 * 60 + 10, 48 * 60),
    "empty": ("Empty bonus stage", 48 * 60 + 10, 72 * 60),
}
WORKSPACE_TASKS = {
    "closed": "Earlier workspace task",
    "live": "Image classification",
    "next": "Text classification",
}
WORKSPACE_PRACTICE_TASK = "Practice workspace task"
WORKSPACE_WAIT_SEC = 600
# The multipart task request takes only these; data files stream one by one after it
FORM_FILE_FIELDS = {"baseline_notebook", "evaluator_script"}


def login(base: str, user: str, password: str) -> smoke.Api:
    api = smoke.Api(base)
    _, data = api.send("GET", "/api/auth/csrf-token")
    api.csrf = data.get("csrf_token", "")
    code, _ = api.send("POST", "/api/auth/login", {"username": user, "password": password})
    if code != 200:
        raise SystemExit(f"login failed for {user}: HTTP {code}")
    _, data = api.send("GET", "/api/auth/csrf-token")
    api.csrf = data.get("csrf_token", "")
    return api


def iso(delta: dt.timedelta) -> str:
    return (dt.datetime.now(dt.UTC) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def notebook(cells: list[str]) -> bytes:
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": [c],
                }
                for c in cells
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                }
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    ).encode()


def register(api: smoke.Api, cid: str, name: str, surname: str, school: str) -> dict:
    code, data = api.send(
        "POST",
        "/api/admin/register-competitor",
        {
            "name": name,
            "surname": surname,
            "middle_name": "A",
            "birth_date": "2009-05-14",
            "grade": "11",
            "school": school,
            "city": "Sofia",
            "challenge_id": cid,
        },
    )
    if code != 201:
        raise SystemExit(f"register-competitor failed: HTTP {code} {data}")
    return {
        "user": data["generated_username"],
        "password": data["generated_password"],
        "id": data["user"]["id"],
        "alias": data["user"].get("alias_id", ""),
    }


def upload_task_files(api: smoke.Api, tid: str, files: dict) -> None:
    """Stream each data file as the upload list does, labels.parquet first."""
    data = [(field, f) for field, f in files.items() if field not in FORM_FILE_FIELDS]
    data.sort(key=lambda item: item[1][0] != "labels.parquet")
    for field, (name, content) in data:
        visibility = "hidden" if field.startswith("hidden_") else "public"
        path = f"/api/tasks/{tid}/files/{urllib.parse.quote(name)}?visibility={visibility}"
        code, body = api.send("PUT", path, content, "application/octet-stream", timeout=120)
        if code != 200:
            raise SystemExit(f"task file upload {name} failed: HTTP {code} {body}")


def hf_zip() -> bytes:
    """A small Hugging Face ZIP with a model, a dataset and hidden entries that are skipped."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("models/demo-org/tiny-model/config.json", '{"model_type": "bert"}\n')
        zf.writestr("models/demo-org/tiny-model/.gitattributes", "*.bin filter=lfs\n")
        zf.writestr("datasets/demo-org/tiny-data/train.csv", "text,label\ngood,1\nbad,0\n")
        zf.writestr(".cache/huggingface/download/train.csv.lock", "")
    return buf.getvalue()


def upload_hf_zip(api: smoke.Api, tid: str, body: bytes) -> bool:
    """Give a task Hugging Face data; False when the stack has no such route yet."""
    code, data = api.send("PUT", f"/api/tasks/{tid}/hf-zip", body, "application/zip", timeout=120)
    if code in (404, 405):
        note = f"no Hugging Face ZIP route on this stack (HTTP {code}): no HF seed"
        print(note, flush=True)  # noqa: T201
        return False
    if code != 200:
        raise SystemExit(f"hf zip upload failed: HTTP {code} {data}")
    return True


def create_task(
    api: smoke.Api,
    cid: str,
    stage_id: str | None,
    title: str,
    description: str,
    time_limit: int,
    files: dict,
) -> str:
    code, task = api.multipart(
        "POST",
        f"/api/challenges/{cid}/tasks",
        {
            "title": title,
            "description": description,
            "stage_id": stage_id or "",
            "gpu_required": "false",
            "ram_limit_mb": "512",
            "time_limit_sec": str(time_limit),
            "base_docker_image": "python:3.12-slim",
            "pip_requirements": "pandas\npyarrow",
            "metrics_config": json.dumps({"accuracy": {"weight": 1.0, "higher_is_better": True}}),
            "public_eval_percentage": "50",
        },
        {field: f for field, f in files.items() if field in FORM_FILE_FIELDS},
    )
    if code != 201:
        raise SystemExit(f"task create failed: HTTP {code} {task}")
    upload_task_files(api, task["id"], files)
    return task["id"]


def create_file_task(api: smoke.Api, cid: str, stage_id: str, title: str, files: dict) -> str:
    """A file-mode task: scored from a submitted Parquet, with hidden labels and baseline."""
    code, task = api.multipart(
        "POST",
        f"/api/challenges/{cid}/tasks",
        {
            "title": title,
            "evaluation_mode": "file",
            "description": "Run your notebook in the workspace and submit submission.parquet.",
            "stage_id": stage_id,
            "metrics_config": json.dumps({"accuracy": {"weight": 1.0, "higher_is_better": True}}),
            "public_eval_percentage": "50",
        },
        {field: f for field, f in files.items() if field in FORM_FILE_FIELDS},
    )
    if code != 201:
        raise SystemExit(f"file task create failed: HTTP {code} {task}")
    upload_task_files(api, task["id"], files)
    return task["id"]


def wait_for_baseline(api: smoke.Api, tid: str, timeout: float = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, data = api.send("GET", f"/api/tasks/{tid}/submissions?baseline=true&page=1&per_page=1")
        rows = data.get("items", []) if isinstance(data, dict) else []
        if rows and rows[0].get("status") in ("completed", "failed"):
            return
        time.sleep(2)


def poll(fetch, done, timeout: float, every: float = 10) -> tuple[bool, object]:
    """Call fetch until done(result) holds or the timeout passes; return (done, last result)."""
    deadline = time.time() + timeout
    while True:
        result = fetch()
        if done(result):
            return True, result
        if time.time() >= deadline:
            return False, result
        time.sleep(every)


def answered(code: int) -> bool:
    """503 means nanoColab is still preparing and 429 a rate limit; other answers are final."""
    return code not in (429, 503)


def seed_workspaces(api: smoke.Api, base: str, cid: str, task_files: dict) -> dict | None:
    """Stage environments in every state a seeded stack reaches, and one without stages."""
    code, catalog = api.send("GET", "/api/environment/images")
    if code != 200 or not catalog.get("available"):
        reason = catalog.get("code") if isinstance(catalog, dict) else f"HTTP {code}"
        print(f"nanoColab is off on this stack ({reason}): no workspace seed", flush=True)  # noqa: T201
        return None
    images = catalog["images"]
    image = next((i for i in images if i.get("default")), images[0])["image_id"]
    setting = {
        "enabled": True,
        "image_id": image,
        "profile_id": catalog["profiles"][0]["id"],
        "workspace_gib": catalog["workspace_gib"]["default"],
        "auto_publish": False,
        "archive_until": None,
    }

    def create(title: str, hours_before: int, hours_after: int) -> str:
        code, ch = api.send(
            "POST",
            "/api/challenges",
            {
                "title": title,
                "description": "Students work in nanoColab workspaces.",
                "start_time": iso(-dt.timedelta(hours=hours_before)),
                "end_time": iso(dt.timedelta(hours=hours_after)),
                "timezone": "Europe/Sofia",
                "gpu_required": False,
                "max_eval_requests": 20,
            },
        )
        if code != 201:
            raise SystemExit(f"workspace challenge create failed: HTTP {code} {ch}")
        return ch["id"]

    wid = create(WORKSPACE_TITLE, 4, 73)
    stages = {}
    for key, (title, start, end) in WORKSPACE_STAGES.items():
        code, st = api.send(
            "POST",
            f"/api/challenges/{wid}/stages",
            {
                "title": title,
                "start_time": iso(dt.timedelta(minutes=start)),
                "end_time": iso(dt.timedelta(minutes=end)),
            },
        )
        if code != 201:
            raise SystemExit(f"workspace stage create failed: HTTP {code} {st}")
        stages[key] = st["id"]
    tasks = {
        key: create_task(api, wid, stages[key], title, "Work in your workspace.", 60, task_files)
        for key, title in WORKSPACE_TASKS.items()
    }
    # Published with the environment below, so its task form shows the HF data locked
    hf_live = upload_hf_zip(api, tasks["live"], hf_zip())
    bid = create(WORKSPACE_PRACTICE_TITLE, 1, 48)
    create_task(api, bid, None, WORKSPACE_PRACTICE_TASK, "Practice only.", 60, task_files)

    student = register(api, wid, "Nikol", "Hristova", "Sofia High School of Mathematics")
    practice_student = register(api, bid, "Kalin", "Todorov", "Ruse English Language School")
    code, data = api.send(
        "POST",
        "/api/admin/register-user",
        {
            "name": "Vera",
            "surname": "Kirova",
            "role": "jury",
            "jury_challenges": [wid, bid],
        },
    )
    if code != 201:
        raise SystemExit(f"workspace jury create failed: HTTP {code} {data}")
    jury = {"user": data["generated_username"], "password": data["generated_password"]}

    # The main competition saves the setting switched off, so its Workspaces view shows Off
    choices = (("main", cid, False), ("trial", wid, True), ("practice", bid, True))
    for key, challenge_id, enabled in choices:
        body = {"workspace": {**setting, "enabled": enabled}}
        code, data = api.send("PUT", f"/api/challenges/{challenge_id}", body)
        if code != 200:
            raise SystemExit(f"workspace setting {key} save failed: HTTP {code} {data}")

    def status(key: str):
        _, data = api.send("GET", f"/api/challenges/{wid}/environments")
        title = WORKSPACE_STAGES[key][0]
        rows = data.get("environments", []) if isinstance(data, dict) else []
        return next((row for row in rows if row["stage_title"] == title), None)

    def settled(env: object) -> bool:
        return isinstance(env, dict) and env["status"]["state"] in ("ready", "problem")

    _, env = poll(lambda: status("live"), settled, WORKSPACE_WAIT_SEC)
    published = False
    if isinstance(env, dict) and env["status"]["state"] == "ready":
        publish = f"/api/challenges/{wid}/environments/{env['id']}/publish"
        _, code = poll(lambda: api.send("POST", publish)[0], answered, WORKSPACE_WAIT_SEC)
        published = code == 200
    launched = False
    if published:
        sapi = login(base, student["user"], student["password"])
        launch = f"/api/tasks/{tasks['live']}/environment/launch"
        _, code = poll(lambda: sapi.send("POST", launch)[0], answered, WORKSPACE_WAIT_SEC, 15)
        launched = code == 200
    poll(lambda: status("next"), settled, 120)
    print(f"workspaces: published={published} launched={launched}", flush=True)  # noqa: T201
    return {
        "cid": wid,
        "practice_cid": bid,
        "challenge_title": WORKSPACE_TITLE,
        "main_title": CHALLENGE_TITLE,
        "practice_title": WORKSPACE_PRACTICE_TITLE,
        "stages": {key: title for key, (title, _, _) in WORKSPACE_STAGES.items()},
        "tasks": WORKSPACE_TASKS,
        "practice_task": WORKSPACE_PRACTICE_TASK,
        "published": published,
        "launched": launched,
        "hf_task": WORKSPACE_TASKS["live"] if hf_live else None,
        "competitor": student,
        "practice_competitor": practice_student,
        "jury": jury,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:80")
    ap.add_argument("--admin-credentials", default=str(ROOT / "admin_credentials.txt"))
    ap.add_argument("--out", required=True, help="output directory (seed.json and fixtures)")
    ap.add_argument("--backend-container", default="lavbench_backend")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    admin_user, admin_pass = smoke.read_admin_credentials(args.admin_credentials)
    api = login(args.base, admin_user, admin_pass)

    code, ch = api.send(
        "POST",
        "/api/challenges",
        {
            "title": CHALLENGE_TITLE,
            "description": "Qualifying round of the national olympiad in artificial intelligence.",
            "start_time": iso(-dt.timedelta(hours=2)),
            "end_time": iso(dt.timedelta(days=2)),
            "timezone": "Europe/Sofia",
            "gpu_required": False,
            "max_eval_requests": 20,
        },
    )
    if code != 201:
        raise SystemExit(f"challenge create failed: HTTP {code} {ch}")
    cid = ch["id"]
    code, st = api.send(
        "POST",
        f"/api/challenges/{cid}/stages",
        {
            "title": STAGE_TITLE,
            "start_time": iso(-dt.timedelta(hours=1)),
            "end_time": iso(dt.timedelta(days=1)),
        },
    )
    if code != 201:
        raise SystemExit(f"stage create failed: HTTP {code} {st}")
    stage_id = st["id"]

    labels = pd.DataFrame({"id": list(range(1, 11)), "label": [0, 1, 0, 1, 0, 1, 1, 0, 0, 1]})
    labels_buf = io.BytesIO()
    labels.to_parquet(labels_buf, index=False)
    train_csv = "id,feature_a,feature_b,label\n" + "\n".join(
        f"{i},{i * 0.5:.1f},{(i % 3) * 1.5:.1f},{i % 2}" for i in range(1, 41)
    )
    baseline = notebook(
        [
            "import pandas as pd\n"
            "pd.DataFrame({'id': list(range(1, 11)), 'label': [0] * 10})"
            ".to_parquet('submission.parquet')\n"
        ]
    )
    tid = create_task(
        api,
        cid,
        stage_id,
        TASK_TITLE,
        "## Task\n\nPredict the binary `label` for each `id`.\n\n"
        "- Training data: `train.csv`\n- Submit `submission.parquet` with columns `id`, `label`\n\n"
        "Scoring uses **accuracy** on a hidden split.",
        60,
        {
            "baseline_notebook": ("baseline.ipynb", baseline),
            "file0": ("labels.parquet", labels_buf.getvalue()),
            "file1": ("train.csv", train_csv.encode()),
        },
    )
    live_tid = create_task(
        api,
        cid,
        stage_id,
        LIVE_TASK_TITLE,
        "Streams a progress line every 3 s.",
        LIVE_TIME_LIMIT_SEC,
        {
            "baseline_notebook": ("baseline.ipynb", baseline),
            "file0": ("labels.parquet", labels_buf.getvalue()),
        },
    )

    labels_bytes = labels_buf.getvalue()
    file_task_files = {
        "file0": ("train.csv", train_csv.encode()),
        "hidden_file0": ("labels.parquet", labels_bytes),
        "hidden_file1": ("baseline_submission.parquet", labels_bytes),
    }
    file_tid = create_file_task(api, cid, stage_id, FILE_TASK_TITLE, file_task_files)
    hf_seeded = upload_hf_zip(api, file_tid, hf_zip())
    emergency_tid = create_file_task(
        api,
        cid,
        stage_id,
        EMERGENCY_TASK_TITLE,
        {**file_task_files, "baseline_notebook": ("solution.ipynb", baseline)},
    )
    code, data = api.send(
        "PUT",
        f"/api/tasks/{emergency_tid}/emergency-upload",
        {"enabled": True, "reason": "UI check: nanoColab outage drill"},
    )
    if code != 200:
        raise SystemExit(f"emergency switch failed: HTTP {code} {data}")

    comps = [
        register(api, cid, *person)
        for person in (
            ("Maria", "Ivanova", "Sofia High School of Mathematics"),
            ("Georgi", "Petrov", "Plovdiv English Language School"),
            ("Elena", "Dimitrova", "Varna Natural Sciences School"),
        )
    ]
    code, data = api.send(
        "POST",
        "/api/admin/register-user",
        {"name": "Ivan", "surname": "Jurov", "role": "jury", "jury_challenges": [cid]},
    )
    if code != 201:
        raise SystemExit(f"jury create failed: HTTP {code} {data}")
    jury = {"user": data["generated_username"], "password": data["generated_password"]}

    wait_for_baseline(api, tid)
    sources = [
        "import pandas as pd\npd.DataFrame({'id': list(range(1, 11)), "
        "'label': [0, 1, 0, 1, 0, 1, 1, 0, 0, 1]}).to_parquet('submission.parquet')\n",
        "import pandas as pd\npd.DataFrame({'id': list(range(1, 11)), "
        "'label': [0, 1, 0, 1, 1, 0, 1, 0, 1, 1]}).to_parquet('submission.parquet')\n",
        "raise ValueError('feature_c is missing from train.csv')\n",
    ]
    sub_ids = []
    for comp, src in zip(comps, sources, strict=True):
        capi = login(args.base, comp["user"], comp["password"])
        ok, sub = smoke.submit_and_poll(capi, api, cid, tid, src, poll_timeout=600)
        print(comp["user"], ok, sub.get("status"), sub.get("public_score"), flush=True)  # noqa: T201
        sub_ids.append(sub.get("id"))

    # A file submission through the emergency upload, scored like a workspace one
    wait_for_baseline(api, emergency_tid)
    capi = login(args.base, comps[0]["user"], comps[0]["password"])
    answer = pd.DataFrame({"id": list(range(1, 11)), "label": [0, 1, 0, 1, 0, 1, 1, 0, 0, 0]})
    answer_buf = io.BytesIO()
    answer.to_parquet(answer_buf, index=False)
    code, data = capi.multipart(
        "POST",
        f"/api/tasks/{emergency_tid}/submit-file",
        {},
        {
            "submission": ("submission.parquet", answer_buf.getvalue()),
            "notebook": ("solution.ipynb", baseline),
        },
    )
    if code != 202:
        raise SystemExit(f"emergency upload failed: HTTP {code} {data}")
    file_sub_id = data["submission_id"]
    poll(
        lambda: api.send("GET", f"/api/submissions/{file_sub_id}")[1],
        lambda sub: isinstance(sub, dict) and sub.get("status") in ("completed", "failed"),
        timeout=300,
        every=2,
    )

    # A platform failure, recorded the way the watchdog records one
    infra_py = (
        "from app import create_app\nfrom models import Submission, db\n"
        "from utils.dates import utcnow\napp = create_app()\nwith app.app_context():\n"
        f"    s = Submission(user_id='{comps[0]['id']}', challenge_id='{cid}', task_id='{tid}',\n"
        "        status='failed', detailed_status='failed_infra', code_cells='[]',\n"
        "        logs='[WATCHDOG] Submission timed out - never picked up by a worker"
        " (1h+ queued).',\n"
        "        created_at=utcnow())\n    db.session.add(s); db.session.commit(); print(s.id)\n"
    )
    # No shell: UI_CHECK_BACKEND_EXEC (set by the operator) replaces docker exec on a host-run backend
    backend_exec = os.environ.get("UI_CHECK_BACKEND_EXEC", "")
    command = shlex.split(backend_exec) or [
        "docker",
        "exec",
        "-i",
        args.backend_container,
        "python",
        "-",
    ]
    out_proc = subprocess.run(  # noqa: S603
        command,
        input=infra_py,
        capture_output=True,
        text=True,
        check=True,
    )
    infra_id = out_proc.stdout.strip().splitlines()[-1]

    # An empty challenge with its own competitor, for the empty states
    code, empty = api.send(
        "POST",
        "/api/challenges",
        {
            "title": "Autumn practice round",
            "description": "No tasks yet.",
            "start_time": iso(-dt.timedelta(hours=1)),
            "end_time": iso(dt.timedelta(days=3)),
            "timezone": "Europe/Sofia",
            "gpu_required": False,
        },
    )
    if code != 201:
        raise SystemExit(f"empty challenge create failed: HTTP {code} {empty}")
    empty_comp = register(api, empty["id"], "Petar", "Stoyanov", "Burgas Mathematics School")

    # A jury member of both competitions: the competitor list follows the selected one
    code, data = api.send(
        "POST",
        "/api/admin/register-user",
        {
            "name": "Vera",
            "surname": "Koleva",
            "role": "jury",
            "jury_challenges": [cid, empty["id"]],
        },
    )
    if code != 201:
        raise SystemExit(f"second jury create failed: HTTP {code} {data}")
    multi_jury = {"user": data["generated_username"], "password": data["generated_password"]}

    # Manual points changed from 7 to 7.25, so the audit log shows the decimals
    for points in (7, 7.25):
        code, data = api.send(
            "POST",
            f"/api/challenges/{cid}/manual-points",
            {"user_id": comps[1]["id"], "points": {tid: points}},
        )
        if code != 200:
            raise SystemExit(f"manual points failed: HTTP {code} {data}")

    # Upload fixtures: a notebook over MAX_NOTEBOOK_BYTES and a competitor CSV
    big = json.loads(notebook(["print(1)\n"]))
    big["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": "x" * (17 * 1024 * 1024)}
    ]
    (out / "oversized.ipynb").write_text(json.dumps(big))
    # A labels.parquet with a repeated id, which the task form must refuse
    (out / "dup").mkdir(exist_ok=True)
    pd.DataFrame({"id": [1, 1, 2], "label": [0, 1, 0]}).to_parquet(
        out / "dup" / "labels.parquet", index=False
    )
    # The ZIP the task form scenarios pick
    (out / "hf").mkdir(exist_ok=True)
    (out / "hf" / "hf-data.zip").write_bytes(hf_zip())
    (out / "competitors.csv").write_text(
        "name,surname,middle_name,birth_date,grade,school,city\n"
        "Ana,Koleva,M,2009-03-02,10,Ruse High School,Ruse\n"
        "Boris,Nikolov,K,2008-11-21,11,Pleven High School,Pleven\n"
    )

    workspace_files = {
        "baseline_notebook": ("baseline.ipynb", baseline),
        "file0": ("labels.parquet", labels_buf.getvalue()),
        "file1": ("train.csv", train_csv.encode()),
    }
    workspaces = seed_workspaces(api, args.base, cid, workspace_files)

    seed = {
        "base": args.base,
        "cid": cid,
        "tid": tid,
        "live_tid": live_tid,
        "stage_id": stage_id,
        "admin": {"user": admin_user, "password": admin_pass},
        "competitors": comps,
        "jury": jury,
        "multi_jury": multi_jury,
        "submissions": sub_ids,
        "infra_submission": infra_id,
        "aliases": [c["alias"] for c in comps],
        "challenge_title": CHALLENGE_TITLE,
        "task_title": TASK_TITLE,
        "live_task_title": LIVE_TASK_TITLE,
        "file_tid": file_tid,
        "file_task_title": FILE_TASK_TITLE,
        "emergency_tid": emergency_tid,
        "emergency_task_title": EMERGENCY_TASK_TITLE,
        "file_submission": file_sub_id,
        "hf_task_title": FILE_TASK_TITLE if hf_seeded else None,
        "stage_title": STAGE_TITLE,
        "empty_cid": empty["id"],
        "empty_competitor": empty_comp,
        "workspaces": workspaces,
    }
    if workspaces:
        # The capture logs these roles in by their seed keys
        seed["ws_competitor"] = workspaces["competitor"]
        seed["ws_practice_competitor"] = workspaces["practice_competitor"]
        seed["ws_jury"] = workspaces["jury"]
    (out / "seed.json").write_text(json.dumps(seed, indent=2))
    time.sleep(25)  # Let the beat rebuild the cached leaderboard
    print("seeded", cid, flush=True)  # noqa: T201


if __name__ == "__main__":
    main()
