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
(the value after '=', e.g. `GEMINI-API-KEY=AQ...`), which is then
exported as GEMINI_API_KEY for the API call.

Only changed sources are translated: git compares the working-tree EN
file against the EN version at the last commit that touched the BG
output, so untouched files are skipped (no state file needed).

Usage:
  python3 scripts/translate_gemini.py                # frontend + guides + docs README
  python3 scripts/translate_gemini.py --docs         # + docs/source
  python3 scripts/translate_gemini.py --only readme  # just the docs README
  python3 scripts/translate_gemini.py --dry-run      # preview only
  python3 scripts/translate_gemini.py --model gemini-3.6-flash
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
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
MAX_BATCH_CHARS = 3000
SLEEP_BETWEEN_CALLS = 0.5


def _repo_path(path: Path) -> str:
    """Repo-root-relative path with forward slashes (for git arguments)."""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def source_changed_since_last_translation(src: Path, out: Path) -> bool:
    """True when *src* differs from the EN version that produced *out*.

    Git-based change detection: compares the working-tree *src* against the
    version of *src* at the last commit that touched *out* (the commit where
    the current translation was recorded). When *out* is missing or not yet
    committed, or git is unavailable, the file is translated.
    """
    if not out.exists():
        return True
    try:
        last = subprocess.run(
            ["git", "rev-list", "-1", "HEAD", "--", _repo_path(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return True
    if not last:
        return True
    try:
        en_at_last = subprocess.run(
            ["git", "show", f"{last}:{_repo_path(src)}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return True
    return en_at_last != src.read_text(encoding="utf-8")

APP_CONTEXT = """
CONTEXT — LavBench (ЛавБенч) is a machine-learning competition platform.
Core concepts (keep these terms consistent across ALL translations):
- challenge = състезание; stage = етап; task = задача
- submission = решение/изпълнение (a competitor's executed notebook)
- baseline notebook = базов бележник (reference solution)
- selected cells = избрани клетки; execution logs = журнали на изпълнението
- leaderboard = класация; public/private score = публичен/частен резултат
- evaluation = оценяване; metric = метрика; parquet = parquet (keep as-is)
- Hugging Face, GPU, CPU, Docker, Jupyter — keep as-is
- jury = жури; competitor = състезател; admin = администратор
- sandbox = пясъчна среда (isolated execution environment)
- role: admin manages challenges/stages, jury evaluates and monitors,
  competitor participates by submitting notebooks.
Translate naturally and idiomatically into professional Bulgarian; do not
transliterate English words when a good Bulgarian term exists.
"""

SYSTEM_LOCALES = (
    "You are a professional translator for the LavBench ML competition platform "
    "UI (English -> Bulgarian)." + APP_CONTEXT
)

SYSTEM_GUIDES = (
    "You are a professional technical documentation translator for the LavBench "
    "ML competition platform (English -> Bulgarian)." + APP_CONTEXT
)

ROLE_CONTEXT = {
    "admin_guide": (
        "This document is the ADMINISTRATOR guide: it explains challenge/stage "
        "lifecycle management, sandbox customization and Docker image build error "
        "remediation, Hugging Face pre-fetching, AST security validation, dynamic "
        "metrics engine and leaderboard management. Write for a system "
        "administrator with technical expertise."
    ),
    "jury_guide": (
        "This document is the JURY guide: it explains the jury permission matrix, "
        "competitor onboarding with credential slips, live submission tracking, "
        "baseline verification, build error diagnostics and leaderboard "
        "inspection. Write for a jury member who evaluates competitors."
    ),
    "competitor_guide": (
        "This document is the COMPETITOR guide: it explains how to log in, "
        "navigate stages and tasks, use baseline notebooks, produce the "
        "submission.parquet output schema and submit Jupyter notebooks. Write "
        "for a data-science competitor participating in the competition."
    ),
    "README.md": (
        "This is the README of the docs/ folder of the LavBench repository: a "
        "developer & documentation guide with quick-access sitemap, frontend "
        "developer guidelines (API type pipeline, i18n parity), backend "
        "endpoint patterns, custom evaluator templates and Sphinx build "
        "instructions. Write for a developer contributing to the project."
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


def gemini_call(
    key: str, model: str, prompt: str, retries: int = 2, system: str | None = None
) -> str:
    """Run one prompt against the Gemini API and return the raw text."""
    url = API_URL.format(model=urllib.parse.quote(model)) + f"?key={urllib.parse.quote(key)}"
    payload: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.load(resp)
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as e:  # noqa: BLE001
            if attempt >= retries:
                raise
            time.sleep(2 * attempt)
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


def translate_flat_batch(
    key: str, batch: dict[str, str], dry_run: bool
) -> dict[str, str] | None:
    """Translate one flat batch {dot.path: value}; returns None on failure."""
    if dry_run:
        return {p: f"[BG] {v}" for p, v in batch.items()}
    src = json.dumps(batch, ensure_ascii=False, indent=1)
    prompt = (
        "Translate the following JSON object of UI/message strings from English "
        "to Bulgarian.\n"
        "Rules:\n"
        "- Return ONLY the translated JSON object, no markdown fences, no comments.\n"
        "- Keep the exact same keys (dot notation); do not add, remove or reorder keys.\n"
        "- Keep placeholders ({{name}}, {count}, %s, $1) and HTML/JSX untouched.\n"
        "- Keep proper nouns/technical terms as-is (Hugging Face, parquet, LavBench, GPU...).\n"
        "- Use natural, idiomatic, professional Bulgarian.\n\n"
        f"JSON:\n{src}"
    )
    text = gemini_call(
        os.environ["GEMINI_API_KEY"], key, prompt, system=SYSTEM_LOCALES
    )
    try:
        translated = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        print(f"  !! {key}: response was not valid JSON, retrying...")
        text = gemini_call(
            os.environ["GEMINI_API_KEY"],
            key,
            prompt + "\n\nIMPORTANT: reply with raw JSON only, no code fences.",
            system=SYSTEM_LOCALES,
        )
        try:
            translated = json.loads(_strip_fences(text))
        except json.JSONDecodeError:
            print(f"  !! {key}: still not JSON — keeping original values")
            return None
    if not isinstance(translated, dict) or set(translated) != set(batch):
        print(f"  !! {key}: key mismatch ({len(batch)} in, {len(translated)} out) — keeping originals")
        return None
    return {p: (v if isinstance(v, str) else str(v)) for p, v in translated.items()}


def translate_locales(model: str, dry_run: bool) -> None:
    print("== frontend/public/locales ==")
    if not source_changed_since_last_translation(LOCALES_EN, LOCALES_BG):
        print(f"  {LOCALES_EN.relative_to(ROOT)}: unchanged since last translation — skip")
        return
    en = json.loads(LOCALES_EN.read_text(encoding="utf-8"))
    bg = json.loads(LOCALES_BG.read_text(encoding="utf-8"))

    flat_en = flatten(en)
    flat_bg = flatten(bg)
    paths = list(flat_en)

    batches: list[dict[str, str]] = []
    current: dict[str, str] = {}
    size = 0
    for path in paths:
        val = flat_en[path]
        if size + len(val) > MAX_BATCH_CHARS and current:
            batches.append(current)
            current, size = {}, 0
        current[path] = val
        size += len(val)
    if current:
        batches.append(current)

    new_bg = dict(flat_bg)
    ok = 0
    for i, batch in enumerate(batches, 1):
        print(f"  batch {i}/{len(batches)} ({len(batch)} keys)")
        result = translate_flat_batch(model, batch, dry_run)
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

    if dry_run:
        print(f"  [dry-run] would update {ok}/{len(flat_en)} strings")
        return
    LOCALES_BG.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  wrote {LOCALES_BG} ({ok}/{len(flat_en)} strings updated)")


MD_PROMPT = (
    "Translate the following Markdown document from English to Bulgarian.\n"
    "Rules:\n"
    "- Return ONLY the translated document, no markdown fences around it.\n"
    "- Preserve ALL Markdown syntax, headings, lists, tables, links, images,\n"
    "  and the exact same section structure — nothing may be omitted or added.\n"
    "- Do NOT translate code blocks, inline code, URLs, file paths or YAML front matter.\n"
    "- Keep the same line structure where possible.\n"
    "- Use natural, idiomatic, professional Bulgarian.\n\n"
    "ROLE CONTEXT:\n{role}\n\n"
    "DOCUMENT:\n{text}"
)


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


def translate_markdown(
    model: str, text: str, dry_run: bool, filename: str | None = None
) -> str:
    if dry_run:
        return f"[DRY-RUN — would translate this file]\n\n{text}"
    role = ROLE_CONTEXT.get(filename or "", "")
    if not role:
        role = (
            "This document is platform documentation for LavBench, an ML "
            "competition platform. Write clearly and professionally."
        )
    prompt = MD_PROMPT.format(role=role, text=text[:90000])
    translated = _strip_fences(
        gemini_call(os.environ["GEMINI_API_KEY"], model, prompt, system=SYSTEM_GUIDES)
    )
    return _relink_anchors(text, translated)


def translate_dir(
    model: str, src_dir: Path, dst_dir: Path, dry_run: bool, names: list[str] | None = None
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
        if not source_changed_since_last_translation(f, out):
            print(f"  {f.relative_to(ROOT)}: unchanged since last translation — skip")
            continue
        print(f"  {f.relative_to(ROOT)} -> {out.relative_to(ROOT)}")
        content = f.read_text(encoding="utf-8")
        translated = translate_markdown(model, content, dry_run, filename=f.name)
        if not dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(translated + "\n", encoding="utf-8")
        time.sleep(SLEEP_BETWEEN_CALLS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate LavBench content EN -> BG with Gemini")
    parser.add_argument("--docs", action="store_true", help="also translate docs/source/*.md")
    parser.add_argument("--dry-run", action="store_true", help="preview only, don't write files")
    parser.add_argument(
        "--only", choices=["locales", "guides", "docs", "readme"], help="translate only this target"
    )
    parser.add_argument("--model", default="gemini-3.6-flash", help="Gemini model id")
    parser.add_argument("--key-file", default=str(KEY_FILE), help="path to the API key file")
    args = parser.parse_args()

    load_api_key(Path(args.key_file))
    print(f"model: {args.model}  dry-run: {args.dry_run}")

    if not args.only or args.only == "locales":
        translate_locales(args.model, args.dry_run)
    if not args.only or args.only == "guides":
        print("== guides ==")
        translate_dir(args.model, GUIDES_EN, GUIDES_BG, args.dry_run)
    if not args.only or args.only == "readme":
        print("== docs/README ==")
        out = README_BG
        if README_EN.exists():
            if not source_changed_since_last_translation(README_EN, out):
                print(f"  {README_EN.relative_to(ROOT)}: unchanged since last translation — skip")
            else:
                translated = translate_markdown(args.model, README_EN.read_text(encoding="utf-8"), args.dry_run, filename="README.md")
                if not args.dry_run:
                    out.write_text(translated + "\n", encoding="utf-8")
                print(f"  {README_EN.relative_to(ROOT)} -> {out.relative_to(ROOT)}")
            time.sleep(SLEEP_BETWEEN_CALLS)
    if args.only == "docs" or (args.docs and not args.only):
        print("== docs ==")
        translate_dir(args.model, DOCS_EN, DOCS_BG, args.dry_run)


if __name__ == "__main__":
    main()
