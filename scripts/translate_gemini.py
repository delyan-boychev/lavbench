#!/usr/bin/env python3
"""Translate LavBench content from English to Bulgarian with the Gemini Interactions API.

Translates:
  - frontend/public/locales/en/translation.json -> bg/translation.json
    (all UI strings and api.ERR_* messages; keys and structure preserved)
  - guides/en/*.md -> guides/bg/*.md
  - docs/README.md -> docs/README.bg.md
  - docs/source/*.md -> docs/source/bg/*.md          (only with --docs;
    guide symlinks are mirrored, only real files are translated)

Calls go through Google's google-genai SDK (pinned in backend/dev-requirements.txt, so
run the script in the lavbench_backend environment). Interactions are sent with
store=false, so Google keeps no copy of the documents. The API key is read from the
.gemini-api-key file in the repo root (the value after '=', e.g. `GEMINI-API-KEY=AQ...`)
or from GEMINI_API_KEY.

Only what changed is translated. Git gives the EN version at the last commit
that touched the BG output (no state file needed), and:
  - UI strings: only keys that are new, missing in BG, or whose English
    changed since then are sent;
  - Markdown: the changed sections are split into blocks (paragraphs, list items,
    table rows, headings, code blocks) and only the changed blocks are sent, each
    with its previous English and Bulgarian, or with the section heading and a
    neighbouring Bulgarian block when it is new. Unchanged and moved blocks keep
    their Bulgarian. A section whose old English and Bulgarian do not have the same
    blocks is sent whole, a reply whose blocks do not match its English is retried
    once as whole sections, and if that fails too the file is left unchanged. When
    the sections themselves do not line up, the whole file is translated.
Use --force for a full re-translation (for example after a terminology change).

Every run prints the tokens the API reports (input, cached, output, thinking) per
document and in total. --dry-run lists what would be sent with an estimate of the
tokens, without calling the API; --max-tokens stops a run before any call when the
estimate is above the limit.

Usage:
  python3 scripts/translate_gemini.py                # frontend + guides + docs README
  python3 scripts/translate_gemini.py --docs         # + docs/source
  python3 scripts/translate_gemini.py --force        # re-translate everything (costly)
  python3 scripts/translate_gemini.py --only readme  # just the docs README
  python3 scripts/translate_gemini.py --dry-run      # list what would be sent, no API calls
  python3 scripts/translate_gemini.py --max-tokens 30000  # refuse a run estimated above this
  python3 scripts/translate_gemini.py --flex         # Flex tier: calls may take minutes
  python3 scripts/translate_gemini.py --model gemini-3.8-flash
  python3 scripts/translate_gemini.py --check        # terminology gate only, no API calls

Terminology lives in SYSTEM_PROMPT and is shared by the UI strings and every
document. After translating, a consistency gate fails on banned variants
(BANNED_TERMS) and warns about English prose left untranslated. Documents also
receive the real Bulgarian UI labels for the interface elements they mention.
"""

# ruff: noqa: E501, RUF001, S603, S607, T201

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".gemini-api-key"
LOCALES_EN = ROOT / "frontend/public/locales/en/translation.json"
LOCALES_BG = ROOT / "frontend/public/locales/bg/translation.json"
GUIDES_EN = ROOT / "guides/en"
GUIDES_BG = ROOT / "guides/bg"
DOCS_EN = ROOT / "docs/source"
DOCS_BG = ROOT / "docs/source/bg"
README_EN = ROOT / "docs/README.md"
README_BG = ROOT / "docs/README.bg.md"

DEFAULT_MODEL = "gemini-4-carbon"
MAX_BATCH_CHARS = 12000
SLEEP_BETWEEN_CALLS = 0.5
STANDARD_TIMEOUT = 300
FLEX_TIMEOUT = 900
# HTTP statuses retried with exponential backoff; a timed-out call may still be billed, so it is never repeated
RETRY_STATUSES = (429, 500, 503)
API_ATTEMPTS = 3
RETRY_BASE_SECONDS = 5
# Token estimate for --dry-run and --max-tokens: characters per token, Bulgarian length
# relative to English, JSON overhead per reply entry and thinking per call
CHARS_PER_TOKEN = 3.0
BG_LENGTH_RATIO = 1.2
JSON_CHARS_PER_ENTRY = 16
THINKING_TOKENS_PER_CALL = 1000
# Bulgarian context sent with a new block: at most this many characters of its neighbour
NEIGHBOUR_CONTEXT_CHARS = 300
USAGE = {"calls": 0, "input": 0, "cached": 0, "output": 0, "thoughts": 0}
ESTIMATE = {"calls": 0, "input": 0, "output": 0}
FLEX = False
MAX_TOKENS: int | None = None
_CLIENT: Any = None


