#!/usr/bin/env python3
"""Screenshot every LavBench page and scenario per role, viewport, language and theme.

Runs inside the official Playwright image (see run.sh), against a stack seeded by seed.py:

    python capture.py PHASE          # main, live, actions, frozen, grace, archived,
                                     # after-grace, ended, final
    python capture.py only:KEY,KEY   # re-capture single scenarios ("role--name")

Every screenshot records console and page errors, horizontal overflow and whether each
scripted step worked; axe-core runs per scenario on desktop in English, in both themes.
Writes /out/shots, /out/sheets (one contact sheet per scenario), /out/report.json and
/out/index.html. Scenario tuples are (role, name, path, steps, options); see README.md.

Screenshots run in UI_CHECK_WORKERS parallel browsers (default 6). Scenarios that change
data run once, one at a time and in order, after the others of their phase.
"""

from __future__ import annotations

import html
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

TOOL = Path(__file__).resolve().parent
OUT = Path("/out")
SHOTS = OUT / "shots"
SHEETS = OUT / "sheets"
SEED = json.loads((OUT / "seed.json").read_text())
LOCALES = {
    lang: json.loads((Path("/locales") / lang / "translation.json").read_text())
    for lang in ("en", "bg")
}
BASE = SEED["base"]
C = f"/challenges/{SEED['cid']}"
E = f"/challenges/{SEED['empty_cid']}"

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 860},
    "tablet": {"width": 820, "height": 1180},
    "phone": {"width": 390, "height": 844},
}
LANGS = ["en", "bg"]
THEMES = ["dark", "light"]
ALL = [f"{v}-{lang}-{theme}" for v in VIEWPORTS for lang in LANGS for theme in THEMES]
# Scenarios that change data run once; the time-boxed grace window gets four variants
ONE = ["desktop-en-dark"]
QUICK = ["desktop-en-dark", "desktop-bg-light", "phone-en-light", "phone-bg-dark"]
WORKERS = max(1, int(os.environ.get("UI_CHECK_WORKERS", "6")))
# After the network goes quiet, give transitions and late renders this long to finish
SETTLE_MS = 400

ADMIN_TABS = [
    ("competition-mgmt", "admin.manage_competitions"),
    ("challenge-config", "admin.create_competition"),
    ("competitor-reg", "admin.competitor_registrations"),
    ("backups", "admin.database_backup"),
    ("user-management", "admin.user_management"),
    ("audit-logs", "admin.audit_logs"),
    ("workers-stats", "admin.workers_resources"),
    ("submission-queue", "admin.submission_queue.title"),
]
JURY_TABS = {"competition-mgmt", "competitor-reg", "workers-stats", "submission-queue"}
TASK_TABS = ["general", "evaluation", "sandbox", "environment", "files"]
MGMT = ("button", "admin.manage_competitions")
REG = ("button", "admin.competitor_registrations")
# On the general leaderboard, manual points sit in a row's details
EXPAND_ROW = ("title", "leaderboard.toggle_details_tooltip")
STAGE_FINALIZE = ("button", "admin.stages.finalize")
CHALLENGE_FINALIZE = ("button_last", "admin.finalize_short")


def label(lang: str, key: str) -> str:
    node = LOCALES[lang]
    for part in key.split("."):
        node = node[part]
    return re.split(r"\{\{", node)[0].strip()


