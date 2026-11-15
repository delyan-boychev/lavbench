#!/usr/bin/env python3
"""Seed a running LavBench stack with realistic data for the UI visual check.

Creates one challenge with a stage, a scorable task with files, a long-running "live log"
task, three competitors (a 1.0 score, a lower score, a traceback), a platform-failure
submission, a jury member, and an empty challenge with its own competitor. Writes
seed.json plus the upload fixtures (an oversized notebook, a competitor CSV) to --out.

Needs a throwaway stack with an evaluation worker (see README.md) and, on the host,
pandas and pyarrow. Run from the repository root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import api_smoke_test as smoke  # noqa: E402
import pandas as pd  # noqa: E402

TASK_TITLE = "Binary classification warm-up"
LIVE_TASK_TITLE = "Live log demo"
STAGE_TITLE = "Round 1"
# The default cap (CELERY_TASK_SOFT_TIME_LIMIT minus 60 s), so the live run outlasts its scenarios
LIVE_TIME_LIMIT_SEC = 1140


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
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}
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


def create_task(
    api: smoke.Api,
    cid: str,
    stage_id: str,
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
            "stage_id": stage_id,
            "gpu_required": "false",
            "ram_limit_mb": "512",
            "time_limit_sec": str(time_limit),
            "base_docker_image": "python:3.12-slim",
            "pip_requirements": "pandas\npyarrow",
            "metrics_config": json.dumps({"accuracy": {"weight": 1.0, "higher_is_better": True}}),
            "public_eval_percentage": "50",
        },
        files,
    )
    if code != 201:
        raise SystemExit(f"task create failed: HTTP {code} {task}")
    return task["id"]


def wait_for_baseline(api: smoke.Api, tid: str, timeout: float = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, data = api.send("GET", f"/api/tasks/{tid}/submissions?baseline=true&page=1&per_page=1")
        rows = data.get("items", []) if isinstance(data, dict) else []
        if rows and rows[0].get("status") in ("completed", "failed"):
            return
        time.sleep(2)


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
            "title": "National AI Olympiad 2027: qualifier",
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
    # Fixed argv, no shell: the only variable part is the operator's container name
    out_proc = subprocess.run(  # noqa: S603
        ["docker", "exec", "-i", args.backend_container, "python", "-"],  # noqa: S607
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

    # Upload fixtures: a notebook over MAX_NOTEBOOK_BYTES and a competitor CSV
    big = json.loads(notebook(["print(1)\n"]))
    big["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": "x" * (17 * 1024 * 1024)}
    ]
    (out / "oversized.ipynb").write_text(json.dumps(big))
    (out / "competitors.csv").write_text(
        "name,surname,middle_name,birth_date,grade,school,city\n"
        "Ana,Koleva,M,2009-03-02,10,Ruse High School,Ruse\n"
        "Boris,Nikolov,K,2008-11-21,11,Pleven High School,Pleven\n"
    )

    seed = {
        "base": args.base,
        "cid": cid,
        "tid": tid,
        "live_tid": live_tid,
        "stage_id": stage_id,
        "admin": {"user": admin_user, "password": admin_pass},
        "competitors": comps,
        "jury": jury,
        "submissions": sub_ids,
        "infra_submission": infra_id,
        "aliases": [c["alias"] for c in comps],
        "task_title": TASK_TITLE,
        "live_task_title": LIVE_TASK_TITLE,
        "stage_title": STAGE_TITLE,
        "empty_cid": empty["id"],
        "empty_competitor": empty_comp,
    }
    (out / "seed.json").write_text(json.dumps(seed, indent=2))
    time.sleep(25)  # Let the beat rebuild the cached leaderboard
    print("seeded", cid, flush=True)  # noqa: T201


if __name__ == "__main__":
    main()
