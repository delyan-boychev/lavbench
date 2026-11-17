#!/usr/bin/env python3
"""Translate LavBench content from English to Bulgarian using the Gemini API.

Translates:
  - frontend/public/locales/en/translation.json -> bg/translation.json
    (all UI strings and api.ERR_* messages; keys and structure preserved)
  - guides/en/*.md -> guides/bg/*.md
  - docs/README.md -> docs/README.bg.md
  - docs/source/*.md -> docs/source/bg/*.md          (only with --docs;
    guide symlinks are mirrored, only real files are translated)

The API key is read from the .gemini-api-key file in the repo root
(the value after '=', e.g. `GEMINI-API-KEY=AQ...`), exported as GEMINI_API_KEY,
and sent in the x-goog-api-key header (never in the URL).

Only what changed is translated. Git gives the EN version at the last commit
that touched the BG output (no state file needed), and:
  - UI strings: only keys that are new, missing in BG, or whose English
    changed since then are sent;
  - Markdown: only the sections (split at headings) that are new or changed
    are sent, with their previous English and Bulgarian as context; the other
    Bulgarian sections are kept verbatim. When the old English and the
    Bulgarian do not line up section by section, the whole file is translated.
Use --force for a full re-translation (for example after a terminology change).

Every run prints the tokens used and an estimated cost; --dry-run lists what
would be sent without calling the API.

Usage:
  python3 scripts/translate_gemini.py                # frontend + guides + docs README
  python3 scripts/translate_gemini.py --docs         # + docs/source
  python3 scripts/translate_gemini.py --force        # re-translate everything (costly)
  python3 scripts/translate_gemini.py --only readme  # just the docs README
  python3 scripts/translate_gemini.py --dry-run      # list what would be sent, no API calls
  python3 scripts/translate_gemini.py --flex         # Flex tier: half price, calls may take minutes
  python3 scripts/translate_gemini.py --model gemini-3.8-flash
  python3 scripts/translate_gemini.py --check        # terminology gate only, no API calls

Terminology lives in SYSTEM_PROMPT and is shared by the UI strings and every
document. After translating, a consistency gate fails on banned variants
(BANNED_TERMS) and warns about English prose left untranslated. Documents also
receive the real Bulgarian UI labels for the interface elements they mention.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".gemini-api-key"
STATE_FILE = ROOT / ".translation_state.json"
LOCALES_EN = ROOT / "frontend/public/locales/en/translation.json"
LOCALES_BG = ROOT / "frontend/public/locales/bg/translation.json"
GUIDES_EN = ROOT / "guides/en"
GUIDES_BG = ROOT / "guides/bg"
DOCS_EN = ROOT / "docs/source"
DOCS_BG = ROOT / "docs/source/bg"
README_EN = ROOT / "docs/README.md"
README_BG = ROOT / "docs/README.bg.md"

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-4-carbon"
MAX_BATCH_CHARS = 12000
SLEEP_BETWEEN_CALLS = 0.5
STANDARD_TIMEOUT = 300
FLEX_TIMEOUT = 900
# USD per 1M tokens (input, output with thinking), aistudio.google.com/docs/pricing; Flex is half
PRICES = {
    "gemini-4-carbon": (4.00, 20.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}
USAGE = {"calls": 0, "prompt": 0, "cached": 0, "output": 0, "thoughts": 0}
FLEX = False


def _repo_path(path: Path) -> str:
    """Repo-root-relative path with forward slashes (for git arguments)."""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def en_at_last_translation(src: Path, out: Path) -> str | None:
    """The EN text of *src* at the last commit that touched *out*, or None when there is none."""
    if not out.exists():
        return None
    try:
        last = subprocess.run(
            ["git", "rev-list", "-1", "HEAD", "--", _repo_path(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not last:
            return None
        return subprocess.run(
            ["git", "show", f"{last}:{_repo_path(src)}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return None


def source_changed_since_last_translation(src: Path, out: Path) -> bool:
    """True when *src* differs from the EN version that produced *out* (or that is unknown)."""
    old = en_at_last_translation(src, out)
    return old is None or old != src.read_text(encoding="utf-8")

# Single source of Bulgarian terminology for the UI strings and every document.
# Change a term here, then re-run with --force so all outputs follow it
SYSTEM_PROMPT = """You are a senior technical translator from English to Bulgarian for LavBench, the scoring platform of the Bulgarian national AI olympiad. Your readers are Bulgarian administrators, jury members, school students and developers. The Bulgarian must read as if a careful Bulgarian engineer wrote it originally, not as a translation.