def scenarios(phase: str) -> list[tuple]:
    s = SEED
    alias, alias2 = s["aliases"][0], s["aliases"][1]
    if phase == "live":
        return [
            (
                "competitor2",
                "submission-running-live-logs",
                f"{C}/submissions",
                [("text", s["live_task_title"]), ("sub", s["running_submission"]), ("wait", 2500)],
                {},
            ),
            (
                "admin",
                "submission-running-kill",
                f"{C}/submissions",
                [
                    ("text", alias2),
                    ("text", s["live_task_title"]),
                    ("sub", s["running_submission"]),
                ],
                {},
            ),
            (
                "admin",
                "submission-kill-confirm",
                f"{C}/submissions",
                [
                    ("text", alias2),
                    ("text", s["live_task_title"]),
                    ("sub", s["running_submission"]),
                    ("button", "submissions.kill"),
                ],
                {},
            ),
            (
                "admin",
                "panel-submission-queue-running",
                "/admin",
                [("button", "admin.submission_queue.title")],
                {},
            ),
        ]
    if phase == "actions":
        return [
            (
                "competitor",
                "final-selection-saved",
                f"{C}/submissions",
                [("sub", s["submissions"][0]), ("text_key", "submissions.final_selection_label")],
                {"variants": ONE},
            ),
            (
                "admin",
                "manual-points-saved",
                f"{C}/leaderboard",
                [
                    ("text", s["task_title"]),
                    ("title", "leaderboard.edit_points_tooltip"),
                    ("fill_placeholder", "leaderboard.points_input_placeholder", "85"),
                    ("button", "common.save"),
                ],
                {"variants": ONE},
            ),
            (
                "admin",
                "backup-created",
                "/admin",
                [
                    ("button", "admin.database_backup"),
                    ("button", "admin.backups.force_now"),
                    ("wait", 6000),
                ],
                {"variants": ONE},
            ),
            (
                "admin",
                "competitor-registered",
                "/admin",
                [
                    REG,
                    ("fill_label", "admin.competitor_reg.first_name", "Ivo"),
                    ("fill_label", "admin.competitor_reg.last_name", "Georgiev"),
                    ("fill_label", "admin.competitor_reg.middle_name", "P"),
                    ("fill_label", "admin.competitor_reg.birth_date", "2009-04-12"),
                    ("fill_label", "admin.competitor_reg.grade", "10"),
                    ("fill_label", "admin.competitor_reg.school", "Sofia High School"),
                    ("fill_label", "admin.competitor_reg.city", "Sofia"),
                    (
                        "select_label",
                        "admin.competitor_reg.assign_competition",
                        s["challenge_title"],
                    ),
                    ("form_submit", 0),
                ],
                {"variants": ONE},
            ),
            (
                "admin",
                "csv-import-done",
                "/admin",
                [
                    REG,
                    (
                        "select_label",
                        "admin.competitor_reg.target_competition_challenge",
                        s["challenge_title"],
                    ),
                    ("upload_css", "input[accept='.csv']", "competitors.csv"),
                    ("form_submit", 1),
                    ("wait", 3000),
                ],
                {"variants": ONE},
            ),
            (
                "competitor3",
                "leaderboard-live-update",
                f"{C}/leaderboard",
                [("api_submit", s["tid"]), ("wait", 45000)],
                {"variants": ONE},
            ),
        ]
    if phase == "frozen":
        return [
            ("competitor", "challenge-frozen", C, [], {}),
            (
                "competitor",
                "submit-blocked-frozen",
                C,
                [
                    ("upload", "notebook"),
                    ("button_key_prefix", "challenge.submit_cells_for_evaluation"),
                ],
                {"variants": ONE},
            ),
        ]
    if phase == "grace":
        return [
            ("competitor", "grace-timer", C, [], {"variants": QUICK}),
            ("competitor", "grace-submission-listed", f"{C}/submissions", [], {"variants": QUICK}),
        ]
    if phase == "after-grace":
        return [
            (
                "competitor",
                "grace-submission-viewable",
                f"{C}/submissions",
                [("sub", s["grace_submission"])],
                {},
            ),
            # The upload is gone once the deadline and its grace window have passed
            ("competitor", "submission-closed-after-deadline", C, [], {}),
            # Finalize appears once the stage deadline has passed, for the jury only
            ("jury", "stage-finalize-modal", "/admin", [MGMT, STAGE_FINALIZE], {}),
            ("admin", "panel-competition-mgmt-no-finalize", "/admin", [MGMT], {}),
        ]
    if phase == "ended":
        # Challenge Finalize appears once the challenge has ended and every stage is final,
        # for the jury only
        return [
            ("jury", "challenge-finalize-modal", "/admin", [MGMT, CHALLENGE_FINALIZE], {}),
            ("competitor", "challenge-ended", C, [], {}),
            (
                "competitor",
                "stage-results-revealed",
                f"{C}/leaderboard",
                [("text", s["stage_title"])],
                {},
            ),
            (
                "jury",
                "stage-final-private-visible",
                f"{C}/leaderboard",
                [("text", s["stage_title"])],
                {},
            ),
        ]
    if phase == "archived":
        return [
            (
                "anonymous",
                "login-archived-challenge",
                "/login",
                [("login_as", "empty_competitor")],
                {},
            )
        ]
    if phase == "final":
        return [
            ("competitor", "final-leaderboard", f"{C}/leaderboard", [], {}),
            ("competitor", "final-submissions", f"{C}/submissions", [], {}),
            ("jury", "final-leaderboard-private-visible", f"{C}/leaderboard", [], {}),
            ("admin", "final-leaderboard", f"{C}/leaderboard", [], {}),
            # Points are read-only once the challenge is final
            ("admin", "final-manual-points-locked", f"{C}/leaderboard", [EXPAND_ROW], {}),
        ]
    out: list[tuple] = [
        ("anonymous", "login", "/login", [], {}),
        ("anonymous", "login-error", "/login", [("login_fail",)], {}),
        ("anonymous", "login-keyboard-focus", "/login", [("press", "Tab", 2)], {}),
        ("competitor", "challenges", "/challenges", [], {}),
        ("competitor", "challenge-task", C, [], {}),
        ("competitor", "notebook-cell-picker", C, [("upload", "notebook")], {}),
        ("competitor", "notebook-too-large", C, [("upload", "oversized")], {}),
        ("competitor", "submissions", f"{C}/submissions", [], {}),
        (
            "competitor",
            "submission-completed",
            f"{C}/submissions",
            [("sub", s["submissions"][0])],
            {},
        ),
        (
            "competitor",
            "submission-platform-error",
            f"{C}/submissions",
            [("sub", s["infra_submission"])],
            {},
        ),
        ("competitor", "leaderboard", f"{C}/leaderboard", [], {}),
        ("competitor", "leaderboard-task-tab", f"{C}/leaderboard", [("text", s["task_title"])], {}),
        (
            "competitor",
            "leaderboard-stage-tab",
            f"{C}/leaderboard",
            [("text", s["stage_title"])],
            {},
        ),
        ("competitor", "docs-competitor-guide", C, [("button", "nav.docs")], {}),
        (
            "competitor3",
            "submission-failed-traceback",
            f"{C}/submissions",
            [("sub", s["submissions"][2])],
            {},
        ),
        ("empty_competitor", "challenge-without-tasks", E, [], {}),
        ("empty_competitor", "submissions-empty", f"{E}/submissions", [], {}),
        ("empty_competitor", "leaderboard-empty", f"{E}/leaderboard", [], {}),
        ("jury", "challenges", "/challenges", [], {}),
        ("jury", "challenge-task", C, [], {}),
        ("jury", "leaderboard-private-hidden", f"{C}/leaderboard", [], {}),
        ("jury", "leaderboard-task-tab", f"{C}/leaderboard", [("text", s["task_title"])], {}),
        ("jury", "submissions", f"{C}/submissions", [], {}),
        ("jury", "submissions-competitor", f"{C}/submissions", [("text", alias)], {}),
        (
            "jury",
            "submission-detail",
            f"{C}/submissions",
            [("text", alias), ("sub", s["submissions"][0])],
            {},
        ),
        (
            "jury",
            "docs-jury-guide",
            C,
            [("button", "nav.docs"), ("button", "nav.doc_jury_guide")],
            {},
        ),
        ("admin", "challenge-task", C, [], {}),
        ("admin", "leaderboard", f"{C}/leaderboard", [], {}),
        (
            "admin",
            "manual-points-modal",
            f"{C}/leaderboard",
            [("text", s["task_title"]), ("title", "leaderboard.edit_points_tooltip")],
            {},
        ),
        ("admin", "leaderboard-task-tab", f"{C}/leaderboard", [("text", s["task_title"])], {}),
        ("admin", "submissions-competitor", f"{C}/submissions", [("text", alias)], {}),
        (
            "admin",
            "submission-detail-private",
            f"{C}/submissions",
            [("text", alias), ("sub", s["submissions"][0])],
            {},
        ),
        (
            "admin",
            "docs-admin-guide",
            C,
            [("button", "nav.docs"), ("button", "nav.doc_admin_guide")],
            {},
        ),
    ]
    for tab, key in ADMIN_TABS:
        out.append(("admin", f"panel-{tab}", "/admin", [("button", key)], {}))
        if tab in JURY_TABS:
            out.append(("jury", f"panel-{tab}", "/admin", [("button", key)], {}))
    for tab in TASK_TABS:
        out.append(
            (
                "admin",
                f"task-create-{tab}",
                "/admin",
                [MGMT, ("button", "admin.add_task"), ("button", f"admin.tasks.tabs.{tab}")],
                {},
            )
        )
        out.append(
            (
                "admin",
                f"task-edit-{tab}",
                "/admin",
                [MGMT, ("button", "admin.edit_config"), ("button", f"admin.tasks.tabs.{tab}")],
                {},
            )
        )
    out += [
        ("admin", "stage-create-modal", "/admin", [MGMT, ("button", "admin.stages.add_stage")], {}),
        # The competition's Edit button uses the same label, so pick the one in the stage row
        (
            "admin",
            "stage-edit-modal",
            "/admin",
            [MGMT, ("button_in", s["stage_title"], "admin.stages.edit")],
            {},
        ),
        (
            "admin",
            "user-edit-modal",
            "/admin",
            [("button", "admin.user_management"), ("button", "common.edit")],
            {},
        ),
        (
            "admin",
            "bulk-reset-prompt",
            "/admin",
            [REG, ("button", "admin.competitor_reg.reset_all_passwords")],
            {},
        ),
    ]
    return out


