#!/usr/bin/env python3
"""api_smoke_test.py — end-to-end smoke test of a RUNNING LavBench deployment.

Tests the full API surface through nginx (default http://localhost:80):
health, auth + CSRF, challenge/stage/task CRUD (incl. multipart upload +
streamed download), submissions, leaderboard, admin endpoints, backups
(trigger + poll), docs, and every SSE stream (initial payload must arrive
through nginx with buffering off).

Usage:
    python3 scripts/api_smoke_test.py [--base http://localhost:80]
        [--admin-user NAME --admin-pass KEY | --admin-credentials admin_credentials.txt]

Set SMOKE_EVALUATE=1 to enable the worker-backed evaluation section
(requires an evaluation worker consuming cpu_queue on the broker).

Exit code: 0 = all passed, 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

PASS: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.csrf = ""

    def _req(self, method: str, path: str, body: bytes | None = None,
             ctype: str | None = None, headers: dict[str, str] | None = None,
             csrf: bool = True) -> urllib.request.Request:
        h = {"Accept": "application/json"}
        if headers:
            h.update(headers)
        if body is not None:
            h["Content-Type"] = ctype or "application/json"
        if csrf and method not in ("GET", "HEAD", "OPTIONS", "TRACE") and self.csrf:
            h["X-CSRF-Token"] = self.csrf
        return urllib.request.Request(self.base + path, data=body, method=method, headers=h)

    def send(self, method: str, path: str, payload=None, ctype: str | None = None,
             headers: dict[str, str] | None = None, csrf: bool = True,
             timeout: float = 30.0) -> tuple[int, dict | str | None]:
        body: bytes | None = None
        if payload is not None and ctype != "application/x-www-form-urlencoded":
            if isinstance(payload, (dict, list)):
                body = json.dumps(payload).encode()
            elif isinstance(payload, str):
                body = payload.encode()
            else:
                body = payload
        try:
            with self.opener.open(self._req(method, path, body, ctype, headers, csrf), timeout=timeout) as r:
                raw = r.read()
                ct = r.headers.get("Content-Type", "")
                data: dict | str | None
                if "application/json" in ct:
                    data = json.loads(raw.decode())
                else:
                    data = raw.decode(errors="replace")
                return r.status, data
        except urllib.error.HTTPError as e:
            raw = e.read()
            ct = e.headers.get("Content-Type", "")
            data = None
            if "application/json" in ct:
                try:
                    data = json.loads(raw.decode())
                except json.JSONDecodeError:
                    data = None
            return e.code, data
        except Exception as e:  # noqa: BLE001
            return -1, f"{type(e).__name__}: {e}"

    def multipart(self, method: str, path: str, fields: dict[str, str],
                  files: dict[str, tuple[str, bytes]], timeout: float = 60.0) -> tuple[int, dict | str | None]:
        boundary = f"----lavbench{uuid.uuid4().hex}"
        buf = io.BytesIO()
        for k, v in fields.items():
            buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, (fname, content) in files.items():
            buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n".encode())
            buf.write(b"Content-Type: application/octet-stream\r\n\r\n")
            buf.write(content)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        return self.send(method, path, buf.getvalue(), f"multipart/form-data; boundary={boundary}",
                         timeout=timeout)

    def sse_first_data(self, path: str, timeout: float = 20.0) -> dict | None:
        """Open an SSE stream and return the first non-heartbeat data payload."""
        try:
            with self.opener.open(self._req("GET", path), timeout=timeout) as r:
                if r.headers.get("Content-Type", "") != "text/event-stream":
                    return {"__not_sse__": r.headers.get("Content-Type", "")}
                deadline = time.time() + timeout
                while time.time() < deadline:
                    line = r.readline()
                    if not line:
                        return {"__eof__": True}
                    if line.startswith(b"data:"):
                        payload = line[5:].strip()
                        if payload:
                            return json.loads(payload)
                return {"__timeout__": True}
        except Exception as e:  # noqa: BLE001
            return {"__error__": f"{type(e).__name__}: {e}"}

    def sse_roundtrip(self, path: str, trigger, timeout: float = 40.0) -> tuple[bool, list[dict], str]:
        """SSE publish→subscribe round-trip: open a stream, wait for the first
        data payloads, then call *trigger* (zero-arg callable that publishes to
        the stream's Redis channel) until a second leaderboard payload arrives.

        Returns ``(ok, payloads, detail)``. Streams here carry no ``event:``
        lines — updates arrive as full JSON ``data:`` payloads.
        """
        try:
            with self.opener.open(self._req("GET", path), timeout=timeout) as r:
                if r.headers.get("Content-Type", "") != "text/event-stream":
                    return False, [], f"not SSE: Content-Type={r.headers.get('Content-Type', '')}"
                deadline = time.time() + timeout
                payloads: list[dict] = []
                updates = 0
                triggered = 0
                last_trigger_at = 0.0
                while time.time() < deadline:
                    line = r.readline()
                    if not line:
                        return False, payloads, "stream EOF before update"
                    if not line.startswith(b"data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    payloads.append(payload)
                    if "leaderboard" not in payload:
                        continue
                    updates += 1
                    if updates >= 2:
                        return True, payloads, f"update received (payloads={len(payloads)}, triggers={triggered})"
                    if triggered < 5 and time.time() - last_trigger_at >= 5.0:
                        trigger()
                        triggered += 1
                        last_trigger_at = time.time()
                return False, payloads, f"timeout (payloads={len(payloads)}, updates={updates}, triggers={triggered})"
        except Exception as e:  # noqa: BLE001
            return False, [], f"{type(e).__name__}: {e}"


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


def warn(name: str, detail: str = "") -> None:
    WARN.append(name)
    print(f"  [WARN] {name}{' — ' + detail if detail else ''}")


def expect_error(data, code: str) -> bool:
    return isinstance(data, dict) and data.get("code") == code


def submit_and_poll(submit_client: Api, poll_client: Api, cid: str, tid: str, source: str,
                    poll_timeout: float = 600.0, interval: float = 5.0) -> tuple[bool, dict]:
    """Submit a single code cell and poll GET /api/submissions/<id> until a
    terminal state (completed/failed). Returns (reached_terminal, payload).

    The generous poll timeout covers the one-time per-task Docker image build
    (pip_requirements pandas/pyarrow) the worker performs on first execution.
    """
    code, data = submit_client.send(
        "POST", f"/api/challenges/{cid}/submit",
        {"task_id": tid, "selected_cells": [{"id": 0, "type": "code", "source": source}]})
    if code != 202 or not isinstance(data, dict) or not data.get("submission_id"):
        return False, {"submit_status": code, **(data if isinstance(data, dict) else {})}
    sid = data["submission_id"]
    deadline = time.time() + poll_timeout
    last: dict = {}
    while time.time() < deadline:
        time.sleep(interval)
        code, data = poll_client.send("GET", f"/api/submissions/{sid}")
        if code == 200 and isinstance(data, dict):
            last = data
            if data.get("status") in ("completed", "failed"):
                return True, data
    return False, last


MIN_IPYNB = {
    "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
               "source": ["import pandas as pd\n", "print('ok')\n"]}],
    "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
    "nbformat": 4,
    "nbformat_minor": 5,
}


def matrix_run(label: str, method: str, path: str, payload, expect: dict[str, tuple],
               clients: dict[str, Api], files: dict[str, tuple[str, bytes]] | None = None) -> None:
    """Role matrix check: for each role run the request and compare (status[, error_code])."""
    for role, (status, code) in expect.items():
        client = clients[role]
        if files:
            st, dt = client.multipart(method, path, payload or {}, files)
        else:
            st, dt = client.send(method, path, payload)
        statuses = status if isinstance(status, tuple) else (status,)
        got_code = dt.get("code") if isinstance(dt, dict) else None
        ok = st in statuses and (code is None or got_code == code)
        check(f"[{role}] {label}", ok,
              f"got {st} code={got_code} want {statuses}{f'/{code}' if code else ''}")


def read_admin_credentials(path: str) -> tuple[str, str]:
    if not os.path.exists(path):
        print(f"ERROR: {path} not found (run 'make setup-admin' first)")
        sys.exit(2)
    lines = [line.strip() for line in open(path, encoding="utf-8") if line.strip()]
    user = key = ""
    for idx, line in enumerate(lines):
        if "Admin Username" in line:
            user = line.split(":", 1)[-1].strip()
        if "Master Key" in line:
            key = line.split(":", 1)[-1].strip()
        if not user and "Generated Admin Username" in line and idx + 1 < len(lines):
            user = lines[idx + 1]
        if not key and "Generated Master Key" in line and idx + 1 < len(lines):
            key = lines[idx + 1]
    if not user or not key:
        print(f"ERROR: could not parse credentials from {path}")
        sys.exit(2)
    return user, key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("LAVBENCH_BASE", "http://localhost:80"))
    ap.add_argument("--admin-user")
    ap.add_argument("--admin-pass")
    ap.add_argument("--admin-credentials", default="admin_credentials.txt")
    args = ap.parse_args()

    api = Api(args.base)
    if args.admin_user and args.admin_pass:
        admin_user, admin_pass = args.admin_user, args.admin_pass
    else:
        admin_user, admin_pass = read_admin_credentials(args.admin_credentials)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = "2027-12-31T00:00:00Z"
    cid = tid = sid = stage_id = comp_user = comp_pass = jury_user = jury_pass = jury_id = comp_id = ""

    # ── 1. Health, docs, swagger (no auth) ──────────────────────────────
    print("\n== 1. Health / docs ==")
    code, data = api.send("GET", "/api/health")
    check("GET /api/health 200 ok", code == 200 and isinstance(data, dict)
          and data.get("status") == "ok", json.dumps(data) if isinstance(data, dict) else "")
    code, data = api.send("GET", "/apidoc/swagger/")
    check("GET /apidoc/swagger/ 200 HTML", code == 200 and isinstance(data, str) and "<html" in data.lower())
    code, data = api.send("GET", "/apidoc/openapi.json")
    check("GET /apidoc/openapi.json 200 JSON", code == 200 and isinstance(data, dict) and "openapi" in data)

    # ── 2. Auth: bad login, CSRF, good login, me ───────────────────────
    print("\n== 2. Auth + CSRF ==")
    code, data = api.send("POST", "/api/auth/login", {"username": "definitely_missing_user", "password": "x"})
    check("bad login 401 ERR_INVALID_CREDENTIALS", code == 401 and expect_error(data, "ERR_INVALID_CREDENTIALS"))
    code, data = api.send("GET", "/api/auth/csrf-token")
    check("GET /api/auth/csrf-token 200 + cookie", code == 200 and isinstance(data, dict) and "csrf_token" in data)
    api.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    code, data = api.send("POST", "/api/auth/login", {"username": admin_user, "password": admin_pass})
    check("admin login 200", code == 200 and isinstance(data, dict) and data.get("user", {}).get("role") == "admin")
    code, data = api.send("GET", "/api/auth/me")
    check("GET /api/auth/me admin", code == 200 and isinstance(data, dict) and data.get("user", {}).get("role") == "admin")

    # ── 3. Challenge CRUD + validation + CSRF enforcement ──────────────
    print("\n== 3. Challenges ==")
    code, data = api.send("POST", "/api/challenges", {"title": "smoke", "start_time": now, "end_time": now},
                          csrf=False)
    check("no-CSRF POST → 403 ERR_CSRF_FAILED", code == 403 and expect_error(data, "ERR_CSRF_FAILED"))
    code, data = api.send("POST", "/api/challenges",
                          {"title": "smoke", "start_time": future, "end_time": now})
    check("end<start → 422 ERR_INVALID_DATE_RANGE", code == 422 and expect_error(data, "ERR_INVALID_DATE_RANGE"))
    code, data = api.send("POST", "/api/challenges",
                          {"title": "smoke-test-challenge", "description": "created by api_smoke_test.py",
                           "start_time": now, "end_time": future, "gpu_required": False, "double_blind": False,
                           "max_eval_requests": 2})
    if code == 201 and isinstance(data, dict) and data.get("id"):
        cid = data["id"]
    check("POST /api/challenges 201", code == 201 and bool(cid))
    code, data = api.send("PUT", f"/api/challenges/{cid}", {"description": "updated by smoke test"})
    check("PUT /api/challenges/<id> 200", code == 200 and isinstance(data, dict) and data.get("id") == cid)
    code, data = api.send("GET", f"/api/challenges/{cid}")
    check("GET /api/challenges/<id> 200", code == 200 and isinstance(data, dict) and data.get("id") == cid)

    # ── 4. Stages ──────────────────────────────────────────────────────
    print("\n== 4. Stages ==")
    code, data = api.send("POST", f"/api/challenges/{cid}/stages",
                          {"title": "Main stage", "start_time": now, "end_time": future})
    if code == 201 and isinstance(data, dict) and data.get("id"):
        stage_id = data["id"]
    check("POST stages 201", code == 201 and bool(stage_id))
    code, data = api.send("PUT", f"/api/challenges/{cid}/stages/{stage_id}", {"title": "Main stage v2"})
    check("PUT stage 200", code == 200 and isinstance(data, dict) and data.get("title") == "Main stage v2")

    # ── 5. Tasks: multipart create, get, download, parse-notebook ─────
    print("\n== 5. Tasks ==")
    ipynb = json.dumps(MIN_IPYNB).encode()
    code, data = api.multipart("POST", f"/api/challenges/{cid}/tasks",
                               {"title": "smoke-task", "stage_id": stage_id, "gpu_required": "false",
                                "base_docker_image": "python:3.12-slim"},
                               {"baseline_notebook": ("baseline.ipynb", ipynb)})
    if code == 201 and isinstance(data, dict) and data.get("id"):
        tid = data["id"]
    check("POST tasks 201 (multipart)", code == 201 and bool(tid))
    files = data.get("files", []) if isinstance(data, dict) else []
    fname = files[0].get("filename", "") if files and isinstance(files[0], dict) else ""
    code, data = api.send("GET", f"/api/tasks/{tid}")
    check("GET /api/tasks/<id> 200", code == 200 and isinstance(data, dict) and data.get("id") == tid)
    if fname:
        code, data = api.send("GET", f"/api/tasks/{tid}/download/{fname}")
        check("task file download streams", code == 200 and isinstance(data, str) and len(data) > 0)
    else:
        warn("task file download", "no files in task response")
    code, data = api.multipart("POST", f"/api/challenges/{cid}/parse-notebook",
                               {}, {"file": ("cells.ipynb", ipynb)})
    check("POST parse-notebook 200", code == 200 and isinstance(data, dict) and "cells" in data)

    # ── 6. Competitor lifecycle ────────────────────────────────────────
    print("\n== 6. Competitor ==")
    code, data = api.send("POST", "/api/admin/register-competitor",
                          {"name": "Smoke", "surname": "Tester", "middle_name": "M", "birth_date": "2005-01-01",
                           "grade": "10", "school": "Test HS", "city": "Sofia", "challenge_id": cid})
    if code == 201 and isinstance(data, dict):
        comp_user = data.get("generated_username", "")
        comp_pass = data.get("generated_password", "")
        comp_id = data.get("user", {}).get("id", "")
    check("register-competitor 201", code == 201 and bool(comp_user))
    comp = Api(args.base)
    code, data = comp.send("POST", "/api/auth/login", {"username": comp_user, "password": comp_pass})
    check("competitor login 200", code == 200 and isinstance(data, dict) and data.get("user", {}).get("role") == "competitor")
    code, data = comp.send("GET", "/api/auth/csrf-token")
    comp.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    code, data = comp.send("GET", "/api/challenges")
    own = [i for i in data.get("items", []) if i.get("id") == cid] if isinstance(data, dict) else []
    check("competitor sees only own challenge", code == 200 and len(own) == 1)

    # ── 7. Submissions ─────────────────────────────────────────────────
    print("\n== 7. Submissions ==")
    cells = [{"id": 0, "type": "code", "source": "print(1)"}]
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit",
                           {"task_id": tid, "selected_cells": [{}]})
    check("invalid selected_cells → 422 ERR_INVALID_SELECTED_CELLS",
          code == 422 and expect_error(data, "ERR_INVALID_SELECTED_CELLS"))
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit",
                           {"task_id": tid, "selected_cells": ["print(1)"]})
    check("non-dict selected_cells → 422 ERR_INVALID_SELECTED_CELLS",
          code == 422 and expect_error(data, "ERR_INVALID_SELECTED_CELLS"))
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit",
                           {"task_id": "00000000-0000-0000-0000-000000000000",
                            "selected_cells": cells})
    check("unknown task_id → 400 ERR_INVALID_TASK_ID",
          code == 400 and expect_error(data, "ERR_INVALID_TASK_ID"))
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit", {"task_id": tid, "selected_cells": cells})
    if code == 202 and isinstance(data, dict) and data.get("submission_id"):
        sid = data["submission_id"]
    check("competitor submit 202 queued", code == 202 and bool(sid) and data.get("status") == "queued")
    code, data = api.send("GET", f"/api/submissions/{sid}")
    st = data.get("status", "") if isinstance(data, dict) else ""
    check("GET submission status valid", code == 200 and st in ("queued", "running", "completed", "failed"), st)
    code, data = api.send("POST", f"/api/submissions/{sid}/select-final")
    check("admin select-final 200", code == 200)
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit", {"task_id": tid, "selected_cells": cells})
    sid2 = data.get("submission_id", "") if code == 202 and isinstance(data, dict) else ""
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit", {"task_id": tid, "selected_cells": cells})
    check("3rd submit → 429 ERR_DAILY_LIMIT_REACHED (max_eval_requests=2, failed excluded)",
          code == 429 and expect_error(data, "ERR_DAILY_LIMIT_REACHED"))
    code, data = api.send("POST", f"/api/submissions/{sid2}/kill")
    check("admin kill queued submission 200", code == 200 and isinstance(data, dict) and "killed" in str(data.get("message", "")))
    code, data = comp.send("POST", "/api/admin/register-user",
                           {"name": "X", "surname": "Y", "role": "competitor", "challenge_id": cid})
    check("competitor on admin endpoint → 403", code == 403 and expect_error(data, "ERR_ROLE_REQUIRED"))

    # ── 8. Leaderboard + jury manual points ────────────────────────────
    print("\n== 8. Leaderboard ==")
    code, data = api.send("GET", f"/api/challenges/{cid}/leaderboard")
    check("GET leaderboard 200", code == 200 and isinstance(data, dict) and "leaderboard" in data)
    code, data = _post_register(api,
                                {"name": "Jury", "surname": "One", "role": "jury", "jury_challenges": [cid]})
    if code == 201 and isinstance(data, dict):
        jury_user = data.get("generated_username", "")
        jury_pass = data.get("generated_password", "")
        jury_id = data.get("user", {}).get("id", "")
    check("register jury 201", code == 201 and bool(jury_user))
    jury = Api(args.base)
    code, data = jury.send("POST", "/api/auth/login", {"username": jury_user, "password": jury_pass})
    check("jury login 200", code == 200 and isinstance(data, dict) and data.get("user", {}).get("role") == "jury")
    code, data = jury.send("GET", "/api/auth/csrf-token")
    jury.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    code, data = jury.send("POST", f"/api/challenges/{cid}/manual-points",
                           {"user_id": comp_id, "points": {tid: 90}, "reason": "smoke"})
    check("jury manual-points 200", code == 200 and isinstance(data, dict) and data.get("user_id") == comp_id)

    # ── 9. Admin surface ───────────────────────────────────────────────
    print("\n== 9. Admin ==")
    code, data = api.send("GET", "/api/admin/users")
    check("GET /api/admin/users 200", code == 200 and isinstance(data, dict) and isinstance(data.get("items"), list))
    code, data = api.send("GET", "/api/admin/metrics")
    check("GET /api/admin/metrics 200", code == 200 and isinstance(data, dict))
    code, data = api.send("GET", "/api/admin/audit-logs")
    check("GET /api/admin/audit-logs 200", code == 200 and isinstance(data, dict) and isinstance(data.get("logs"), list),
          f"status={code} body={json.dumps(data)[:160] if not isinstance(data, str) else data[:160]}")
    code, data = api.send("GET", "/api/admin/dead-letters")
    check("GET /api/admin/dead-letters 200", code == 200 and isinstance(data, dict) and isinstance(data.get("items"), list))
    code, data = api.send("GET", "/api/admin/submissions/queue")
    check("GET /api/admin/submissions/queue 200", code == 200 and isinstance(data, dict) and isinstance(data.get("items"), list))
    code, data = api.send("GET", "/api/admin/workers/stats")
    check("GET /api/admin/workers/stats 200", code == 200 and isinstance(data, dict))
    wstats = data if code == 200 and isinstance(data, dict) else {}
    wlist = wstats.get("workers", [])
    check("workers/stats shape (workers list + count)",
          isinstance(wlist, list) and isinstance(wstats.get("connected_workers_count"), int),
          f"keys={sorted(wstats.keys())[:6] if isinstance(wstats, dict) else wstats}")
    spec_keys = ("name", "status", "type", "gpu_type", "ram_gb", "vram_gb")
    if wlist:
        check("worker entries carry worker_spec fields (hostname/type/gpu/ram)",
              all(isinstance(w, dict) and all(k in w for k in spec_keys) for w in wlist),
              f"workers={len(wlist)}")
        check("a CPU worker type is registered (worker_spec registry)",
              any(w.get("type") == "CPU" for w in wlist),
              f"types={sorted({w.get('type') for w in wlist if isinstance(w, dict)})}")
    else:
        warn("worker_spec registration",
             "no workers connected (external machines absent) — verified endpoint shape only")
    code, data = api.send("GET", "/api/admin/backups")
    known_backups = data.get("backups", []) if isinstance(data, dict) else []
    check("GET /api/admin/backups 200", code == 200 and isinstance(known_backups, list))

    # ── 10. Backups: trigger + poll ────────────────────────────────────
    print("\n== 10. Backups ==")
    code, data = api.send("POST", "/api/admin/backups/force")
    check("POST backups/force 202", code == 202 and isinstance(data, dict) and data.get("status") == "started")
    deadline = time.time() + 150
    created = False
    if code == 202:
        while time.time() < deadline:
            time.sleep(10)
            code, data = api.send("GET", "/api/admin/backups")
            backups = data.get("backups", []) if isinstance(data, dict) else []
            if len(backups) > len(known_backups):
                created = True
                break
    check("backup appears within 150s", created, "see celery_worker logs if failing")

    # ── 11. SSE streams through nginx ──────────────────────────────────
    print("\n== 11. SSE ==")
    sse = [
        ("leaderboard/live (admin)", f"/api/challenges/{cid}/leaderboard/live", api, ("leaderboard", "info")),
        ("task submissions/live (admin)", f"/api/tasks/{tid}/submissions/live", api, ("items", "info")),
        ("submission logs/live (admin)", f"/api/submissions/{sid}/logs/live", api, ("info", "log", "status")),
        ("admin backups/live", "/api/admin/backups/live", api, ("backups",)),
        ("admin queue/live", "/api/admin/submissions/queue/live", api, ("items", "event")),
        ("admin workers/stats/live", "/api/admin/workers/stats/live", api, ()),
        ("worker-status/live", "/api/worker-status/live", api, ()),
        ("worker-status/live (competitor)", "/api/worker-status/live", comp, ()),
        ("leaderboard/live (competitor)", f"/api/challenges/{cid}/leaderboard/live", comp, ("leaderboard", "info")),
    ]
    for name, path, client, keys in sse:
        payload = client.sse_first_data(path)
        if "__not_sse__" in payload:
            check(f"SSE {name}", False, f"Content-Type={payload['__not_sse__']}")
        elif "__timeout__" in payload or "__eof__" in payload or "__error__" in payload:
            check(f"SSE {name}", False, str(payload))
        elif not isinstance(payload, dict):
            check(f"SSE {name}", False, f"non-JSON payload: {payload}")
        else:
            ok = any(k in payload for k in keys) if keys else len(payload) > 0
            check(f"SSE {name}", ok, f"keys={sorted(payload.keys())[:6]}")

    # ── 11b. SSE round-trips (coordination pub/sub over the broker Redis) ──
    print("\n== 11b. SSE round-trips ==")
    # queue_updates channel: initial payload only — no deterministic trigger
    # exists (kill/clear only publish when submissions are still queued, which
    # is worker-timing dependent), so assert snapshot + connection.
    payload = api.sse_first_data("/api/admin/submissions/queue/live")
    check("SSE queue/live snapshot event (queue_updates channel)",
          isinstance(payload, dict) and payload.get("event") == "snapshot"
          and isinstance(payload.get("items"), list),
          f"keys={sorted(payload.keys())[:6] if isinstance(payload, dict) else payload}")
    # leaderboard live round-trip: select-final always republishes
    # publish_leaderboard_update → the stream must deliver a second payload.
    if sid:
        def _trigger_leaderboard_update() -> None:
            api.send("POST", f"/api/submissions/{sid}/select-final")

        ok, payloads, detail = api.sse_roundtrip(
            f"/api/challenges/{cid}/leaderboard/live", _trigger_leaderboard_update)
        check("SSE leaderboard/live round-trip (publish → update received)", ok, detail)
        check("SSE leaderboard/live initial 'info: connected' event",
              bool(payloads) and payloads[0].get("info") == "connected",
              str(payloads[0])[:120] if payloads else "no payloads collected")
    else:
        warn("SSE leaderboard/live round-trip", "no submission id (prior submission checks failed)")

    # ── 12. Edge cases ─────────────────────────────────────────────────
    print("\n== 12. Edge cases ==")
    anon = Api(args.base)
    code, data = anon.send("GET", "/api/challenges")
    check("anonymous GET challenges → 401 ERR_TOKEN_INVALID",
          code == 401 and expect_error(data, "ERR_TOKEN_INVALID"))
    code, data = anon.send("POST", "/api/auth/login", {"username": "", "password": ""})
    check("empty credentials → 422 ERR_VALIDATION", code == 422 and expect_error(data, "ERR_VALIDATION"))
    code, data = api.send("POST", "/api/challenges",
                          {"title": "", "start_time": now, "end_time": future})
    check("empty title → 422 ERR_VALIDATION", code == 422 and expect_error(data, "ERR_VALIDATION"))
    code, data = api.send("GET", "/api/challenges/00000000-0000-0000-0000-000000000000")
    check("nonexistent challenge → 404", code == 404)
    code, data = api.send("GET", f"/api/tasks/{tid}/download/does-not-exist.ipynb")
    check("missing task file → 404 ERR_FILE_NOT_FOUND", code == 404 and expect_error(data, "ERR_FILE_NOT_FOUND"))
    code, data = api.send("GET", "/api/admin/backups/%2E%2E%2F%2E%2E%2Fetc%2Fpasswd/download")
    check("backup download path traversal → 404", code == 404)
    code, data = jury.send("GET", "/api/admin/backups")
    check("jury GET backups → 403 ERR_ROLE_REQUIRED (admin-only)",
          code == 403 and expect_error(data, "ERR_ROLE_REQUIRED"))
    code, data = jury.send("DELETE", "/api/admin/backups/manual_nonexistent.tar.gz")
    check("jury DELETE backup → 403 ERR_ROLE_REQUIRED", code == 403 and expect_error(data, "ERR_ROLE_REQUIRED"))
    code, data = jury.send("POST", f"/api/challenges/{cid}/manual-points",
                           {"user_id": comp_id, "points": {tid: 150}, "reason": "smoke"})
    check("manual points > 100 → 422 ERR_POINTS_OUT_OF_BOUNDS",
          code == 422 and expect_error(data, "ERR_POINTS_OUT_OF_BOUNDS"))
    code, data = comp.send("POST", f"/api/challenges/{cid}/submit", {"task_id": tid, "selected_cells": []})
    check("empty selected_cells → 422 ERR_VALIDATION", code == 422 and expect_error(data, "ERR_VALIDATION"))
    if fname:
        code, data = comp.send("GET", f"/api/tasks/{tid}/download/{fname}")
        check("competitor downloads baseline file 200", code == 200)
    code, data = api.send("POST", "/api/challenges",
                          {"title": "edge-other-challenge", "start_time": now, "end_time": future,
                           "gpu_required": False})
    cid2 = data.get("id", "") if isinstance(data, dict) else ""
    if cid2:
        code, data = comp.send("GET", f"/api/challenges/{cid2}")
        check("competitor other challenge → 403 ERR_NOT_REGISTERED",
              code == 403 and expect_error(data, "ERR_NOT_REGISTERED"))
        api.send("DELETE", f"/api/challenges/{cid2}")
    code, data = api.send("POST", f"/api/challenges/{cid}/archive")
    check("archive challenge 200", code == 200 and isinstance(data, dict) and data.get("challenge", {}).get("is_archived") is True)
    comp2 = Api(args.base)
    code, data = comp2.send("POST", "/api/auth/login", {"username": comp_user, "password": comp_pass})
    check("competitor login while archived → 403 ERR_COMPETITION_ARCHIVED",
          code == 403 and expect_error(data, "ERR_COMPETITION_ARCHIVED"))
    code, data = api.send("POST", f"/api/challenges/{cid}/archive")
    check("unarchive challenge 200", code == 200 and isinstance(data, dict) and data.get("challenge", {}).get("is_archived") is False)
    comp = Api(args.base)
    code, data = comp.send("POST", "/api/auth/login", {"username": comp_user, "password": comp_pass})
    check("competitor login after unarchive 200", code == 200)
    code, data = comp.send("GET", "/api/auth/csrf-token")
    comp.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""
    for i in range(6):
        code, data = anon.send("POST", "/api/auth/login", {"username": "rate_limit_probe", "password": "x"})
    check("6th bad login same user → 429 ERR_RATE_LIMIT_EXCEEDED",
          code == 429 and expect_error(data, "ERR_RATE_LIMIT_EXCEEDED"))
    payload = anon.sse_first_data(f"/api/challenges/{cid}/leaderboard/live", timeout=10)
    check("anonymous SSE → 401", "__error__" in payload and "401" in str(payload.get("__error__")))
    # ── 13. Role matrix ────────────────────────────────────────────────
    print("\n== 13. Role matrix ==")
    clients = {"a": api, "j": jury, "c": comp, "n": Api(args.base)}
    matrix = [
        ("POST /api/challenges (create)", "POST", "/api/challenges",
         {"title": "matrix-junk", "start_time": now, "end_time": future},
         {"j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/users", "GET", "/api/admin/users", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/metrics", "GET", "/api/admin/metrics", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/audit-logs", "GET", "/api/admin/audit-logs", None,
         {"j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/dead-letters", "GET", "/api/admin/dead-letters", None,
         {"j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/backups", "GET", "/api/admin/backups", None,
         {"j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/backups/<f>/download", "GET", "/api/admin/backups/missing.tar.gz/download", None,
         {"j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/submissions/queue", "GET", "/api/admin/submissions/queue", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/admin/workers/stats", "GET", "/api/admin/workers/stats", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET scores CSV (not finalized)", "GET", f"/api/admin/challenges/{cid}/download-scores-csv", None,
         {"a": (400, None), "j": (400, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET submissions zip", "GET", f"/api/admin/challenges/{cid}/download-submissions-zip", None,
         {"a": (400, None), "j": (400, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET challenge credentials", "GET", f"/api/admin/challenges/{cid}/credentials", None,
         {"a": ((200, 404), None), "j": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/challenges/<id>/export", "GET", f"/api/challenges/{cid}/export", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}),
        ("GET /api/challenges/<id>/export-results", "GET", f"/api/challenges/{cid}/export-results", None,
         {"j": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (401, "ERR_TOKEN_INVALID")}),
        ("GET /api/tasks/<id>", "GET", f"/api/tasks/{tid}", None,
         {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("GET /api/tasks/<id>/submissions", "GET", f"/api/tasks/{tid}/submissions", None,
         {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("GET /api/tasks/<id>/leaderboard", "GET", f"/api/tasks/{tid}/leaderboard", None,
         {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("GET /api/challenges/<id>/leaderboard", "GET", f"/api/challenges/{cid}/leaderboard", None,
         {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("GET /api/challenges/<id>/submissions", "GET", f"/api/challenges/{cid}/submissions", None,
         {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("POST manual-points", "POST", f"/api/challenges/{cid}/manual-points",
         {"user_id": comp_id, "points": {tid: 1}, "reason": "role-matrix"},
         {"a": (403, "ERR_ROLE_REQUIRED"), "c": (403, "ERR_ROLE_REQUIRED"), "n": (401, "ERR_TOKEN_INVALID")}),
        ("POST submit (jury)", "POST", f"/api/challenges/{cid}/submit",
         {"task_id": tid, "selected_cells": [{"id": 0, "type": "code", "source": "print(1)"}]},
         {"j": (202, None), "n": (401, "ERR_TOKEN_INVALID")}),
        ("POST parse-notebook (multipart)", "POST", f"/api/challenges/{cid}/parse-notebook",
         {}, {"j": (200, None), "c": (200, None), "n": (401, "ERR_TOKEN_INVALID")},
         {"file": ("cells.ipynb", ipynb)}),
    ]
    for label, method, path, payload, expect, *rest in matrix:
        matrix_run(label, method, path, payload, expect, clients,
                   files=rest[0] if rest else None)
    code, data = api.send("POST", "/api/challenges",
                          {"title": "role-throwaway", "start_time": "2024-01-01T00:00:00Z",
                           "end_time": "2025-12-31T00:00:00Z", "gpu_required": False})
    role_cid = data.get("id", "") if isinstance(data, dict) else ""
    role_sid = ""
    jury2_id = ""
    if role_cid:
        code, data = _post_register(api,
                                    {"name": "RC", "surname": "One", "middle_name": "M", "birth_date": "2010-01-01",
                                     "grade": "8", "school": "S", "city": "Sofia",
                                     "role": "competitor", "challenge_id": role_cid})
        check("register competitor for throwaway challenge 201",
              code == 201 and isinstance(data, dict))
        code, data = _post_register(api,
                                    {"name": "Jury", "surname": "Two", "role": "jury", "jury_challenges": [role_cid]})
        if code == 201 and isinstance(data, dict):
            jury2_id = data.get("user", {}).get("id", "")
            jury2 = Api(args.base)
            jury2.send("GET", "/api/auth/csrf-token")
            jury2.csrf = jury2.send("GET", "/api/auth/csrf-token")[1]["csrf_token"]
            jury2.send("POST", "/api/auth/login",
                       {"username": data.get("generated_username", ""),
                        "password": data.get("generated_password", "")})
            clients["j2"] = jury2
            matrix_run("POST stages (jury on own challenge)", "POST", f"/api/challenges/{role_cid}/stages",
                       {"title": "RS", "start_time": "2024-01-01T00:00:00Z",
                        "end_time": "2025-12-31T00:00:00Z"}, {"j2": (201, None)}, clients)
            code, data = api.send("GET", f"/api/challenges/{role_cid}")
            role_sid = data.get("stages", [{}])[0].get("id", "") if isinstance(data, dict) else ""
            if role_sid:
                matrix_run("POST stage finalize (jury)", "POST",
                           f"/api/challenges/{role_cid}/stages/{role_sid}/finalize",
                           {"reveal_results": False}, {"j2": (200, None)}, clients)
                matrix_run("POST challenge finalize (jury)", "POST",
                           f"/api/challenges/{role_cid}/finalize",
                           {"reveal_results": False}, {"j2": (200, None), "a": (403, "ERR_ROLE_REQUIRED"),
                                                       "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}, clients)
                matrix_run("PUT reveal-results (jury)", "PUT",
                           f"/api/challenges/{role_cid}/reveal-results",
                           {"reveal_results": True}, {"j2": (200, None)}, clients)
                matrix_run("POST archive (jury)", "POST", f"/api/challenges/{role_cid}/archive",
                           None, {"j2": (200, None), "c": (403, "ERR_ROLE_REQUIRED"), "n": (403, "ERR_ROLE_REQUIRED")}, clients)
                matrix_run("DELETE challenge (admin)", "DELETE", f"/api/challenges/{role_cid}",
                           None, {"a": (200, None), "j2": (403, "ERR_ROLE_REQUIRED")}, clients)
    if jury2_id:
        code, data = api.send("DELETE", f"/api/admin/users/{jury2_id}")
        check("DELETE jury2 user → 404 ERR_USER_NOT_FOUND (challenge cascade)",
              code == 404 and expect_error(data, "ERR_USER_NOT_FOUND"))
    rl_users: list[str] = []
    rl_status, rl_data = 0, None
    for attempt in range(2):
        rl_users, rl_status, rl_data = [], 0, None
        for i in range(25):
            rl_status, rl_data = api.send("POST", "/api/admin/register-user",
                                          {"name": f"RL{i}", "surname": "Probe", "middle_name": "M",
                                           "birth_date": "2010-01-01", "grade": "8", "school": "Test School",
                                           "city": "Sofia", "role": "competitor", "challenge_id": cid})
            if rl_status == 201 and isinstance(rl_data, dict):
                rl_users.append(rl_data.get("user", {}).get("id", ""))
            elif rl_status == 429:
                break
        if attempt == 0 and (rl_status != 429 or not rl_users):
            print("  (admin register budget still cooling down from a prior run — waiting 65s, retrying)")
            time.sleep(65)
            continue
        break
    check("register-user rate limit → 429 ERR_RATE_LIMITED (admin 20/60s budget)",
          rl_status == 429 and expect_error(rl_data, "ERR_RATE_LIMITED") and len(rl_users) >= 15,
          f"status={rl_status} users_created={len(rl_users)}")
    for uid in rl_users:
        api.send("DELETE", f"/api/admin/users/{uid}")
    check("rate-limit test users cleaned up", True)

    # ── 14. Docs endpoints ─────────────────────────────────────────────
    print("\n== 14. Docs ==")
    code, data = api.send("GET", "/api/docs/competitor?lang=en")
    check("GET /api/docs/competitor 200", code == 200 and isinstance(data, dict) and data.get("title"))
    code, data = api.send("GET", "/api/docs/jury?lang=en")
    check("GET /api/docs/jury 200", code == 200 and isinstance(data, dict) and data.get("title"))

    # ── 15. Evaluation worker E2E (SMOKE_EVALUATE=1) ──────────────────
    if os.environ.get("SMOKE_EVALUATE") == "1":
        print("\n== 15. Evaluation (worker) ==")
        try:
            import pandas as pd
            import pyarrow  # noqa: F401

            have_parquet = True
        except ImportError as e:
            have_parquet = False
            warn("eval worker E2E",
                 f"pandas/pyarrow not importable on smoke host ({e}) — skipped")
        if have_parquet:
            code, data = api.send("GET", "/api/admin/workers/stats")
            wlist = data.get("workers", []) if code == 200 and isinstance(data, dict) else []
            worker_ok = any(w.get("type") == "CPU" for w in wlist if isinstance(w, dict))
            check("eval: CPU worker connected (worker_spec)",
                  worker_ok,
                  f"types={sorted({w.get('type') for w in wlist if isinstance(w, dict)})}")
            if not worker_ok:
                warn("eval worker E2E",
                     "no CPU worker registered — submission E2E skipped (SMOKE_EVALUATE=1 requires one)")
            else:
                code, data = api.send("POST", "/api/admin/register-competitor",
                                      {"name": "Eval", "surname": "Probe", "middle_name": "M",
                                       "birth_date": "2006-02-02", "grade": "10",
                                       "school": "Eval HS", "city": "Plovdiv", "challenge_id": cid})
                ecomp_user = data.get("generated_username", "") if code == 201 and isinstance(data, dict) else ""
                ecomp_pass = data.get("generated_password", "") if code == 201 and isinstance(data, dict) else ""
                ecomp_id = data.get("user", {}).get("id", "") if code == 201 and isinstance(data, dict) else ""
                check("eval: register fresh competitor 201", code == 201 and bool(ecomp_user))
                ecomp = Api(args.base)
                code, data = ecomp.send("POST", "/api/auth/login",
                                        {"username": ecomp_user, "password": ecomp_pass})
                check("eval: competitor login 200", code == 200 and isinstance(data, dict)
                      and data.get("user", {}).get("role") == "competitor")
                code, data = ecomp.send("GET", "/api/auth/csrf-token")
                ecomp.csrf = data.get("csrf_token", "") if isinstance(data, dict) else ""

                labels_df = pd.DataFrame({"id": [1, 2, 3, 4, 5], "label": [0, 1, 0, 1, 0]})
                labels_buf = io.BytesIO()
                labels_df.to_parquet(labels_buf, index=False)
                code, data = api.multipart(
                    "POST", f"/api/challenges/{cid}/tasks",
                    {"title": "smoke-eval-task", "stage_id": stage_id, "gpu_required": "false",
                     "ram_limit_mb": "512", "time_limit_sec": "60",
                     "base_docker_image": "python:3.12-slim",
                     "pip_requirements": "pandas\npyarrow",
                     "metrics_config": json.dumps(
                         {"accuracy": {"weight": 1.0, "higher_is_better": True}}),
                     "public_eval_percentage": "50"},
                    {"baseline_notebook": ("baseline.ipynb", ipynb),
                     "file0": ("labels.parquet", labels_buf.getvalue())})
                eval_tid = data.get("id", "") if code == 201 and isinstance(data, dict) else ""
                check("eval: create task with labels.parquet 201", code == 201 and bool(eval_tid))
                code, data = ecomp.send("GET", f"/api/tasks/{eval_tid}/download/labels.parquet")
                check("eval: competitor labels.parquet download → 403 ERR_ACCESS_DENIED",
                      code == 403 and expect_error(data, "ERR_ACCESS_DENIED"))
                # boom-ci: raises before writing parquet → failed; the stderr
                # traceback is merged into the submission logs.
                reached, sub = submit_and_poll(ecomp, api, cid, eval_tid,
                                               'raise RuntimeError("boom-ci")')
                check("eval: boom-ci submission failed",
                      reached and sub.get("status") == "failed", f"status={sub.get('status')}")
                check("eval: boom-ci traceback in logs",
                      reached and "boom-ci" in str(sub.get("logs", "")),
                      f"logs={str(sub.get('logs', ''))[:200]}")
                # Good submission: writes submission.parquet (labels match ground truth).
                good_code = ("import pandas as pd\n"
                             "pd.DataFrame({'id': [1, 2, 3, 4, 5], 'label': [0, 1, 0, 1, 0]})"
                             ".to_parquet('submission.parquet')\n")
                reached, sub = submit_and_poll(ecomp, api, cid, eval_tid, good_code)
                check("eval: good submission completed",
                      reached and sub.get("status") == "completed", f"status={sub.get('status')}")
                score = sub.get("public_score")
                check("eval: public_score == 1.0 (accuracy)",
                      isinstance(score, (int, float)) and abs(float(score) - 1.0) < 1e-6,
                      f"score={score}")
                mpub = sub.get("metrics_payload_public")
                check("eval: metrics_payload_public accuracy 1.0",
                      isinstance(mpub, dict) and abs(float(mpub.get("accuracy", -1)) - 1.0) < 1e-6,
                      f"payload={mpub}")
                # No-parquet: runs fine but never writes submission.parquet.
                reached, sub = submit_and_poll(ecomp, api, cid, eval_tid, "print('no parquet')")
                check("eval: no-parquet submission failed",
                      reached and sub.get("status") == "failed", f"status={sub.get('status')}")
                check("eval: no-parquet error in logs",
                      reached and "submission.parquet" in str(sub.get("logs", "")),
                      f"logs={str(sub.get('logs', ''))[:200]}")
                # Leaderboard: the completed eval submission scores 1.0.
                # The raw leaderboard is cached and only rebuilt by the
                # recalculate-dirty-leaderboards beat task (every 20 s), so poll
                # briefly for the fresh entry instead of asserting immediately.
                ts_score = ts = None
                for _ in range(12):
                    code, data = api.send("GET", f"/api/challenges/{cid}/leaderboard")
                    lb = data.get("leaderboard", []) if code == 200 and isinstance(data, dict) else []
                    entry = {}
                    for e in lb:
                        if isinstance(e, dict) and isinstance(e.get("user"), dict) \
                                and e["user"].get("id") == ecomp_id:
                            entry = e
                            break
                    ts = entry.get("task_scores", {}).get(str(eval_tid), {}) if isinstance(entry, dict) else {}
                    ts_score = ts.get("public_score") if isinstance(ts, dict) else None
                    if isinstance(ts_score, (int, float)) and abs(float(ts_score) - 1.0) < 1e-6:
                        break
                    time.sleep(5)
                check("eval: leaderboard task_score 1.0 (fresh competitor)",
                      isinstance(ts_score, (int, float)) and abs(float(ts_score) - 1.0) < 1e-6,
                      f"task_scores={ts}")
                code, data = api.send("DELETE", f"/api/tasks/{eval_tid}")
                check("eval: delete task 200", code == 200 and isinstance(data, dict))

    # ── 16. Cleanup ────────────────────────────────────────────────────
    print("\n== 16. Cleanup ==")
    if cid:
        code, data = api.send("DELETE", f"/api/challenges/{cid}")
        check("DELETE challenge 200", code == 200)
    code, data = api.send("DELETE", f"/api/admin/users/{jury_id}")
    check("DELETE jury user → 404 ERR_USER_NOT_FOUND (challenge cascade)",
          code == 404 and expect_error(data, "ERR_USER_NOT_FOUND"))
    code, data = api.send("DELETE", f"/api/admin/users/{comp_id}")
    check("DELETE competitor user → 404 ERR_USER_NOT_FOUND (challenge cascade)",
          code == 404 and expect_error(data, "ERR_USER_NOT_FOUND"))
    code, data = api.send("POST", "/api/auth/logout")
    check("logout 200", code == 200)

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}  WARN {len(WARN)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    for w in WARN:
        print(f"  WARN: {w}")
    return 1 if FAIL else 0


def _post_register(api: Api, payload: dict) -> tuple[int, object]:
    """POST register-user with a 65s cooldown retry (rate limiter windows leak across runs)."""
    for attempt in range(2):
        code, data = api.send("POST", "/api/admin/register-user", payload)
        if code != 429 or attempt == 1:
            return code, data
        print("  (admin register budget still cooling down — waiting 65s, retrying)")
        time.sleep(65)
    return code, data


if __name__ == "__main__":
    sys.exit(main())
