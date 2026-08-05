#!/usr/bin/env python3
"""
Lint script: enforce the comment/docstring conventions from AGENTS.md.

Checks (exit 1 on any error):
1. Every .py module starts with a module docstring (one-line summary)
2. Comments start with '# ' — no '#word' without a space
3. No decorative divider banners: # ===, # ---, # ═══, # ░░, # ██, # ****
4. No commented-out code: '# if ...', '# return ...', '# import ...', etc.
5. No bare '# noqa' — always '# noqa: CODE'
6. TODO comments must be actionable: '# TODO: <imperative> ...'

Warnings (printed, exit 0):
W1. Comment text should start with a capital letter (or code token / URL / digit)
W2. Single-line comments should not end with a period

Usage:
    python scripts/check_comments.py [files...]
    # If no files given, checks all *.py under the backend (routes, services,
    # schemas, tasks, utils, config, models, tests, scripts + root modules)
"""

import ast
import re
import sys
import tokenize
from pathlib import Path

CODE_KEYWORDS = re.compile(
    r"^(?:def|class|from|import|return|raise|assert|print)\b|"
    r"^(?:if|for|while)\b.*:$|"
    r"^self\.[a-z_]+"
)
DIVIDER_BANNER = re.compile(r"^(?:[═█░·•−_*~]|={2,}|-{2,}|\*{2,}){3,}$")  # noqa: RUF001
ALLOWED_LOWERCASE_START = re.compile(
    r"^(?:noqa|type:\s*ignore|fmt:|todo|fixme|xxx|pyright|mypy|ruff|"
    r"e[0-9]{3}|w[0-9]{3}|s[0-9]{3}|f[0-9]{3}|i[0-9]{3}|n[0-9]{3}|"
    r"up[0-9]{3}|b[0-9]{3}|t[0-9]{3}|c4[0-9]{3}|perf[0-9]{3}|a[0-9]{3}|log[0-9]{3}|"
    r"http|https|url|uuid|jwt|csrf|sse|api|json|ipynb|parquet|db|app|os|"
    r"pdf|sql|utf-?8|sha256|ed25519|fernet|gevent|gunicorn|celery|redis|"
    r"postgres|docker|nginx|flask|pytest|ruff|mypy|uvicorn|gzip|tar|tmpfs|"
    r"labels\.parquet)"
)
TRAILING_PERIOD = re.compile(r"\.$")
PATH_LIKE = re.compile(r"^[/~.]?[/\w.-]+[/.]")

ROOT = Path(__file__).resolve().parent.parent

ERRORS: list[tuple[Path, int, str]] = []
WARNINGS: list[tuple[Path, int, str]] = []


def check_module_docstring(path: Path) -> None:
    """Verify the first statement of a module is a string-literal docstring."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        ERRORS.append((path, 1, f"syntax error: {exc}"))
        return
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        ERRORS.append(
            (path, 1, "missing module docstring (first statement must be a summary string)")
        )


def check_comment_tokens(path: Path) -> None:
    """Scan real comment tokens (never strings) for style violations."""
    try:
        with tokenize.open(path) as fh:
            tokens = list(tokenize.generate_tokens(fh.readline))
    except (tokenize.TokenError, IndentationError, OSError):
        return
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        raw = tok.string
        lineno = tok.start[0]
        stripped = raw.lstrip("#").lstrip()

        # ── Check 2: comment requires a space after the hash ──
        if raw.startswith("#") and not raw.startswith("#!") and not raw.startswith("# "):
            ERRORS.append((path, lineno, "comment must have a space after '#'"))

        # ── Check 5: bare noqa directive ──
        if re.fullmatch(r"\s*noqa\s*", stripped):
            ERRORS.append((path, lineno, "bare '# noqa' — use '# noqa: CODE'"))

        # ── Check 6: TODO format ──
        if re.match(r"^(TODO|FIXME|XXX)", stripped, re.IGNORECASE) and (
            not re.match(r"^TODO\s*:", stripped) or re.fullmatch(r"TODO\s*:\s*", stripped)
        ):
            ERRORS.append((path, lineno, "TODO must be '# TODO: <imperative> ...' with content"))

        # ── Check 3: forbidden divider banners ──
        if DIVIDER_BANNER.match(stripped) or re.match(
            r"^(?:══+[=\s]*|██+[=\s]*|░░+[=\s]*|===+|-{3,})", stripped
        ):
            ERRORS.append((path, lineno, "forbidden divider — use '# ── Title ──'"))

        # ── Check 4: commented-out code ──
        if CODE_KEYWORDS.match(stripped):
            ERRORS.append((path, lineno, f"commented-out code: '{stripped[:60]}'"))

        # ── W1: capitalized start ──
        first_char = stripped[0] if stripped else ""
        if (
            first_char
            and first_char.islower()
            and not ALLOWED_LOWERCASE_START.match(stripped)
            and not PATH_LIKE.match(stripped)
        ):
            WARNINGS.append(
                (path, lineno, f"comment should start with a capital letter: '{stripped[:60]}'")
            )

        # ── W2: no trailing period on single-line comments ──
        if stripped and TRAILING_PERIOD.search(stripped) and stripped.count(".") == 1:
            WARNINGS.append(
                (path, lineno, f"single-line comment should not end with '.': '{stripped[:60]}'")
            )


def main() -> int:
    args = sys.argv[1:]
    if args:
        files = [Path(f).resolve() for f in args]
    else:
        files = []
        for rel in ["app.py", "evaluation_engine.py", "spec.py", "conftest.py"]:
            p = ROOT / rel
            if p.exists():
                files.append(p)
        for sub in [
            "routes",
            "services",
            "schemas",
            "tasks",
            "utils",
            "config",
            "models",
            "tests",
            "scripts",
            "tasks/task_modules",
        ]:
            files.extend(sorted((ROOT / sub).glob("*.py")))

    for f in sorted(set(files)):
        if not f.exists():
            continue
        check_module_docstring(f)
        check_comment_tokens(f)

    for path, lineno, msg in ERRORS:
        print(f"{path}:{lineno}: ERROR {msg}")
    for path, lineno, msg in WARNINGS:
        print(f"{path}:{lineno}: WARNING {msg}")
    if ERRORS:
        print(f"\n{len(ERRORS)} error(s) — fix before committing")
        return 1
    if WARNINGS:
        print(f"\n{len(WARNINGS)} warning(s)")
    else:
        print("OK: all comments follow the AGENTS.md conventions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