def creds(role: str) -> dict | None:
    if role == "anonymous":
        return None
    if role.startswith("competitor"):
        index = int(role[len("competitor") :] or 1) - 1
        return SEED["competitors"][index]
    return SEED[role]


def log_in(p, roles: set[str]) -> dict[str, dict]:
    """Log each role in once; every browser context of the phase reuses its cookies."""
    sessions: dict[str, dict] = {}
    for role in sorted(roles):
        c = creds(role)
        if c is None:
            continue
        request = p.request.new_context()
        r = request.post(
            f"{BASE}/api/auth/login", data={"username": c["user"], "password": c["password"]}
        )
        if not r.ok:
            raise RuntimeError(f"login {role}: HTTP {r.status}")
        sessions[role] = request.storage_state()
        request.dispose()
    return sessions


class Network:
    """Track the page's open requests, so a step waits for its data instead of a fixed time."""

    def __init__(self, page) -> None:
        self.page = page
        self.pending: set = set()
        page.on("request", self._start)
        page.on("requestfinished", self._end)
        page.on("requestfailed", self._end)

    def _start(self, request) -> None:
        # Event streams stay open for the page's lifetime
        if request.resource_type not in ("eventsource", "websocket"):
            self.pending.add(request)

    def _end(self, request) -> None:
        self.pending.discard(request)

    def settle(self, quiet_ms: int = 400, timeout_ms: int = 8000) -> None:
        """Wait until no request has been open for quiet_ms, then SETTLE_MS for rendering."""
        start = time.monotonic()
        idle_since: float | None = None
        while (time.monotonic() - start) * 1000 < timeout_ms:
            self.page.wait_for_timeout(100)
            if self.pending:
                idle_since = None
            elif idle_since is None:
                idle_since = time.monotonic()
            elif (time.monotonic() - idle_since) * 1000 >= quiet_ms:
                break
        self.page.wait_for_timeout(SETTLE_MS)