def _repo_path(path: Path) -> str:
    """Repo-root-relative path with forward slashes (for git arguments)."""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def at_last_translation(path: Path, out: Path) -> str | None:
    """The text of *path* at the last commit that touched *out*, or None when there is none."""
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
            ["git", "show", f"{last}:{_repo_path(path)}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return None


def en_at_last_translation(src: Path, out: Path) -> str | None:
    """The EN text of *src* at the last commit that touched *out*, or None when there is none."""
    return at_last_translation(src, out)


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
- emergency upload (the per-task switch used during a nanoColab outage) = аварийно качване; never "директно качване"
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
- Machine (a workspace's compute profile) = машина; Storage per student = хранилище за състезател
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
    """Read the key from GEMINI_API_KEY or the key file and export it as GEMINI_API_KEY."""
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


def thinking_level(model: str) -> str:
    """The least thinking each model allows; thinking tokens are billed as output."""
    # Only the Flash-Lite models accept "minimal"; the others refuse it with HTTP 400
    return "minimal" if "flash-lite" in model else "low"


def record_usage(usage: Any) -> None:
    """Add one interaction's token usage to USAGE."""
    USAGE["calls"] += 1
    for field, name in (
        ("input", "total_input_tokens"),
        ("cached", "total_cached_tokens"),
        ("output", "total_output_tokens"),
        ("thoughts", "total_thought_tokens"),
    ):
        USAGE[field] += int(getattr(usage, name, None) or 0)


def _usage_line(usage: dict[str, int]) -> str:
    return (
        f"{usage['calls']} call(s), {usage['input']} input tokens ({usage['cached']} cached), "
        f"{usage['output']} output, {usage['thoughts']} thinking"
    )


def print_usage() -> None:
    """Print the tokens of the whole run and, when anything was planned, the estimate."""
    if ESTIMATE["calls"]:
        print(
            f"estimate: {ESTIMATE['calls']} call(s), about {ESTIMATE['input']} input and "
            f"{ESTIMATE['output']} output tokens (estimate)"
        )
    if USAGE["calls"]:
        print(f"usage: {_usage_line(USAGE)}")


def _client() -> Any:
    """The google-genai client, created on first use so that imports and dry runs need no SDK."""
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        from google.genai import types

        timeout = FLEX_TIMEOUT if FLEX else STANDARD_TIMEOUT
        # Retries happen in gemini_call, which never repeats a timed-out call
        options = types.HttpOptions(
            timeout=timeout * 1000, retry_options=types.HttpRetryOptions(attempts=0)
        )
        _CLIENT = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=options)
    return _CLIENT


def gemini_call(model: str, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
    """Run one prompt as a stateless interaction and return its text."""
    from google.genai import errors

    request: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "store": False,
        "generation_config": {"thinking_level": thinking_level(model)},
    }
    if system:
        request["system_instruction"] = system
    if json_mode:
        request["response_format"] = {"type": "text", "mime_type": "application/json"}
    if FLEX:
        request["service_tier"] = "flex"
    for attempt in range(1, API_ATTEMPTS + 1):
        try:
            interaction = _client().interactions.create(**request)
        except errors.APIError as e:
            if e.code not in RETRY_STATUSES or attempt >= API_ATTEMPTS:
                raise RuntimeError(f"Gemini API error {e.code}: {str(e.message)[:300]}") from None
            time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
            continue
        record_usage(interaction.usage)
        return str(interaction.output_text or "").strip()
    raise RuntimeError("unreachable")


def estimate_tokens(prompt: str, reply_chars: float) -> tuple[int, int]:
    """Estimated input and output tokens of one call, from the prompt and the expected reply size."""
    tokens_in = math.ceil((len(SYSTEM_PROMPT) + len(prompt)) / CHARS_PER_TOKEN)
    tokens_out = math.ceil(reply_chars / CHARS_PER_TOKEN) + THINKING_TOKENS_PER_CALL
    return tokens_in, tokens_out


def plan_call(prompt: str, reply_chars: float, label: str = "") -> None:
    """Add one planned call to ESTIMATE and print its estimate."""
    tokens_in, tokens_out = estimate_tokens(prompt, reply_chars)
    ESTIMATE["calls"] += 1
    ESTIMATE["input"] += tokens_in
    ESTIMATE["output"] += tokens_out
    print(f"  {label}estimate: about {tokens_in} input and {tokens_out} output tokens (estimate)")


def call_model(model: str, prompt: str, reply_chars: float, json_mode: bool = False) -> str:
    """Call the model with the system prompt, refusing a call that would pass --max-tokens."""
    if MAX_TOKENS is not None:
        used = USAGE["input"] + USAGE["output"] + USAGE["thoughts"]
        planned = sum(estimate_tokens(prompt, reply_chars))
        if used + planned > MAX_TOKENS:
            raise RuntimeError(
                f"--max-tokens {MAX_TOKENS}: {used} tokens used and this call is estimated at "
                f"{planned}; stopping before the call"
            )
    return gemini_call(model, prompt, system=SYSTEM_PROMPT, json_mode=json_mode)


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
            p for p in flat_en if p.rsplit(".", 1)[0] == group and p not in batch and p in flat_bg
        ]
        for p in siblings[:per_group]:
            context[p] = {"en": flat_en[p], "bg": flat_bg[p]}
    return context