TERMINOLOGY (mandatory; the same English term always maps to the same Bulgarian term, in every file and every UI string):
- challenge = състезание; stage = етап; task = задача
- submission = решение (a competitor's submitted notebook or file); to submit = изпращам решение; submitting = изпращане
- notebook (Jupyter) = бележник; cell = клетка; baseline notebook = базов бележник
- leaderboard = класация; public / private score = публичен / частен резултат
- evaluation = оценяване; to evaluate = оценявам; custom evaluator = персонализиран оценител; metric = метрика
- labels / ground truth = етикети / еталонни стойности
- jury = жури; competitor = състезател; admin = администратор
- deadline = краен срок; grace period = гратисен период (never "толерансен период"); quota = квота; rate limit = ограничение на честотата
- final selection = финален избор; final submission = финално решение; to star a submission = маркирам решение със звезда
- double-blind = двойно сляпо; alias = псевдоним; finalization = финализиране
- worker / worker node / evaluation worker = работен възел (plural: работни възли); never "уъркър" or "работник"
- queue = опашка; heartbeat = сигнал за активност; consumer (of a queue) = консуматор
- backup = резервно копие (plural: резервни копия); never "архив" for a backup
- archive (a ZIP file) = архив; archived challenge = архивирано състезание
- sandbox = изолирана среда; never "пясъчна среда"
- container = контейнер; Docker image = Docker образ; image build = изграждане на образ
- pipeline = конвейер; never "пайплайн"
- endpoint = крайна точка; request = заявка; response = отговор
- logs = журнали; log line = ред от журнала; never "логове"
- live / real time = на живо / в реално време; stream (SSE) = поток; streaming = поточно предаване
- cache = кеш; lock = заключване; broker = брокер; outage = прекъсване
- upload = качване; download = изтегляне; panel = панел; dashboard = табло
- environment variable = променлива на средата; configuration = конфигурация; settings = настройки
- deploy / deployment = внедряване; health check = проверка за изправност; lifecycle = жизнен цикъл
- workspace (nanoColab) = работно пространство; task package = пакет на задачата; manifest = манифест
- wizard = съветник; dry run = пробно изпълнение; draft = чернова; publish = публикувам
- authentication = автентификация; authorization = оторизация; login / sign in = вход
- encryption / encrypted = криптиране / криптиран; never "шифрован"
- online / stale (worker state) = на линия / без сигнал

KEEP EXACTLY AS IN THE SOURCE (never translate or transliterate):
- code blocks, inline code in backticks, file names and paths, URLs, API paths, HTTP methods and status codes
- environment variable names, config keys, error codes (ERR_*, WARN_*), JSON keys, status values shown in backticks
- the word "traceback"
- product and technology names (never transliterate, never write ЛавБенч): LavBench, nanoColab, JupyterHub, Jupyter, Docker, Docker Compose, Redis, PostgreSQL, Celery, Flask, nginx, Gemini, Hugging Face, Statuspage, GitHub, GCP, GPU, CPU, RAM, SSE, JWT, OIDC, ZIP, Parquet, parquet
- placeholders such as {{count}}, {name}, %s, <id>, and HTML or Markdown markup

STYLE:
- Formal, clear technical Bulgarian with natural Bulgarian word order. Avoid calques and English sentence structure; restructure the sentence when a literal rendering sounds foreign.
- Do not transliterate English words when an established Bulgarian term exists.
- Address the reader with polite plural imperatives: "Натиснете", "Изберете", "Качете".
- Use Bulgarian quotation marks „…“ in running text; leave quotes inside code untouched.
- Keep numbers, size units and limits exactly as in the source (10 MB, 2 GB, 2 GiB, 180).
- Write time units the Bulgarian way: s = сек., min = мин, h = ч ("30 s" = „30 сек.“, "24 h" = „24 ч“), except inside code or placeholders.
- Translate every sentence. Never leave English prose untranslated; only the items listed under KEEP stay in English.
- Do not add, remove, merge or reorder content. Do not add explanations or notes of your own.
- Avoid tautologies (for example "изолация на изолираната среда"); rephrase instead.
- Before answering, check your whole output against TERMINOLOGY: every listed English term must use its mandated Bulgarian term, even inside UI labels and headings. If a UI label in UI LABELS conflicts with TERMINOLOGY, follow TERMINOLOGY.
"""

ROLE_CONTEXT = {
    "admin_guide": (
        "This document is the ADMINISTRATOR guide: challenge and stage lifecycle, task setup, "
        "sandbox and image builds, metrics and evaluators, users and credentials, backups, "
        "worker nodes and the system status panel, audit logs. Write for a technical "
        "administrator."
    ),
    "jury_guide": (
        "This document is the JURY guide: the jury permission matrix, onboarding competitors "
        "and their credentials, live submission tracking, baseline checks, diagnosing task "
        "problems, scores and manual points, exports. Write for a jury member."
    ),
    "competitor_guide": (
        "This document is the COMPETITOR guide, read by school students taking part in the "
        "olympiad: logging in, stages and tasks, baseline notebooks, producing "
        "submission.parquet, submitting and tracking submissions, the leaderboard. Write "
        "clearly for students."
    ),
    "architecture.md": (
        "This document is the ARCHITECTURE reference: components, the submission pipeline, "
        "sandbox isolation, image builds, the evaluation engine, live updates, backups, worker "
        "budgeting and the status endpoints. Write for developers and operators."
    ),
    "README.md": (
        "This is the README of the docs/ folder: a developer and documentation guide with a "
        "sitemap, frontend and backend guidelines, evaluator templates and the Sphinx build. "
        "Write for a developer contributing to the project."
    ),
}


def load_api_key(key_file: Path | None = None) -> str:
    """Read the key from the key file and export it as GEMINI_API_KEY."""
    key_file = key_file or KEY_FILE
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    if not key_file.exists():
        sys.exit(f"ERROR: API key file not found: {key_file}")
    raw = key_file.read_text(encoding="utf-8").strip()
    if "=" in raw:
        raw = raw.split("=", 1)[1]
    key = raw.strip()
    if not key:
        sys.exit("ERROR: .gemini-api-key is empty")
    os.environ["GEMINI_API_KEY"] = key
    return key


def thinking_config(model: str) -> dict:
    """The least thinking each model allows; thinking tokens are billed as output."""
    if model.startswith("gemini-2.5"):
        return {"thinkingBudget": 0}
    # Only the Flash-Lite models accept "minimal"; the others refuse it with HTTP 400
    return {"thinkingLevel": "minimal" if "flash-lite" in model else "low"}


def record_usage(data: dict) -> None:
    meta = data.get("usageMetadata") or {}
    USAGE["calls"] += 1
    USAGE["prompt"] += int(meta.get("promptTokenCount") or 0)
    USAGE["cached"] += int(meta.get("cachedContentTokenCount") or 0)
    USAGE["output"] += int(meta.get("candidatesTokenCount") or 0)
    USAGE["thoughts"] += int(meta.get("thoughtsTokenCount") or 0)


def print_usage(model: str) -> None:
    if not USAGE["calls"]:
        return
    line = (
        f"usage: {USAGE['calls']} call(s), {USAGE['prompt']} input tokens "
        f"({USAGE['cached']} cached), {USAGE['output']} output, {USAGE['thoughts']} thinking"
    )
    if model in PRICES:
        price_in, price_out = PRICES[model]
        cost = (
            USAGE["prompt"] * price_in + (USAGE["output"] + USAGE["thoughts"]) * price_out
        ) / 1_000_000
        line += f", about ${cost / 2 if FLEX else cost:.4f}"
    print(line)


def gemini_call(
    key: str,
    model: str,
    prompt: str,
    retries: int = 3,
    system: str | None = None,
    json_mode: bool = False,
) -> str:
    """Run one prompt against the Gemini API and return the raw text."""
    # The key travels in a header, never in the URL, so it cannot leak into logs
    url = API_URL.format(model=urllib.parse.quote(model))
    config: dict = {"thinkingConfig": thinking_config(model)}
    if json_mode:
        config["responseMimeType"] = "application/json"
    payload: dict = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if FLEX:
        payload["service_tier"] = "flex"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key}
    )
    timeout = FLEX_TIMEOUT if FLEX else STANDARD_TIMEOUT
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            record_usage(data)
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code not in (429, 500, 503) or attempt >= retries:
                raise RuntimeError(f"Gemini API HTTP {e.code}: {detail}") from None
            time.sleep(5 * attempt)
        except TimeoutError:
            # A timed-out request may still be generated and billed, so it is never repeated
            raise RuntimeError(f"Gemini API call timed out after {timeout} s") from None
        except urllib.error.URLError as e:
            if attempt >= retries:
                raise RuntimeError(f"Gemini API call failed: {e.reason}") from None
            time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def flatten(d: dict, prefix: str = "", out: dict | None = None) -> dict[str, str]:
    out = out if out is not None else {}
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flatten(v, path, out)
        elif isinstance(v, str):
            out[path] = v
    return out


def group_context(
    batch: dict[str, str], flat_en: dict[str, str], flat_bg: dict[str, str], per_group: int = 4
) -> dict[str, dict[str, str]]:
    """A few translated keys from the batch's groups, so new strings take the same form."""
    groups = {p.rsplit(".", 1)[0] for p in batch if "." in p}
    context: dict[str, dict[str, str]] = {}
    for group in sorted(groups):
        siblings = [
            p
            for p in flat_en
            if p.rsplit(".", 1)[0] == group and p not in batch and p in flat_bg
        ]
        for p in siblings[:per_group]:
            context[p] = {"en": flat_en[p], "bg": flat_bg[p]}
    return context


def translate_flat_batch(
    model: str,
    batch: dict[str, str],
    prev_bg: dict[str, str],
    old_en: dict[str, str],
    context: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """Translate one flat batch {dot.path: value}; returns None on failure.

    Each key carries its existing Bulgarian and, when the English changed, the
    English that Bulgarian was made from, so correct wording is reused.
    """
    payload: dict[str, dict[str, str]] = {}
    for p, v in batch.items():
        entry = {"en": v, "bg": prev_bg.get(p, "(none)")}
        if p in prev_bg and p in old_en and old_en[p] != v:
            entry["old_en"] = old_en[p]
        payload[p] = entry
    request = {"translate": payload, "context": context}
    prompt = UI_PROMPT + "\n" + json.dumps(request, ensure_ascii=False, indent=1)
    text = gemini_call(
        os.environ["GEMINI_API_KEY"], model, prompt, system=SYSTEM_PROMPT, json_mode=True
    )
    try:
        translated = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        print("  !! response was not valid JSON — keeping original values")
        return None
    if not isinstance(translated, dict) or set(translated) != set(batch):
        print(f"  !! key mismatch ({len(batch)} in, {len(translated)} out) — keeping originals")
        return None
    return {p: (v if isinstance(v, str) else batch[p]) for p, v in translated.items()}


def changed_keys(
    flat_en: dict[str, str], flat_bg: dict[str, str], old_en: dict[str, str] | None
) -> list[str]:
    """Keys that are missing in BG or whose English changed since the BG was committed."""
    return [
        p
        for p, v in flat_en.items()
        if old_en is None or p not in flat_bg or p not in old_en or old_en[p] != v
    ]


def translate_locales(model: str, dry_run: bool, force: bool = False) -> None:
    print("== frontend/public/locales ==")
    flat_en = flatten(json.loads(LOCALES_EN.read_text(encoding="utf-8")))
    flat_bg = flatten(json.loads(LOCALES_BG.read_text(encoding="utf-8")))
    old_en: dict[str, str] | None = None
    if not force:
        old_text = en_at_last_translation(LOCALES_EN, LOCALES_BG)
        try:
            old_en = flatten(json.loads(old_text)) if old_text else None
        except json.JSONDecodeError:
            old_en = None
    paths = changed_keys(flat_en, flat_bg, old_en)
    if not paths:
        print("  no new or changed keys — skip")
        return
    chars = sum(len(flat_en[p]) + len(flat_bg.get(p, "")) for p in paths)
    print(f"  {len(paths)} of {len(flat_en)} keys are new or changed ({chars} characters)")
    if dry_run:
        for p in paths[:50]:
            print(f"    {p}")
        if len(paths) > 50:
            print(f"    ... and {len(paths) - 50} more")
        return

    batches: list[dict[str, str]] = []
    current: dict[str, str] = {}
    size = 0
    for path in paths:
        val = flat_en[path]
        # Count the Bulgarian context too, so a batch stays a modest request
        cost = len(val) + len(flat_bg.get(path, ""))
        if size + cost > MAX_BATCH_CHARS and current:
            batches.append(current)
            current, size = {}, 0
        current[path] = val
        size += cost
    if current:
        batches.append(current)

    new_bg = dict(flat_bg)
    ok = 0
    for i, batch in enumerate(batches, 1):
        print(f"  batch {i}/{len(batches)} ({len(batch)} keys)")
        context = group_context(batch, flat_en, flat_bg)
        result = translate_flat_batch(model, batch, flat_bg, old_en or {}, context)
        if result is not None:
            new_bg.update(result)
            ok += len(result)
        time.sleep(SLEEP_BETWEEN_CALLS)

    # Merge: structure mirrors en (all keys present), keep any bg-only extras.
    merged: dict = {}
    for path, val in flat_en.items():
        node = merged
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = new_bg.get(path, val)
    for path, val in flat_bg.items():
        if path not in flat_en:
            node = merged
            parts = path.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = val

    LOCALES_BG.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  wrote {LOCALES_BG} ({ok}/{len(flat_en)} strings updated)")


UI_PROMPT = """Translate the interface strings in the JSON object below from English to Bulgarian, following every rule in your instructions.

The JSON has two objects. "translate" holds the strings to translate: each entry has "en" (the English source), "bg" (the existing Bulgarian translation, or "(none)" for a new key) and, when the English changed, "old_en" (the English that the existing Bulgarian was made from). "context" holds existing translations from the same groups, for reference only: give new strings the same style and grammatical form as their group (for example nouns for audit log actions, imperatives for buttons) and do not return them.

Output rules:
- Return only a flat JSON object {"dot.path": "Bulgarian text"} with exactly the keys of "translate". No code fences, no comments, no nested objects.
- Keep placeholders ({{count}}, {{name}}, {name}, %s, $1), HTML and JSX tags exactly.
- Keys ending in _one and _other are plural forms; give each the correct Bulgarian form for that count.

Interface style:
- Buttons and short actions use the singular imperative usual in Bulgarian interfaces: „Запази“, „Изтрий“, „Опитай отново“, „Изпрати решение“.
- Messages that address the user use polite plural: „Моля, изберете…“, „Качете файл…“.
- Bulgarian does not use title case: capitalize only the first word and proper nouns ("Public Score" = „Публичен резултат“). Keep ALL CAPS only where the English is ALL CAPS.
- Keep strings about as short as the English; interface space is limited.

Reuse the existing "bg" value verbatim when it is correct, natural and matches the TERMINOLOGY. Change it when the English changed, when it is inaccurate or unnatural, or when it uses a term other than the TERMINOLOGY (for example „толерансен период“ must become „гратисен период“, and every "final selection" must be „финален избор“).

JSON:
"""

MD_PROMPT = """Translate the Markdown document below from English to Bulgarian, following every rule in your instructions.

Output rules:
- Return only the translated document, without code fences around it.
- Preserve all Markdown exactly: headings, lists, tables (same number of columns and rows), links, images, bold and italics, blank lines and line breaks.
- Translate headings, table text, link text and image alt text; never change link targets.

ROLE CONTEXT:
{role}

UI LABELS: the application's real Bulgarian interface labels. When the document refers to one of these interface elements, use exactly this Bulgarian label (inside „…“ or bold, as in the source); inflect it
(for example add the definite article) only where Bulgarian grammar requires it:
{ui_labels}

EXISTING BULGARIAN TRANSLATION (reference only). Reuse its wording where it is correct and matches the TERMINOLOGY. Wherever it uses a different term than the TERMINOLOGY (for example "уъркър", "архив" for a backup, "пясъчна среда", "пайплайн", "логове"), replace it with the mandated term. Retranslate anything that is unnatural, inaccurate or left in English:
{previous}

DOCUMENT:
{text}
"""

MD_SECTIONS_PROMPT = """Translate the sections of a Markdown document in the JSON object below from English to Bulgarian, following every rule in your instructions. The other sections of the document already have a reviewed Bulgarian translation and are not sent.

Each entry has "en" (the English section to translate) and, when this part existed before, "old_en" (its previous English) and "bg" (the existing Bulgarian translation of "old_en"). Reuse the existing Bulgarian wording verbatim where the English did not change and the wording is correct and matches the TERMINOLOGY; translate what changed.

Output rules:
- Return only a JSON object {{"id": "Bulgarian Markdown"}} with exactly the same ids.
- Preserve all Markdown exactly: headings (same level and count), lists, tables (same number of columns and rows), links, images, code blocks, bold and italics, blank lines and line breaks.
- Translate headings, table text, link text and image alt text; never change link targets.

ROLE CONTEXT:
{role}

UI LABELS: the application's real Bulgarian interface labels. When a section refers to one of these interface elements, use exactly this Bulgarian label (inside „…“ or bold, as in the source); inflect it (for example add the definite article) only where Bulgarian grammar requires it:
{ui_labels}

JSON:
{sections}
"""

FENCE_START = ("```", "~~~")
HEADING = re.compile(r"^(#{1,6})\s")


def split_sections(text: str) -> list[str]:
    """Split Markdown before each heading outside code blocks; the parts join back losslessly."""
    sections: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if fence:
            if stripped.startswith(fence):
                fence = None
        elif stripped.startswith(FENCE_START):
            fence = stripped[:3]
        elif HEADING.match(line) and current:
            sections.append("".join(current))
            current = []
        current.append(line)
    if current:
        sections.append("".join(current))
    return sections


def _heading_level(section: str) -> int:
    match = HEADING.match(section)
    return len(match.group(1)) if match else 0


def plan_sections(old_en: str, new_en: str, bg: str) -> list[str | dict[str, str]] | None:
    """Kept Bulgarian sections (str) and units to translate (dict); None if EN and BG differ in shape."""
    old_parts, new_parts = split_sections(old_en), split_sections(new_en)
    bg_parts = split_sections(bg)
    if len(old_parts) != len(bg_parts) or any(
        _heading_level(o) != _heading_level(b) for o, b in zip(old_parts, bg_parts, strict=True)
    ):
        return None
    plan: list[str | dict[str, str]] = []
    # Trailing blank lines do not count as a change; kept sections take the new spacing
    matcher = difflib.SequenceMatcher(
        None, [p.rstrip() for p in old_parts], [p.rstrip() for p in new_parts], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                new = new_parts[j1 + k]
                plan.append(bg_parts[i1 + k].rstrip() + new[len(new.rstrip()) :])
        elif op == "replace" and i2 - i1 == j2 - j1:
            plan.extend(
                {"en": new_parts[j1 + k], "old_en": old_parts[i1 + k], "bg": bg_parts[i1 + k]}
                for k in range(j2 - j1)
            )
        elif op == "replace":
            plan.append(
                {
                    "en": "".join(new_parts[j1:j2]),
                    "old_en": "".join(old_parts[i1:i2]),
                    "bg": "".join(bg_parts[i1:i2]),
                }
            )
        elif op == "insert":
            plan.append({"en": "".join(new_parts[j1:j2])})
    return plan


def _role(filename: str | None) -> str:
    return ROLE_CONTEXT.get(filename or "", "") or (
        "This document is platform documentation for LavBench, an ML "
        "competition platform. Write clearly and professionally."
    )


def _heading_count(text: str) -> int:
    return sum(1 for part in split_sections(text) if HEADING.match(part))


def translate_sections(
    model: str, units: list[dict[str, str]], filename: str | None
) -> list[str] | None:
    """Translate the changed sections in one call; None when the reply does not fit them."""
    payload = {str(i): unit for i, unit in enumerate(units, 1)}
    prompt = MD_SECTIONS_PROMPT.format(
        role=_role(filename),
        ui_labels=ui_labels("".join(unit["en"] for unit in units)),
        sections=json.dumps(payload, ensure_ascii=False, indent=1),
    )
    text = gemini_call(
        os.environ["GEMINI_API_KEY"], model, prompt, system=SYSTEM_PROMPT, json_mode=True
    )
    try:
        reply = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        print("  !! response was not valid JSON")
        return None
    if not isinstance(reply, dict) or set(reply) != set(payload):
        print("  !! the reply does not have one entry per section")
        return None
    translated = []
    for key, unit in payload.items():
        value = reply[key]
        if not isinstance(value, str) or _heading_count(value) != _heading_count(unit["en"]):
            print(f"  !! section {key}: the headings do not match the English")
            return None
        trailing = unit["en"][len(unit["en"].rstrip()) :]
        translated.append(value.strip() + trailing)
    return translated


def translate_document(
    model: str, src: Path, out: Path, filename: str, dry_run: bool, force: bool
) -> None:
    """Translate the changed sections of one Markdown file, or the whole file when needed."""
    content = src.read_text(encoding="utf-8")
    previous_bg = out.read_text(encoding="utf-8") if out.exists() else None
    old_en = None if force else en_at_last_translation(src, out)
    if old_en is not None and old_en == content:
        print(f"  {_repo_path(src)}: unchanged since last translation — skip")
        return
    plan = plan_sections(old_en, content, previous_bg) if old_en and previous_bg else None
    if plan is None:
        reason = "--force" if force else "no aligned previous translation"
        print(f"  {_repo_path(src)} -> {_repo_path(out)}: whole file ({reason}, {len(content)} chars)")
        if dry_run:
            return
        translated = translate_markdown(model, content, filename=filename, previous_bg=previous_bg)
        result = translated + "\n"
    else:
        units = [part for part in plan if isinstance(part, dict)]
        chars = sum(len(value) for unit in units for value in unit.values())
        print(
            f"  {_repo_path(src)} -> {_repo_path(out)}: {len(units)} changed section(s), "
            f"{chars} characters"
        )
        for unit in units:
            print(f"    {unit['en'].splitlines()[0][:80] if unit['en'].strip() else '(blank)'}")
        if dry_run or not units:
            if not dry_run:
                kept = "".join(part for part in plan if isinstance(part, str))
                out.write_text(kept, encoding="utf-8")
            return
        done = translate_sections(model, units, filename)
        if done is None:
            print(f"  !! {_repo_path(out)} left unchanged; fix the cause or use --force")
            return
        pieces = iter(done)
        result = _relink_anchors(
            content, "".join(part if isinstance(part, str) else next(pieces) for part in plan)
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding="utf-8")


def _gh_slug(heading: str) -> str:
    """GitHub-style anchor slug for a heading line."""
    slug = re.sub(r"[`*_\[\]]", "", heading).lower()
    slug = re.sub(r"[^a-zа-я0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug


def _relink_anchors(src: str, translated: str) -> str:
    """Rewrite (#en-anchor) links to the translated headings' anchors.

    The model is told to keep section structure identical, so headings line up
    by index between src and translated; map EN slugs to their BG counterparts.
    """
    en_headings = [m for m in re.finditer(r"^#{1,6}\s+(.+)$", src, re.M)]
    bg_headings = [m for m in re.finditer(r"^#{1,6}\s+(.+)$", translated, re.M)]
    if len(en_headings) != len(bg_headings):
        return translated
    mapping: dict[str, str] = {}
    for en_m, bg_m in zip(en_headings, bg_headings):
        en_slug = _gh_slug(en_m.group(1))
        bg_slug = _gh_slug(bg_m.group(1))
        if en_slug and bg_slug and en_slug != bg_slug:
            mapping[en_slug] = bg_slug
    if not mapping:
        return translated
    for en_slug, bg_slug in mapping.items():
        translated = re.sub(
            rf"\(\s*#\s*{re.escape(en_slug)}\s*\)", f"(#{bg_slug})", translated
        )
    return translated


def ui_labels(text: str) -> str:
    """List the real Bulgarian UI labels for bold or quoted phrases that are UI strings."""
    try:
        en = flatten(json.loads(LOCALES_EN.read_text(encoding="utf-8")))
        bg = flatten(json.loads(LOCALES_BG.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return "(none)"
    by_text: dict[str, dict[str, str]] = {}
    for path, value in en.items():
        if path in bg and 2 < len(value) <= 80:
            by_text.setdefault(value.strip().lower(), {}).setdefault(bg[path], path)
    phrases = set(re.findall(r"\*\*([^*\n]{3,80})\*\*", text))
    phrases |= set(re.findall(r'"([^"\n]{3,80})"', text))
    lines = []
    for p in sorted(phrases):
        labels = by_text.get(p.strip().lower())
        if not labels:
            continue
        if len(labels) == 1:
            lines.append(f"- {p.strip()} = {next(iter(labels))}")
        else:
            # One English label can mean a button and an audit entry; the key tells which is which
            choices = "; ".join(f"{label} ({path})" for label, path in labels.items())
            lines.append(f"- {p.strip()} = one of: {choices}; pick the one that fits the sentence")
    return "\n".join(lines) or "(none)"


def translate_markdown(
    model: str,
    text: str,
    filename: str | None = None,
    previous_bg: str | None = None,
) -> str:
    previous = previous_bg or "(no previous translation; translate from scratch)"
    prompt = MD_PROMPT.format(
        role=_role(filename),
        ui_labels=ui_labels(text),
        previous=previous[:90000],
        text=text[:90000],
    )
    translated = _strip_fences(
        gemini_call(os.environ["GEMINI_API_KEY"], model, prompt, system=SYSTEM_PROMPT)
    )
    return _relink_anchors(text, translated)


def translate_dir(
    model: str,
    src_dir: Path,
    dst_dir: Path,
    dry_run: bool,
    names: list[str] | None = None,
    force: bool = False,
) -> None:
    src_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(src_dir.glob("*.md"))
    for f in files:
        if names is not None and f.name not in names:
            continue
        out = dst_dir / f.name
        if f.is_symlink():
            # The source is a symlink (guides are linked into docs/source):
            # mirror the link to the already-translated bg target instead of
            # re-translating the same content.
            target = f.readlink()
            if not target.is_absolute():
                target = f.parent / target
            bg_target = Path(str(target).replace("/en/", "/bg/", 1))
            if not bg_target.exists():
                print(f"  !! {f.relative_to(ROOT)}: bg target missing: {bg_target}")
                continue
            if (
                out.is_symlink()
                and os.path.normpath(os.path.join(out.parent, os.readlink(out)))
                == os.path.normpath(bg_target)
            ):
                print(f"  {f.name}: symlink ok (unchanged)")
                continue
            if not dry_run:
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists() or out.is_symlink():
                    out.unlink()
                out.symlink_to(os.path.relpath(bg_target, out.parent))
            print(f"  {f.name}: symlinked -> {bg_target.relative_to(ROOT)}")
            continue
        translate_document(model, f, out, f.name, dry_run, force)
        time.sleep(SLEEP_BETWEEN_CALLS)


# Variants that must never appear in Bulgarian output: pattern -> mandated term
BANNED_TERMS = {
    r"уъркър": "работен възел",
    r"пясъчн\w* сред": "изолирана среда",
    r"пайплайн": "конвейер",
    r"логов[еи]": "журнали",
    r"толерансн\w* период": "гратисен период",
    r"житейск\w* цикъл|житейск\w* цикли": "жизнен цикъл",
    r"ЛавБенч": "LavBench",
    r"шифрова\w*": "криптиран",
}
ENGLISH_RUN = re.compile(r"(?:\b[A-Za-z][a-z'-]+\b[\s,]+){4,}")


def _bg_outputs() -> list[Path]:
    files = [LOCALES_BG, README_BG]
    files += sorted(GUIDES_BG.glob("*.md"))
    files += [f for f in sorted(DOCS_BG.glob("*.md")) if not f.is_symlink()]
    return [f for f in files if f.exists()]


def check_consistency() -> int:
    """Report banned terminology variants (errors) and leftover English prose (warnings)."""
    errors = 0
    warnings = 0
    for path in _bg_outputs():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            lines = [f"{k}: {v}" for k, v in flatten(json.loads(text)).items()]
        else:
            lines = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
            lines = lines.splitlines()
        rel = path.relative_to(ROOT)
        for no, line in enumerate(lines, 1):
            for pattern, mandated in BANNED_TERMS.items():
                for m in re.finditer(pattern, line, re.IGNORECASE):
                    errors += 1
                    print(f"  ERROR {rel}:{no}: \"{m.group(0)}\" -> use \"{mandated}\"")
            if path.suffix == ".md":
                prose = re.sub(r"`[^`]*`|\]\([^)]*\)|https?://\S+", " ", line)
                if ENGLISH_RUN.search(prose):
                    warnings += 1
                    print(f"  warning {rel}:{no}: possible untranslated English: {line.strip()[:120]}")
    print(f"consistency: {errors} error(s), {warnings} warning(s)")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate LavBench content EN -> BG with Gemini")
    parser.add_argument("--docs", action="store_true", help="also translate docs/source/*.md")
    parser.add_argument("--dry-run", action="store_true", help="preview only, don't write files")
    parser.add_argument(
        "--force",
        action="store_true",
        help="translate everything, bypassing git change detection",
    )
    parser.add_argument(
        "--only", choices=["locales", "guides", "docs", "readme"], help="translate only this target"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model id")
    parser.add_argument(
        "--flex",
        action="store_true",
        help="use the Flex tier: half price, but each call may take minutes",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only check the Bulgarian outputs for banned terms (no API calls)",
    )
    parser.add_argument("--key-file", default=str(KEY_FILE), help="path to the API key file")
    args = parser.parse_args()

    if args.check:
        sys.exit(1 if check_consistency() else 0)

    global FLEX
    FLEX = args.flex
    if not args.dry_run:
        load_api_key(Path(args.key_file))
    print(f"model: {args.model}  dry-run: {args.dry_run}  force: {args.force}  flex: {args.flex}")

    try:
        if not args.only or args.only == "locales":
            translate_locales(args.model, args.dry_run, force=args.force)
        if not args.only or args.only == "guides":
            print("== guides ==")
            translate_dir(args.model, GUIDES_EN, GUIDES_BG, args.dry_run, force=args.force)
        if (not args.only or args.only == "readme") and README_EN.exists():
            print("== docs/README ==")
            translate_document(
                args.model, README_EN, README_BG, "README.md", args.dry_run, args.force
            )
        if args.only == "docs" or (args.docs and not args.only):
            print("== docs ==")
            translate_dir(args.model, DOCS_EN, DOCS_BG, args.dry_run, force=args.force)
    finally:
        print_usage(args.model)

    if not args.dry_run:
        print("== consistency ==")
        if check_consistency():
            sys.exit(1)


if __name__ == "__main__":
    main()