def fixture(name: str) -> str:
    if name == "notebook":
        return str(TOOL / "notebook.ipynb")
    return str(OUT / {"oversized": "oversized.ipynb"}.get(name, name))


def visible_button(page, lang: str, name: str):
    btn = page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(name)}"))
    if not btn.filter(visible=True).count():
        # On phones some actions sit behind the hamburger menu
        menu = page.get_by_role("button", name=label(lang, "nav.open_menu"))
        if menu.count():
            menu.first.click()
            page.wait_for_timeout(600)
    return btn.filter(visible=True)


def run_steps(page, context, net: Network, steps: list, lang: str, variant: str) -> str:
    for step in steps:
        kind = step[0]
        if kind in ("button", "button_last", "button_key_prefix"):
            name = label(lang, step[1])
            btn = visible_button(page, lang, name)
            if not btn.count():
                return f"button '{name}' not found"
            (btn.last if kind == "button_last" else btn.first).click()
        elif kind == "button_in":
            # The button inside the innermost block that also contains the text (a list row)
            name = label(lang, step[2])
            exact = page.get_by_role("button", name=re.compile(rf"^\s*{re.escape(name)}\s*$"))
            row = page.locator("div", has_text=step[1]).filter(has=exact).last
            if not row.count():
                return f"button '{name}' in '{step[1]}' not found"
            row.get_by_role("button", name=re.compile(rf"^\s*{re.escape(name)}\s*$")).first.click()
        elif kind in ("text", "text_key"):
            text = label(lang, step[1]) if kind == "text_key" else step[1]
            loc = page.get_by_text(text, exact=False)
            if not loc.count():
                return f"text '{text}' not found"
            loc.first.click()
        elif kind == "title":
            loc = page.get_by_title(label(lang, step[1]))
            if not loc.count():
                return f"element titled '{label(lang, step[1])}' not found"
            loc.first.click()
        elif kind == "sub":
            # UUIDv7 ids share a time prefix; the random tail identifies the submission
            loc = page.get_by_text(re.compile(re.escape(step[1][-12:])))
            if not loc.count():
                return f"submission ...{step[1][-12:]} not found"
            loc.first.click()
        elif kind == "upload":
            page.set_input_files("input[type=file]", fixture(step[1]))
        elif kind == "upload_css":
            page.set_input_files(step[1], fixture(step[2]))
        elif kind == "fill_label":
            page.get_by_label(label(lang, step[1]), exact=False).first.fill(step[2])
        elif kind == "select_label":
            name = label(lang, step[1])
            # ui/SelectField is a combobox button with a listbox, not a native <select>
            combo = page.get_by_role("combobox", name=re.compile(rf"^\s*{re.escape(name)}"))
            if combo.count():
                combo.first.click()
                option = page.get_by_role("option", name=re.compile(re.escape(step[2])))
                if not option.count():
                    return f"option '{step[2]}' not found"
                option.first.click()
            else:
                page.get_by_label(name, exact=False).first.select_option(label=step[2])
        elif kind == "fill_placeholder":
            page.get_by_placeholder(label(lang, step[1])).first.fill(step[2])
        elif kind == "form_submit":
            # Downloads it triggers (the credentials CSV) are accepted by the context
            form = page.locator("form").nth(step[1])
            form.locator("button[type=submit]").click()
            net.settle()
            if form.locator("[aria-invalid=true]").count():
                return "the form was not submitted: a field is invalid"
            continue
        elif kind == "press":
            for _ in range(step[2]):
                page.keyboard.press(step[1])
        elif kind == "login_fail":
            # One username per variant: five failures for one name within a minute return 429
            page.locator("input").nth(0).fill(f"no_such_user_{variant.replace('-', '_')}")
            page.locator("input[type=password]").fill("wrong-password")
            page.locator("button[type=submit]").click()
        elif kind == "login_as":
            c = SEED[step[1]]
            page.locator("input").nth(0).fill(c["user"])
            page.locator("input[type=password]").fill(c["password"])
            page.locator("button[type=submit]").click()
        elif kind == "api_submit":
            csrf = context.request.get(f"{BASE}/api/auth/csrf-token").json()["csrf_token"]
            source = (
                "import pandas as pd\npd.DataFrame({'id': list(range(1, 11)), "
                "'label': [0, 1, 0, 1, 0, 1, 1, 0, 0, 1]}).to_parquet('submission.parquet')\n"
            )
            r = context.request.post(
                f"{BASE}/api/tasks/{step[1]}/submit",
                data={"selected_cells": [{"source": source}]},
                headers={"X-CSRF-Token": csrf},
            )
            if r.status != 202:
                return f"api submit HTTP {r.status}"
        elif kind == "wait":
            page.wait_for_timeout(step[1])
            continue
        net.settle()
    return ""


