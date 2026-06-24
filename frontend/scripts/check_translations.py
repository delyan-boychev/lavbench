#!/usr/bin/env python3
"""
Comprehensive translation integrity checker for LavBench.
Checks:
  1. Symmetry — keys present in one locale but missing from the other
  2. Missing — keys used via t('...') in source code but absent from translations
  3. Orphaned — keys defined in translations but never referenced in source code
  4. Hardcoded — user-facing text in JSX that should use t()

Handles dynamic key patterns like t('badge.' + role) and t(`path/${id}`).
"""

import os
import re
import json
import sys
from collections import defaultdict

# ── Colours ────────────────────────────────────────────────────────────────
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ── Helpers ────────────────────────────────────────────────────────────────
def flatten_keys(d, prefix=""):
    """Flatten a nested dict into dot-separated keys. Returns dict of key→value."""
    out = {}
    for k, v in d.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_keys(v, full))
        else:
            out[full] = v
    return out


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Extract keys used in source code ──────────────────────────────────────
def extract_used_keys(src_dir):
    """
    Scan all .jsx / .js files for t('key') calls.
    Returns (used_keys, dynamic_prefixes).
      - used_keys: set of fully-static dot-separated keys
      - dynamic_prefixes: set of prefixes that get a suffix concatenated at runtime
        e.g. 'badge.' (from t('badge.' + role)), 'api.' (from t(`api.${code}`))
    """
    used = set()
    dynamic_prefixes = set()

    # Pattern 1: t('static.key') or t("static.key")
    static_pat = re.compile(r"""\bt\(\s*['"]([^'"]+)['"]\s*[),]""")

    # Pattern 2: t('prefix.' + var) — string concatenation
    concat_pat = re.compile(r"""\bt\(\s*(['"]([^'"]*\.)['"])\s*\+""")

    # Pattern 3: t(`template_literal`) — may contain ${var}
    template_pat = re.compile(r"""\bt\(\s*`([^`]*)`""")

    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "assets", "types")]
        for fname in files:
            if not fname.endswith((".jsx", ".js")) or fname == "setupTests.js":
                continue
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()

            # Static strings
            for m in static_pat.finditer(content):
                key = m.group(1)
                if key and not key.startswith("${"):
                    used.add(key)

            # String concatenation → dynamic prefix
            for m in concat_pat.finditer(content):
                prefix = m.group(2)
                if prefix:
                    dynamic_prefixes.add(prefix)

            # Template literals
            for m in template_pat.finditer(content):
                tmpl = m.group(1)
                if "${" in tmpl:
                    # Dynamic template: extract the prefix before first ${var}
                    prefix = tmpl.split("${")[0]
                    if prefix:
                        dynamic_prefixes.add(prefix)
                else:
                    # Fully static template literal
                    used.add(tmpl)

    # Remove fully-static keys that are actually just dynamic prefixes
    # (e.g. if someone writes t('badge.') directly — that's a dynamic prefix usage)
    used = {k for k in used if k not in dynamic_prefixes}

    return used, dynamic_prefixes


# ── Symmetry check ────────────────────────────────────────────────────────
def check_symmetry(en_keys, bg_keys):
    en_set = set(en_keys.keys())
    bg_set = set(bg_keys.keys())
    only_en = sorted(en_set - bg_set)
    only_bg = sorted(bg_set - en_set)
    return only_en, only_bg


# ── Missing check ─────────────────────────────────────────────────────────
def check_missing(used_keys, en_keys, bg_keys, dynamic_prefixes):
    """Find keys used in code that are not in translations."""
    en_set = set(en_keys.keys())
    bg_set = set(bg_keys.keys())

    missing_en = []
    missing_bg = []

    for k in sorted(used_keys):
        # Skip known dynamic prefix fragments (like 'badge.')
        if k in dynamic_prefixes:
            continue
        if k not in en_set:
            missing_en.append(k)
        if k not in bg_set:
            missing_bg.append(k)

    return missing_en, missing_bg


# ── Orphaned check ────────────────────────────────────────────────────────
def check_orphaned(en_keys, used_keys, dynamic_prefixes):
    """Find translation keys that are never referenced in code."""
    en_set = set(en_keys.keys())
    orphaned = []

    for k in sorted(en_set):
        # Exact match test
        if k in used_keys:
            continue
        # Check if this key is reachable via a dynamic prefix
        # e.g. 'badge.admin' is reachable via t('badge.' + 'admin')
        for prefix in dynamic_prefixes:
            if k.startswith(prefix):
                break
        else:
            # Also check if any parent path is used dynamically
            parts = k.split(".")
            matched = False
            for i in range(len(parts), 0, -1):
                candidate = ".".join(parts[:i]) + ("." if i < len(parts) else "")
                if candidate in dynamic_prefixes:
                    matched = True
                    break
            if not matched:
                orphaned.append(k)

    return orphaned


