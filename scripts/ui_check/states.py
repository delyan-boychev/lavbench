#!/usr/bin/env python3
"""Put the seeded stack into the state a capture phase needs.

    python scripts/ui_check/states.py --out DIR live           # a fresh long-running submission
    python scripts/ui_check/states.py --out DIR stop-live      # kill it, freeing the worker
    python scripts/ui_check/states.py --out DIR freeze         # emergency freeze on
    python scripts/ui_check/states.py --out DIR unfreeze
    python scripts/ui_check/states.py --out DIR grace          # stage deadline just passed,
                                                               # plus a submission made in grace
    python scripts/ui_check/states.py --out DIR archive-empty  # archive the empty challenge
    python scripts/ui_check/states.py --out DIR finalize-stage # manual points for everyone, the
                                                               # stage final and revealed, and the
                                                               # challenge ended
    python scripts/ui_check/states.py --out DIR finalize       # challenge final and revealed

Each command reads and updates DIR/seed.json, written by seed.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed import login

LIVE_SOURCE = (
    "import time\n"
    "for epoch in range(1, 400):\n"
    "    print(f'epoch {epoch:03d}: loss={1 / epoch:.4f} accuracy={1 - 1 / (epoch + 1):.4f}',"
    " flush=True)\n"
    "    time.sleep(3)\n"
)
GRACE_SOURCE = (
    "import pandas as pd\npd.DataFrame({'id': list(range(1, 11)), "
    "'label': [0, 1, 0, 1, 0, 1, 1, 0, 0, 0]}).to_parquet('submission.parquet')\n"
)


def check(code: int, data: object, what: str) -> None:
    if code not in (200, 201, 202):
        raise SystemExit(f"{what} failed: HTTP {code} {str(data)[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="directory holding seed.json")
    ap.add_argument(
        "command",
        choices=[
            "live",
            "stop-live",
            "freeze",
            "unfreeze",
            "grace",
            "archive-empty",
            "finalize-stage",
            "finalize",
        ],
    )
    args = ap.parse_args()
    path = Path(args.out) / "seed.json"
    seed = json.loads(path.read_text())
    base = seed["base"]
    admin = login(base, seed["admin"]["user"], seed["admin"]["password"])
    cid = seed["cid"]

    if args.command == "live":
        comp = seed["competitors"][1]
        capi = login(base, comp["user"], comp["password"])
        code, data = capi.send(
            "POST",
            f"/api/tasks/{seed['live_tid']}/submit",
            {"selected_cells": [{"id": 0, "type": "code", "source": LIVE_SOURCE}]},
        )
        check(code, data, "live submit")
        seed["running_submission"] = data["submission_id"]
        time.sleep(15)  # Let a worker pick it up, so the log is streaming
    elif args.command == "stop-live":
        code, data = admin.send("POST", f"/api/submissions/{seed['running_submission']}/kill")
        if code not in (200, 400):  # 400: it already ended
            check(code, data, "kill live submission")
    elif args.command in ("freeze", "unfreeze"):
        code, data = admin.send(
            "PUT", f"/api/challenges/{cid}", {"is_frozen": args.command == "freeze"}
        )
        check(code, data, args.command)
    elif args.command == "grace":
        # The deadline passed 15 s ago, so the 3-minute grace window is open
        end = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=15)
        code, data = admin.send(
            "PUT",
            f"/api/challenges/{cid}/stages/{seed['stage_id']}",
            {"end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")},
        )
        check(code, data, "move stage deadline")
        comp = seed["competitors"][0]
        capi = login(base, comp["user"], comp["password"])
        code, data = capi.send(
            "POST",
            f"/api/tasks/{seed['tid']}/submit",
            {"selected_cells": [{"id": 0, "type": "code", "source": GRACE_SOURCE}]},
        )
        check(code, data, "submit during grace")
        seed["grace_submission"] = data["submission_id"]
        seed["grace_ends_at"] = time.time() + 165
    elif args.command == "archive-empty":
        code, data = admin.send("POST", f"/api/challenges/{seed['empty_cid']}/archive")
        check(code, data, "archive empty challenge")
    elif args.command == "finalize-stage":
        jury = login(base, seed["jury"]["user"], seed["jury"]["password"])
        # Finalising needs the jury's points for every competitor and task with submissions
        for comp, points in zip(seed["competitors"], (85, 70, 40), strict=True):
            code, data = jury.send(
                "POST",
                f"/api/challenges/{cid}/manual-points",
                {
                    "user_id": comp["id"],
                    "points": {seed["tid"]: points, seed["live_tid"]: points // 2},
                    "reason": "Reviewed the notebook and the approach",
                },
            )
            check(code, data, "manual points")
        code, data = jury.send(
            "POST",
            f"/api/challenges/{cid}/stages/{seed['stage_id']}/finalize",
            {"reveal_results": True},
        )
        check(code, data, "finalize stage")
        # The challenge Finalize button and route need the challenge to have ended
        end = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)
        code, data = admin.send(
            "PUT", f"/api/challenges/{cid}", {"end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
        )
        check(code, data, "end challenge")
        time.sleep(25)  # Let the beat rebuild the cached leaderboard
    elif args.command == "finalize":
        jury = login(base, seed["jury"]["user"], seed["jury"]["password"])
        for method, url, body in (
            ("POST", f"/api/challenges/{cid}/finalize", {"reveal_results": True}),
            ("PUT", f"/api/challenges/{cid}/reveal-results", {"reveal_results": True}),
        ):
            code, data = jury.send(method, url, body)
            check(code, data, f"{method} {url.rsplit('/', 1)[-1]}")
        time.sleep(25)  # Let the beat rebuild the cached leaderboard
    path.write_text(json.dumps(seed, indent=2))
    print(args.command, "done", flush=True)  # noqa: T201


if __name__ == "__main__":
    main()