def selected(phase: str) -> list[tuple]:
    if phase.startswith("only:"):
        keys = set(phase[5:].split(","))
        everything = [
            sc
            for ph in (
                "main",
                "live",
                "actions",
                "frozen",
                "after-grace",
                "archived",
                "ended",
                "final",
            )
            for sc in scenarios_safe(ph)
        ]
        return [sc for sc in everything if f"{sc[0]}--{sc[1]}" in keys]
    return scenarios(phase)


def scenarios_safe(phase: str) -> list[tuple]:
    try:
        return scenarios(phase)
    except KeyError:
        return []


def capture_one(browser, axe, sessions: dict, job: tuple) -> dict:
    """Screenshot one scenario in one variant and return its findings."""
    key, role, path, steps, variant = job
    vp_name, lang, theme = variant.split("-")
    context = browser.new_context(
        viewport=VIEWPORTS[vp_name],
        locale=lang,
        accept_downloads=True,
        storage_state=sessions.get(role),
    )
    context.add_init_script(
        f"localStorage.setItem('theme', '{theme}');localStorage.setItem('i18nextLng', '{lang}');"
    )
    page = context.new_page()
    net = Network(page)
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"[:300]))
    result: dict = {"key": key, "variant": variant, "axe": None}
    try:
        page.goto(f"{BASE}{path}", wait_until="networkidle")
        net.settle()
        try:
            problem = run_steps(page, context, net, steps, lang, variant)
        except Exception as exc:
            problem = f"{type(exc).__name__}: {str(exc)[:200]}"
        page.screenshot(path=str(SHOTS / f"{key}--{variant}.png"), full_page=True)
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        if vp_name == "desktop" and lang == "en":
            result["axe"] = (
                theme,
                [
                    {
                        "id": v["id"],
                        "impact": v["impact"],
                        "nodes": len(v["nodes"]),
                        "help": v["help"],
                        "targets": [n["target"] for n in v["nodes"][:3]],
                    }
                    for v in axe.run(page).response["violations"]
                ],
            )
    finally:
        context.close()
    result["findings"] = {
        "console_errors": errors,
        "horizontal_overflow": overflow,
        "step_problem": problem,
    }
    return result