def flat_prompt(
    batch: dict[str, str],
    prev_bg: dict[str, str],
    old_en: dict[str, str],
    context: dict[str, dict[str, str]],
) -> str:
    """The prompt for one batch of UI strings.

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
    return UI_PROMPT + "\n" + json.dumps(request, ensure_ascii=False, indent=1)


def _flat_reply_chars(batch: dict[str, str]) -> float:
    return sum(len(v) * BG_LENGTH_RATIO + len(p) + JSON_CHARS_PER_ENTRY for p, v in batch.items())


def translate_flat_batch(
    model: str,
    batch: dict[str, str],
    prev_bg: dict[str, str],
    old_en: dict[str, str],
    context: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """Translate one flat batch {dot.path: value}; returns None on failure."""
    prompt = flat_prompt(batch, prev_bg, old_en, context)
    text = call_model(model, prompt, _flat_reply_chars(batch), json_mode=True)
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
    for i, batch in enumerate(batches, 1):
        context = group_context(batch, flat_en, flat_bg)
        prompt = flat_prompt(batch, flat_bg, old_en or {}, context)
        plan_call(prompt, _flat_reply_chars(batch), f"batch {i}/{len(batches)}: ")
    if dry_run:
        for p in paths[:50]:
            print(f"    {p}")
        if len(paths) > 50:
            print(f"    ... and {len(paths) - 50} more")
        return

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

    LOCALES_BG.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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

MD_UNITS_PROMPT = """Translate the units of a Markdown document in the JSON object below from English to Bulgarian, following every rule in your instructions. The document already has a reviewed Bulgarian translation; only the paragraphs, list items, table rows, headings or sections whose English changed are sent, and the rest of the Bulgarian is kept as it is.

Each unit has "en", the English to translate. A unit that replaces existing text also has "old_en", its previous English, and "bg", the reviewed Bulgarian of "old_en": reuse that Bulgarian wording verbatim where the English did not change and the wording matches the TERMINOLOGY, and translate only what changed. "section" (the heading of the section the unit belongs to) and "bg_context" (the neighbouring reviewed Bulgarian text) are context only: match their style and terms, and do not translate or return them.

Output rules:
- Return only a JSON object {{"id": "Bulgarian Markdown"}} with exactly the same ids.
- Each value must have exactly the blocks of its "en", in the same order: the same paragraphs, list items, table rows, headings (same level) and code blocks, with blank lines where the English has them. Never merge, split, add or drop a paragraph, list item or table row.
- Preserve all Markdown exactly: list markers and indentation, tables (same number of columns), links, images, code blocks, bold and italics.
- Translate headings, table text, link text and image alt text; never change link targets.

ROLE CONTEXT:
{role}

UI LABELS: the application's real Bulgarian interface labels. When a unit refers to one of these interface elements, use exactly this Bulgarian label (inside „…“ or bold, as in the source); inflect it (for example add the definite article) only where Bulgarian grammar requires it:
{ui_labels}