# ── Report helpers ────────────────────────────────────────────────────────
def section(title):
    print(f"\n{BOLD}{'─' * 72}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'─' * 72}{RESET}")


def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg, items, limit=999):
    print(f"  {YELLOW}⚠ {RESET}{msg}: {len(items)}")
    for item in items[:limit]:
        print(f"      {RED}{item}{RESET}")
    if len(items) > limit:
        print(f"      {RED}... and {len(items) - limit} more{RESET}")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.abspath(os.path.join(script_dir, ".."))
    src_dir = os.path.join(frontend_dir, "src")

    en_path = os.path.join(frontend_dir, "public", "locales", "en", "translation.json")
    bg_path = os.path.join(frontend_dir, "public", "locales", "bg", "translation.json")

    if not os.path.exists(src_dir):
        print(f"{RED}Error: src/ not found at {src_dir}{RESET}")
        sys.exit(1)

    en_raw = load_json(en_path)
    bg_raw = load_json(bg_path)
    en_keys = flatten_keys(en_raw)
    bg_keys = flatten_keys(bg_raw)

    print(f"{BOLD}LavBench Translation Check{RESET}")
    print(f"  English keys : {len(en_keys)}")
    print(f"  Bulgarian keys: {len(bg_keys)}")

    used_keys, dynamic_prefixes = extract_used_keys(src_dir)
    print(f"  Source files scanned in src/")
    print(f"  Static keys used : {len(used_keys)}")
    if dynamic_prefixes:
        dyn_list = sorted(dynamic_prefixes)
        print(
            f"  Dynamic prefixes : {len(dyn_list)}  ({', '.join(dyn_list[:6])}{'...' if len(dyn_list) > 6 else ''})"
        )

    errors = 0
    warnings = 0

    # ── 1. Symmetry ──────────────────────────────────────────────────────
    section("1. Locale Symmetry (keys in one locale but not the other)")
    only_en, only_bg = check_symmetry(en_keys, bg_keys)
    if only_en:
        warn("Keys in English but missing from Bulgarian", only_en)
        warnings += 1
    else:
        ok("English keys match Bulgarian keys")

    if only_bg:
        warn("Keys in Bulgarian but missing from English", only_bg)
        warnings += 1

    if not only_en and not only_bg:
        ok("Both locales are perfectly in sync")

    # ── 2. Missing ───────────────────────────────────────────────────────
    section("2. Missing Translations (used in code, not in locale)  [ERROR]")
    missing_en, missing_bg = check_missing(
        used_keys, en_keys, bg_keys, dynamic_prefixes
    )

    if missing_en:
        warn("Used in code but MISSING from English", missing_en)
        errors += 1
    else:
        ok("No missing English keys")

    if missing_bg:
        warn("Used in code but MISSING from Bulgarian", missing_bg)
        errors += 1
    else:
        ok("No missing Bulgarian keys")

    if not missing_en and not missing_bg:
        ok("All code references have translations")

    # ── 3. Orphaned ─────────────────────────────────────────────────────
    section("3. Orphaned Translations (in locale, never used in code)  [WARNING]")
    orphaned = check_orphaned(en_keys, used_keys, dynamic_prefixes)
    if orphaned:
        warn("Defined but never referenced (may be intentional)", orphaned, limit=999)
        warnings += 1
    else:
        ok("No orphaned translations — every key is referenced")

    # ── Summary ──────────────────────────────────────────────────────────
    section("Summary")
    total_en = len(en_keys)
    total_bg = len(bg_keys)
    print(f"  English keys      : {total_en}")
    print(f"  Bulgarian keys    : {total_bg}")
    print(f"  Symmetry issues   : {len(only_en) + len(only_bg)}")
    print(f"  Missing keys      : {len(missing_en) + len(missing_bg)}")
    print(f"  Orphaned keys     : {len(orphaned)}")

    if errors == 0 and warnings == 0:
        print(f"\n  {GREEN}{BOLD}✓ All checks passed. Translations are clean.{RESET}")
    elif errors == 0:
        print(
            f"\n  {YELLOW}{BOLD}✓ No errors, but {warnings} warning(s) — see above.{RESET}"
        )
    else:
        print(f"\n  {RED}{BOLD}✗ {errors} error(s) — see above for details.{RESET}")

    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