def worker(jobs: queue.Queue, results: queue.Queue, sessions: dict) -> None:
    """Run jobs in a browser of this thread's own (Playwright objects are per thread)."""
    from axe_playwright_python.sync_playwright import Axe

    axe = Axe()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        while True:
            try:
                job = jobs.get_nowait()
            except queue.Empty:
                break
            try:
                results.put(capture_one(browser, axe, sessions, job))
            except Exception as exc:
                # A crash still reports the variant, so the scenario completes
                results.put(
                    {
                        "key": job[0],
                        "variant": job[4],
                        "axe": None,
                        "findings": {
                            "console_errors": [],
                            "horizontal_overflow": False,
                            "step_problem": f"capture failed: {type(exc).__name__}: {exc}"[:300],
                        },
                    }
                )
        browser.close()


def run_jobs(jobs: list[tuple], workers: int, sessions: dict, on_result) -> None:
    """Run jobs on `workers` browsers; with one worker they run in the listed order."""
    if not jobs:
        return
    todo: queue.Queue = queue.Queue()
    for job in jobs:
        todo.put(job)
    results: queue.Queue = queue.Queue()
    threads = [
        threading.Thread(target=worker, args=(todo, results, sessions), daemon=True)
        for _ in range(min(workers, len(jobs)))
    ]
    for t in threads:
        t.start()
    for _ in jobs:
        # No job takes 10 minutes; a silent wait means every browser thread died
        on_result(results.get(timeout=600))
    for t in threads:
        t.join()