JSON:
{units}
"""

# ── Markdown blocks ──

LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
ITEM = re.compile(r"^[ \t]*(?:[-*+]|(\d{1,9})[.)])(?:[ \t]|$)")
ROW = re.compile(r"^[ \t]*\|")
TABLE_SEP = re.compile(r"^[ \t]*\|?(?:[ \t]*:?-+:?[ \t]*\|?)+[ \t]*$")
HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
PIPE = re.compile(r"(?<!\\)\|")
LINK_TARGET = re.compile(
    r"\]\(\s*<?([^)\s>]*)|^[ \t]*\[[^\]]+\]:[ \t]*<?([^\s>]+)|<(https?://[^>\s]+)>", re.M
)


class Block(NamedTuple):
    """One Markdown block: its text, the line end after it and the blank lines that follow."""

    text: str
    eol: str
    sep: str
    kind: str

    @property
    def full(self) -> str:
        return self.text + self.eol + self.sep


def _line_kind(line: str) -> str:
    """The kind of block that starts with this line."""
    if m := ATX.match(line):
        return f"h{len(m.group(1))}"
    if _fence_close(line):
        return "fence"
    if ROW.match(line):
        return "row-sep" if TABLE_SEP.match(line) else "row"
    if HR.match(line):
        return "hr"
    if m := ITEM.match(line):
        return "ol" if m.group(1) else "ul"
    stripped = line.lstrip(" \t")
    if stripped.startswith(">"):
        return "quote"
    if stripped.startswith("<"):
        return "html"
    return "para"


def _fence_close(line: str) -> re.Pattern[str] | None:
    """The pattern of the line that closes the fence this line opens, or None."""
    m = FENCE.match(line)
    # A backtick fence's info string has no backticks, otherwise it is inline code
    if not m or (m.group(1)[0] == "`" and "`" in m.group(2)):
        return None
    char, size = re.escape(m.group(1)[0]), len(m.group(1))
    return re.compile(rf"^[ \t]*{char}{{{size},}}[ \t]*$")


def _verbatim_close(line: str) -> re.Pattern[str] | None:
    """The end of a fence or an HTML comment that this line opens, inside which nothing splits."""
    close = _fence_close(line)
    if close:
        return close
    stripped = line.lstrip(" \t")
    if stripped.startswith("<!--") and "-->" not in stripped[4:]:
        return re.compile(r".*-->")
    return None


def _starts_block(line: str, current: str) -> bool:
    """Whether a line right after a non-blank line starts a new block."""
    if ATX.match(line) or ROW.match(line):
        return True
    if HR.match(line):
        return False
    m = ITEM.match(line)
    # An ordered item other than 1 cannot interrupt a paragraph, so a wrapped "10. ..." stays
    return bool(m) and not (m.group(1) and m.group(1) != "1" and current == "para")


def _front_matter_end(lines: list[str]) -> int:
    """The number of lines of YAML front matter at the start, or 0."""
    if len(lines) < 3 or lines[0].rstrip("\r\n") != "---" or not lines[1].strip():
        return 0
    for k in range(1, len(lines)):
        if lines[k].rstrip("\r\n") in ("---", "..."):
            return k + 1
    return 0


def split_blocks(text: str) -> list[Block]:
    """Split Markdown into blocks; joining every block's full text gives back the input exactly.

    Blocks end at blank lines outside fences and HTML comments; headings, list items and
    table rows also start a block, and a heading or table row is a block of its own line.
    """
    lines = LINE.findall(text)
    raw: list[tuple[list[str], list[str], str]] = []
    start = _front_matter_end(lines)
    if start:
        raw.append((lines[:start], [], "front"))
    close: re.Pattern[str] | None = None
    end_block = bool(start)
    for line in lines[start:]:
        s = line.rstrip("\r\n")
        if close is not None:
            raw[-1][0].append(line)
            if close.match(s):
                close = None
            continue
        if not s.strip():
            if not raw:
                raw.append(([], [], "blank"))
            raw[-1][1].append(line)
            continue
        if not raw or raw[-1][1] or end_block or _starts_block(s, raw[-1][2]):
            raw.append(([], [], _line_kind(s)))
        raw[-1][0].append(line)
        end_block = bool(ATX.match(s) or ROW.match(s))
        close = _verbatim_close(s)
    blocks = []
    for content_lines, blank_lines, kind in raw:
        content = "".join(content_lines)
        eol = "\r\n" if content.endswith("\r\n") else "\n" if content.endswith("\n") else ""
        if kind == "para" and len(content_lines) > 1 and (m := SETEXT.match(content_lines[1])):
            kind = "setext1" if m.group(1)[0] == "=" else "setext2"
        blocks.append(Block(content[: len(content) - len(eol)], eol, "".join(blank_lines), kind))
    return blocks


def _is_heading(block: Block) -> bool:
    return re.fullmatch(r"h[1-6]", block.kind) is not None


def split_sections(text: str) -> list[str]:
    """Split Markdown before each heading outside code blocks; the parts join back losslessly."""
    sections: list[str] = []
    for block in split_blocks(text):
        if not sections or _is_heading(block):
            sections.append("")
        sections[-1] += block.full
    return sections


def _heading_level(section: str) -> int:
    blocks = split_blocks(section)
    return int(blocks[0].kind[1]) if blocks and _is_heading(blocks[0]) else 0


def _fences(block: Block) -> list[tuple[str, str]]:
    return [
        (m.group(1), m.group(2).strip())
        for line in block.text.splitlines()
        if (m := FENCE.match(line))
    ]


def _columns(block: Block) -> list[int]:
    return [len(PIPE.findall(line)) for line in block.text.splitlines() if ROW.match(line)]


def _links(block: Block) -> tuple[list[str], int]:
    """Link targets other than in-page anchors, and the number of anchors (relinked later)."""
    targets = [
        next(g for g in m.groups() if g is not None) for m in LINK_TARGET.finditer(block.text)
    ]
    return sorted(t for t in targets if not t.startswith("#")), sum(
        t.startswith("#") for t in targets
    )


# A Bulgarian block must agree with its English block on each of these
BLOCK_CHECKS: dict[str, Callable[[Block], object]] = {
    "kind": lambda block: block.kind,
    "code fences": _fences,
    "table columns": _columns,
    "link targets": _links,
}


def block_mismatch(en: list[Block], bg: list[Block]) -> str | None:
    """Why two block lists do not line up (count, kinds, fences, columns, links), or None."""
    en = [b for b in en if b.kind != "blank"]
    bg = [b for b in bg if b.kind != "blank"]
    if len(en) != len(bg):
        return f"{len(bg)} block(s) instead of {len(en)}"
    for n, (a, b) in enumerate(zip(en, bg, strict=True), 1):
        for name, check in BLOCK_CHECKS.items():
            if check(a) != check(b):
                return f"block {n}: the {name} differ from the English"
    return None


def _norm(block: Block) -> str:
    """Comparison key: reflowed lines and trailing spaces are no change, except in code."""
    lines = block.text.splitlines()
    if any(FENCE.match(line) for line in lines) or block.kind == "front":
        return block.kind + "\0" + "\n".join(line.rstrip() for line in lines)
    indent = block.text[: len(block.text) - len(block.text.lstrip(" \t"))]
    return block.kind + "\0" + indent + " ".join(block.text.split())


def _with_eol(text: str, like: Block) -> str:
    """Text with the line ends of *like* (CRLF or LF)."""
    sample = like.text + like.eol
    if "\r\n" in sample:
        return text.replace("\r\n", "\n").replace("\n", "\r\n")
    if "\n" in sample:
        return text.replace("\r\n", "\n")
    return text


def _keep(bg_text: str, new: Block) -> dict[str, Any]:
    """A kept Bulgarian block with the spacing of the new English."""
    return {"keep": _with_eol(bg_text, new) + new.eol + new.sep, "en": new.full}


def _join(blocks: list[Block]) -> str:
    return "".join(block.full for block in blocks).strip("\r\n").rstrip()


def _unit(
    kind: str, new: list[Block], old: list[Block] | None = None, bg: list[Block] | None = None
) -> dict[str, Any]:
    """A unit to translate: the new English blocks and, when it replaces text, the old ones."""
    unit: dict[str, Any] = {"_kind": kind, "_blocks": new, "en": _join(new)}
    if old is not None and bg is not None:
        unit["old_en"], unit["bg"] = _join(old), _join(bg)
    return unit


def _inserted(new: list[Block], moved: dict[str, str]) -> list[dict[str, Any]]:
    """New blocks: a known block (moved or duplicated) keeps its Bulgarian, the rest is sent."""
    items: list[dict[str, Any]] = []
    run: list[Block] = []
    for block in new:
        bg = moved.get(_norm(block))
        if block.kind == "blank" or bg is not None:
            if run:
                items.append(_unit("insert", run))
                run = []
            items.append(_keep(block.text if bg is None else bg, block))
        else:
            run.append(block)
    if run:
        items.append(_unit("insert", run))
    return items


def plan_blocks(old: str, new: str, bg: str, moved: dict[str, str]) -> list[dict[str, Any]] | None:
    """Kept Bulgarian blocks and units for one changed stretch; None when old EN and BG differ in shape."""
    old_b, new_b, bg_b = split_blocks(old), split_blocks(new), split_blocks(bg)
    if block_mismatch(old_b, bg_b) or [b.kind for b in old_b] != [b.kind for b in bg_b]:
        return None
    items: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(
        None, [_norm(b) for b in old_b], [_norm(b) for b in new_b], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            items.extend(_keep(bg_b[i1 + k].text, new_b[j1 + k]) for k in range(j2 - j1))
        elif op == "replace":
            items.append(_unit("block", new_b[j1:j2], old_b[i1:i2], bg_b[i1:i2]))
        elif op == "insert":
            items.extend(_inserted(new_b[j1:j2], moved))
    return items


def _moved_blocks(old_parts: list[str], bg_parts: list[str]) -> dict[str, str]:
    """Bulgarian of every old English block that has exactly one translation, by comparison key."""
    found: dict[str, set[str]] = {}
    for old, bg in zip(old_parts, bg_parts, strict=True):
        old_b, bg_b = split_blocks(old), split_blocks(bg)
        if block_mismatch(old_b, bg_b) is None:
            for a, b in zip(
                [x for x in old_b if x.kind != "blank"],
                [x for x in bg_b if x.kind != "blank"],
                strict=True,
            ):
                found.setdefault(_norm(a), set()).add(b.text)
    return {key: next(iter(texts)) for key, texts in found.items() if len(texts) == 1}


def _group(old: str, new: str, bg: str, moved: dict[str, str]) -> dict[str, Any]:
    """One changed stretch: block-level items when old EN and BG line up, else the whole unit."""
    blocks = split_blocks(new)
    if old:
        whole = _unit("section", blocks, split_blocks(old), split_blocks(bg))
    else:
        whole = _unit("section", blocks)
    items = plan_blocks(old, new, bg, moved)
    return {"items": items if items is not None else [whole], "whole": whole}


def plan_document(old_en: str, new_en: str, bg: str) -> list[dict[str, Any]] | None:
    """Groups of kept Bulgarian and units, one group per changed stretch of sections.

    Each group has "items" (block-level when its old English and Bulgarian line up)
    and "whole" (the stretch as one unit, the fallback). None when the sections of
    the old English and the Bulgarian do not line up.
    """
    old_parts, new_parts = split_sections(old_en), split_sections(new_en)
    bg_parts = split_sections(bg)
    if len(old_parts) != len(bg_parts) or any(
        _heading_level(o) != _heading_level(b) for o, b in zip(old_parts, bg_parts, strict=True)
    ):
        return None
    moved = _moved_blocks(old_parts, bg_parts)
    groups: list[dict[str, Any]] = []
    # Trailing blank lines do not count as a change; kept sections take the new spacing
    matcher = difflib.SequenceMatcher(
        None, [p.rstrip() for p in old_parts], [p.rstrip() for p in new_parts], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        new = "".join(new_parts[j1:j2])
        if op == "equal":
            for k in range(j2 - j1):
                part = new_parts[j1 + k]
                keep = bg_parts[i1 + k].rstrip() + part[len(part.rstrip()) :]
                groups.append({"items": [{"keep": keep, "en": part}], "whole": None})
        elif op == "replace" and i2 - i1 == j2 - j1:
            # Section by section, so a section that does not line up falls back alone
            groups.extend(
                _group(old_parts[k], new_parts[j1 + k - i1], bg_parts[k], moved)
                for k in range(i1, i2)
            )
        elif op in ("replace", "insert"):
            old = "".join(old_parts[i1:i2])
            groups.append(_group(old, new, "".join(bg_parts[i1:i2]), moved))
    _add_context([item for group in groups for item in group["items"]])
    return groups


def _edge_block(text: str, index: int) -> str:
    """The first (0) or last (-1) non-blank block of a kept text."""
    return [b.text for b in split_blocks(text) if b.kind != "blank"][index]


def _add_context(items: list[dict[str, Any]]) -> None:
    """Give units their section heading, and new blocks a neighbouring Bulgarian block."""
    heading = ""
    for n, item in enumerate(items):
        blocks = split_blocks(item["en"]) if "keep" in item else item["_blocks"]
        if "keep" not in item:
            first = next((b for b in blocks if b.kind != "blank"), None)
            if heading and first is not None and not _is_heading(first):
                item["section"] = heading
            if item["_kind"] == "insert":
                before = [i["keep"] for i in items[:n] if "keep" in i and i["keep"].strip()]
                after = [i["keep"] for i in items[n + 1 :] if "keep" in i and i["keep"].strip()]
                if before:
                    item["bg_context"] = _edge_block(before[-1], -1)[-NEIGHBOUR_CONTEXT_CHARS:]
                elif after:
                    item["bg_context"] = _edge_block(after[0], 0)[:NEIGHBOUR_CONTEXT_CHARS]
        for block in blocks:
            if _is_heading(block):
                heading = block.text.strip()


def _reindent(text: str, like: str) -> str:
    """Text with the leading indentation of *like* on its first line."""
    return like[: len(like) - len(like.lstrip(" \t"))] + text.lstrip(" \t")


def fit_reply(en: list[Block], reply: str) -> tuple[str | None, str]:
    """The reply laid out with the English spacing, or None and why it does not match the English."""
    reply = re.sub(r"\A(?:[ \t]*\r?\n)+", "", reply.replace("\r\n", "\n"))
    got = split_blocks(reply)
    why = block_mismatch(en, got)
    if why:
        return None, why
    replies = iter(b for b in got if b.kind != "blank")
    out = []
    for block in en:
        if block.kind == "blank":
            out.append(block.full)
            continue
        text = _reindent(next(replies).text.rstrip(), block.text)
        out.append(_with_eol(text, block) + block.eol + block.sep)
    return "".join(out), ""


def _role(filename: str | None) -> str:
    return ROLE_CONTEXT.get(filename or "", "") or (
        "This document is platform documentation for LavBench, an ML "
        "competition platform. Write clearly and professionally."
    )


def _payload(units: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """The units as sent: their public fields under ids 1..n."""
    return {
        str(n): {k: v for k, v in unit.items() if not k.startswith("_")}
        for n, unit in enumerate(units, 1)
    }


def units_prompt(units: list[dict[str, Any]], filename: str | None) -> str:
    return MD_UNITS_PROMPT.format(
        role=_role(filename),
        ui_labels=ui_labels("".join(unit["en"] for unit in units)),
        units=json.dumps(_payload(units), ensure_ascii=False, indent=1),
    )


def _units_reply_chars(units: list[dict[str, Any]]) -> float:
    return sum(len(unit["en"]) * BG_LENGTH_RATIO + JSON_CHARS_PER_ENTRY for unit in units)


def translate_units(model: str, units: list[dict[str, Any]], filename: str | None) -> None:
    """Translate units in one call; each unit whose reply fits its English gets "_out"."""
    prompt = units_prompt(units, filename)
    text = call_model(model, prompt, _units_reply_chars(units), json_mode=True)
    try:
        reply = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        print("  !! response was not valid JSON")
        return
    if not isinstance(reply, dict) or set(reply) != set(_payload(units)):
        print("  !! the reply does not have exactly one entry per unit")
        return
    for n, unit in enumerate(units, 1):
        value = reply[str(n)]
        out, why = (
            fit_reply(unit["_blocks"], value) if isinstance(value, str) else (None, "not text")
        )
        if out is None:
            print(f"  !! unit {n} ({unit['_kind']}): {why}")
        else:
            unit["_out"] = out


def _units_of(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for group in groups for item in group["items"] if "keep" not in item]


def translate_groups(model: str, groups: list[dict[str, Any]], filename: str | None) -> bool:
    """Translate every unit; a group whose reply does not fit is retried once as whole sections."""
    units = _units_of(groups)
    if units:
        translate_units(model, units, filename)
    failed = [g for g in groups if any("_out" not in i for i in g["items"] if "keep" not in i)]
    if not failed:
        return True
    print(f"  retrying {len(failed)} changed stretch(es) as whole sections")
    retry = [group["whole"] for group in failed]
    for group, unit in zip(failed, retry, strict=True):
        group["items"] = [unit]
        unit.pop("_out", None)
    translate_units(model, retry, filename)
    return all("_out" in unit for unit in retry)


def render(groups: list[dict[str, Any]]) -> str:
    return "".join(
        item["keep"] if "keep" in item else item["_out"]
        for group in groups
        for item in group["items"]
    )


def _unit_title(unit: dict[str, Any]) -> str:
    first = unit["en"].strip().splitlines()[0] if unit["en"].strip() else "(blank)"
    return str(unit.get("section") or first)[:70]


def translate_document(
    model: str, src: Path, out: Path, filename: str, dry_run: bool, force: bool
) -> None:
    """Translate the changed blocks of one Markdown file, or the whole file when needed."""
    content = src.read_text(encoding="utf-8")
    previous_bg = out.read_text(encoding="utf-8") if out.exists() else None
    old_en = None if force else en_at_last_translation(src, out)
    label = f"{_repo_path(src)} -> {_repo_path(out)}"
    if old_en is not None and old_en == content:
        print(f"  {_repo_path(src)}: unchanged since last translation — skip")
        return
    # Plan against the committed BG, which matches the old EN even after an uncommitted earlier run
    base_bg = at_last_translation(out, out) or previous_bg
    groups = plan_document(old_en, content, base_bg) if old_en and base_bg else None
    before = dict(USAGE)
    if groups is None:
        reason = "--force" if force else "no aligned previous translation"
        print(f"  {label}: whole file ({reason}, {len(content)} characters)")
        plan_call(whole_prompt(content, filename, previous_bg), len(content) * BG_LENGTH_RATIO)
        if dry_run:
            return
        result = (
            translate_markdown(model, content, filename=filename, previous_bg=previous_bg) + "\n"
        )
    else:
        units = _units_of(groups)
        chars = sum(len(v) for unit in units for v in _payload([unit])["1"].values())
        print(f"  {label}: {len(units)} unit(s), {chars} characters")
        for unit in units:
            sent = sum(len(v) for v in _payload([unit])["1"].values())
            print(f"    {unit['_kind']:<7} {_unit_title(unit)}  ({sent} characters)")
        if units:
            plan_call(units_prompt(units, filename), _units_reply_chars(units))
        if dry_run:
            return
        if not translate_groups(model, groups, filename):
            print(f"  !! {_repo_path(out)} left unchanged; fix the cause or use --force")
            return
        result = _relink_anchors(content, render(groups))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding="utf-8")
    if USAGE["calls"] > before["calls"]:
        print(f"  usage: {_usage_line({k: USAGE[k] - before[k] for k in USAGE})}")


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
    en_headings = list(re.finditer(r"^#{1,6}\s+(.+)$", src, re.M))
    bg_headings = list(re.finditer(r"^#{1,6}\s+(.+)$", translated, re.M))
    if len(en_headings) != len(bg_headings):
        return translated
    mapping: dict[str, str] = {}
    for en_m, bg_m in zip(en_headings, bg_headings, strict=True):
        en_slug = _gh_slug(en_m.group(1))
        bg_slug = _gh_slug(bg_m.group(1))
        if en_slug and bg_slug and en_slug != bg_slug:
            mapping[en_slug] = bg_slug
    if not mapping:
        return translated
    for en_slug, bg_slug in mapping.items():
        translated = re.sub(rf"\(\s*#\s*{re.escape(en_slug)}\s*\)", f"(#{bg_slug})", translated)
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


def whole_prompt(text: str, filename: str | None, previous_bg: str | None) -> str:
    previous = previous_bg or "(no previous translation; translate from scratch)"
    return MD_PROMPT.format(
        role=_role(filename),
        ui_labels=ui_labels(text),
        previous=previous[:90000],
        text=text[:90000],
    )


def translate_markdown(
    model: str,
    text: str,
    filename: str | None = None,
    previous_bg: str | None = None,
) -> str:
    """Translate a whole document."""
    prompt = whole_prompt(text, filename, previous_bg)
    translated = _strip_fences(call_model(model, prompt, len(text) * BG_LENGTH_RATIO))
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
            if out.is_symlink() and os.path.normpath(
                os.path.join(out.parent, os.readlink(out))
            ) == os.path.normpath(bg_target):
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
        if not dry_run:
            time.sleep(SLEEP_BETWEEN_CALLS)


# Variants that must never appear in Bulgarian output: pattern -> mandated term
BANNED_TERMS = {
    r"уъркър": "работен възел",
    r"пясъчн\w* сред": "изолирана среда",
    r"пайплайн": "конвейер",
    # Not inside a longer word such as "диалогови" (dialog)
    r"(?<!\w)логов[еи]": "журнали",
    r"толерансн\w* период": "гратисен период",
    r"житейск\w* цикъл|житейск\w* цикли": "жизнен цикъл",
    r"ЛавБенч": "LavBench",
    r"шифрова\w*": "криптиран",
    r"[Дд]иректн\w* качван\w*": "аварийно качване",
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
                    print(f'  ERROR {rel}:{no}: "{m.group(0)}" -> use "{mandated}"')
            if path.suffix == ".md":
                prose = re.sub(r"`[^`]*`|\]\([^)]*\)|https?://\S+", " ", line)
                if ENGLISH_RUN.search(prose):
                    warnings += 1
                    print(
                        f"  warning {rel}:{no}: possible untranslated English: {line.strip()[:120]}"
                    )
    print(f"consistency: {errors} error(s), {warnings} warning(s)")
    return errors


def run_targets(args: argparse.Namespace, dry_run: bool) -> None:
    """Translate (or, with dry_run, plan) every selected target."""
    if not args.only or args.only == "locales":
        translate_locales(args.model, dry_run, force=args.force)
    if not args.only or args.only == "guides":
        print("== guides ==")
        translate_dir(args.model, GUIDES_EN, GUIDES_BG, dry_run, force=args.force)
    if (not args.only or args.only == "readme") and README_EN.exists():
        print("== docs/README ==")
        translate_document(args.model, README_EN, README_BG, "README.md", dry_run, args.force)
    if args.only == "docs" or (args.docs and not args.only):
        print("== docs ==")
        translate_dir(args.model, DOCS_EN, DOCS_BG, dry_run, force=args.force)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate LavBench content EN -> BG with Gemini")
    parser.add_argument("--docs", action="store_true", help="also translate docs/source/*.md")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be sent and estimate the tokens; no API calls, no writes",
    )
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
        help="use the Flex service tier; each call may take minutes",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="stop before calling the API when the estimated input plus output tokens exceed this",
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

    global FLEX, MAX_TOKENS
    FLEX = args.flex
    MAX_TOKENS = args.max_tokens
    if MAX_TOKENS is not None and not args.dry_run:
        # Plan the whole run first, so a run over the limit makes no call at all
        with contextlib.redirect_stdout(io.StringIO()):
            run_targets(args, dry_run=True)
        planned = ESTIMATE["input"] + ESTIMATE["output"]
        if planned > MAX_TOKENS:
            sys.exit(
                f"estimated {planned} tokens ({ESTIMATE['input']} input, {ESTIMATE['output']} "
                f"output) exceed --max-tokens {MAX_TOKENS}; nothing was sent"
            )
        for key in ESTIMATE:
            ESTIMATE[key] = 0
    if not args.dry_run:
        load_api_key(Path(args.key_file))
    print(f"model: {args.model}  dry-run: {args.dry_run}  force: {args.force}  flex: {args.flex}")

    try:
        run_targets(args, args.dry_run)
    finally:
        print_usage()
    if args.dry_run and MAX_TOKENS is not None:
        planned = ESTIMATE["input"] + ESTIMATE["output"]
        verdict = "within" if planned <= MAX_TOKENS else "above"
        print(f"the estimate is {verdict} --max-tokens {MAX_TOKENS}")

    if not args.dry_run:
        print("== consistency ==")
        if check_consistency():
            sys.exit(1)


if __name__ == "__main__":
    main()