def main(phase: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    SHEETS.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "report.json"
    report: dict = json.loads(report_path.read_text()) if report_path.exists() else {}
    chosen = selected(phase)
    with sync_playwright() as p:
        sessions = log_in(p, {sc[0] for sc in chosen})

    remaining: dict[str, int] = {}
    parallel_jobs: list[tuple] = []
    serial_jobs: list[tuple] = []
    for role, name, path, steps, opts in chosen:
        key = f"{role}--{name}"
        variants = opts.get("variants", ALL)
        report[key] = {
            # A re-capture keeps the phase the scenario belongs to
            "phase": report.get(key, {}).get("phase", phase),
            "path": path,
            "steps": [list(x) for x in steps],
            "variants": {},
            "axe": {},
        }
        remaining[key] = len(variants)
        target = serial_jobs if variants == ONE else parallel_jobs
        target += [(key, role, path, steps, v) for v in variants]

    def on_result(res: dict) -> None:
        key = res["key"]
        entry = report[key]
        entry["variants"][res["variant"]] = res["findings"]
        if res["axe"]:
            entry["axe"][res["axe"][0]] = res["axe"][1]
        remaining[key] -= 1
        if remaining[key] == 0:
            # Keep the variants in the contact sheet's order
            entry["variants"] = {v: entry["variants"][v] for v in ALL if v in entry["variants"]}
            sheet(key, list(entry["variants"]))
            report_path.write_text(json.dumps(report, indent=2))
            print("done", key, flush=True)  # noqa: T201

    start = time.monotonic()
    run_jobs(parallel_jobs, WORKERS, sessions, on_result)
    run_jobs(serial_jobs, 1, sessions, on_result)
    print(f"phase {phase}: {len(chosen)} scenarios in {time.monotonic() - start:.0f} s")  # noqa: T201
    write_index(report)


def sheet(key: str, variants: list[str]) -> None:
    """One contact sheet per scenario: a row per viewport, a column per language and theme."""
    rows: dict[str, list] = {}
    for variant in variants:
        vp_name = variant.split("-")[0]
        shot = SHOTS / f"{key}--{variant}.png"
        if not shot.exists():  # The capture failed before its screenshot
            continue
        img = Image.open(shot)
        img = img.crop(
            (
                0,
                0,
                img.width,
                min(img.height, {"desktop": 1200, "tablet": 1500, "phone": 1600}[vp_name]),
            )
        )
        scale = {"desktop": 520, "tablet": 420, "phone": 300}[vp_name] / img.width
        rows.setdefault(vp_name, []).append(
            (variant, img.resize((int(img.width * scale), int(img.height * scale))))
        )
    if not rows:
        return
    width = max(sum(i.width for _, i in r) + 12 * (len(r) + 1) for r in rows.values())
    height = sum(max(i.height for _, i in r) for r in rows.values()) + 34 * len(rows) + 12
    canvas = Image.new("RGB", (width, height), (120, 120, 120))
    draw = ImageDraw.Draw(canvas)
    y = 12
    for r in rows.values():
        x = 12
        for variant, img in r:
            draw.text((x, y), variant, fill=(255, 255, 255))
            canvas.paste(img, (x, y + 18))
            x += img.width + 12
        y += max(i.height for _, i in r) + 34
    canvas.save(SHEETS / f"{key}.png")


def write_index(report: dict) -> None:
    parts = [
        "<!doctype html><meta charset='utf-8'><title>LavBench visual check</title>",
        "<style>body{font-family:system-ui;margin:16px;background:#f4f4f5;color:#111}"
        "section{background:#fff;border-radius:8px;padding:12px;margin:0 0 20px}"
        "img{max-width:100%;border:1px solid #ccc}nav a{display:inline-block;margin:2px 8px 2px 0}"
        ".bad{color:#b91c1c}.ok{color:#15803d}pre{white-space:pre-wrap;font-size:12px}</style>",
        "<h1>LavBench visual check</h1>",
        f"<p>{len(report)} scenarios. Viewports: desktop 1280 px, tablet 820 px, phone 390 px; "
        "languages: English and Bulgarian; themes: dark and light. axe runs on desktop "
        "English.</p><nav>",
    ]
    parts += [f"<a href='#{html.escape(k)}'>{html.escape(k)}</a>" for k in report]
    parts.append("</nav>")
    for key, entry in report.items():
        errs = {v: d["console_errors"] for v, d in entry["variants"].items() if d["console_errors"]}
        over = [v for v, d in entry["variants"].items() if d["horizontal_overflow"]]
        probs = {v: d["step_problem"] for v, d in entry["variants"].items() if d["step_problem"]}
        axe_lines = [
            f"{theme}: {v['impact']} {v['id']} ({v['nodes']}) {html.escape(v['help'])}"
            for theme, vio in entry["axe"].items()
            for v in vio
        ]
        parts.append(
            f"<section id='{html.escape(key)}'><h2>{html.escape(key)}</h2>"
            f"<p>phase <b>{html.escape(entry['phase'])}</b>, "
            f"<code>{html.escape(entry['path'])}</code>, steps "
            f"<code>{html.escape(json.dumps(entry['steps']))}</code></p>"
        )
        parts.append(
            f"<p class='{'bad' if probs else 'ok'}'>Steps: "
            f"{'all worked' if not probs else html.escape(json.dumps(probs))}</p>"
        )
        parts.append(
            f"<p class='{'bad' if errs else 'ok'}'>Console errors: {len(errs)} variant(s)</p>"
        )
        for v, e in errs.items():
            parts.append(f"<pre>{html.escape(v)}: {html.escape(' | '.join(e))}</pre>")
        parts.append(
            f"<p class='{'bad' if over else 'ok'}'>Horizontal overflow: "
            f"{', '.join(over) or 'none'}</p>"
        )
        parts.append(
            f"<p class='{'bad' if axe_lines else 'ok'}'>axe: {len(axe_lines)} violation(s)</p>"
        )
        if axe_lines:
            parts.append("<pre>" + "\n".join(axe_lines) + "</pre>")
        parts.append(f"<img src='sheets/{html.escape(key)}.png' loading='lazy'><p>")
        parts += [
            f"<a href='shots/{html.escape(key)}--{v}.png'>{v}</a> " for v in entry["variants"]
        ]
        parts.append("</p></section>")
    (OUT / "index.html").write_text("\n".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "main")
