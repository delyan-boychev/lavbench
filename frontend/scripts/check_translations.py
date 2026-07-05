#!/usr/bin/env python3
"""
Comprehensive translation integrity checker for LavBench.
Checks:
  1. Symmetry — keys present in one locale but missing from the other
  2. Missing — keys used via t('...') in source code but absent from translations
  3. Orphaned — keys defined in translations but never referenced in source code

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


# ── Extract keys used in source code with locations ────────────────────────
def extract_used_keys(src_dir):
    """
    Scan all .jsx / .js files for t('key') calls.
    Returns (used_keys, dynamic_prefixes, locations).
      - used_keys: set of fully-static dot-separated keys
      - dynamic_prefixes: set of prefixes that get a suffix concatenated at runtime
      - locations: dict key → list of (filepath, lineno)
    """
    used = set()
    dynamic_prefixes = set()
    locations = defaultdict(list)

    static_pat = re.compile(r"""\bt\(\s*['"]([^'"]+)['"]\s*[),]""")
    concat_pat = re.compile(r"""\bt\(\s*(['"]([^'"]*\.)['"])\s*\+""")
    template_pat = re.compile(r"""\bt\(\s*`([^`]*)`""")

    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "assets", "types")]
        for fname in files:
            if not fname.endswith((".jsx", ".js")) or fname == "setupTests.js":
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, src_dir)
            with open(fpath, "r", encoding="utf-8") as fh:
                content = fh.read()

            for m in static_pat.finditer(content):
                key = m.group(1)
                if key and not key.startswith("${"):
                    used.add(key)
                    locations[key].append((rel, content[:m.start()].count("\n") + 1))

            for m in concat_pat.finditer(content):
                prefix = m.group(2)
                if prefix:
                    dynamic_prefixes.add(prefix)

            for m in template_pat.finditer(content):
                tmpl = m.group(1)
                if "${" in tmpl:
                    prefix = tmpl.split("${")[0]
                    if prefix:
                        dynamic_prefixes.add(prefix)
                else:
                    used.add(tmpl)
                    locations[tmpl].append((rel, content[:m.start()].count("\n") + 1))

    used = {k for k in used if k not in dynamic_prefixes}
    return used, dynamic_prefixes, locations


# ── Group keys by namespace ────────────────────────────────────────────────
def group_by_namespace(keys):
    groups = defaultdict(list)
    for k in keys:
        ns = k.split(".")[0] if "." in k else "(root)"
        groups[ns].append(k)
    return dict(sorted(groups.items()))


# ── Symmetry check ────────────────────────────────────────────────────────
def check_symmetry(en_keys, bg_keys):
    en_set = set(en_keys.keys())
    bg_set = set(bg_keys.keys())
    only_en = sorted(en_set - bg_set)
    only_bg = sorted(bg_set - en_set)
    return only_en, only_bg


# ── Missing check ─────────────────────────────────────────────────────────
def check_missing(used_keys, en_keys, bg_keys, dynamic_prefixes, locations):
    """Find keys used in code that are not in translations."""
    en_set = set(en_keys.keys())
    bg_set = set(bg_keys.keys())

    missing_en = []
    missing_bg = []

    for k in sorted(used_keys):
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
        if k in used_keys:
            continue
        for prefix in dynamic_prefixes:
            if k.startswith(prefix):
                break
        else:
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
    print(f"  English keys    : {len(en_keys)}")
    print(f"  Bulgarian keys  : {len(bg_keys)}")

    used_keys, dynamic_prefixes, locations = extract_used_keys(src_dir)
    print(f"  Source files scanned in src/")
    print(f"  Static keys used: {len(used_keys)}")
    if dynamic_prefixes:
        dyn_list = sorted(dynamic_prefixes)
        print(
            f"  Dynamic prefixes: {len(dyn_list)}  ({', '.join(dyn_list[:6])}{'...' if len(dyn_list) > 6 else ''})"
        )

    errors = 0
    warnings = 0

    # ── 1. Symmetry ──────────────────────────────────────────────────────
    section("1. Locale Symmetry (keys in one locale but not the other)")
    only_en, only_bg = check_symmetry(en_keys, bg_keys)
    if only_en:
        print(f"  {YELLOW}✗{RESET} Keys in English but missing from Bulgarian: {len(only_en)}")
        for k in only_en:
            print(f"      {RED}{k}{RESET}")
        warnings += 1
    else:
        ok("English keys match Bulgarian keys")

    if only_bg:
        print(f"  {YELLOW}✗{RESET} Keys in Bulgarian but missing from English: {len(only_bg)}")
        for k in only_bg:
            print(f"      {RED}{k}{RESET}")
        warnings += 1

    if not only_en and not only_bg:
        ok("Both locales are perfectly in sync")

    # ── 2. Missing ───────────────────────────────────────────────────────
    section("2. Missing Translations (used in code, not in locale)")
    missing_en, missing_bg = check_missing(
        used_keys, en_keys, bg_keys, dynamic_prefixes, locations
    )

    if missing_en:
        print(f"  {RED}✗{RESET} Used in code but MISSING from English: {len(missing_en)}")
        for k in missing_en:
            locs = locations.get(k, [])
            loc_str = "; ".join(f"{f}:{ln}" for f, ln in locs)
            print(f"      {RED}{k}{RESET}")
            if loc_str:
                print(f"        → {loc_str}")
        errors += 1
    else:
        ok("No missing English keys")

    if missing_bg:
        print(f"  {RED}✗{RESET} Used in code but MISSING from Bulgarian: {len(missing_bg)}")
        for k in missing_bg[:20]:
            locs = locations.get(k, [])
            loc_str = "; ".join(f"{f}:{ln}" for f, ln in locs)
            print(f"      {RED}{k}{RESET}")
            if loc_str:
                print(f"        → {loc_str}")
        if len(missing_bg) > 20:
            print(f"      {RED}... and {len(missing_bg) - 20} more{RESET}")
        errors += 1
    else:
        ok("No missing Bulgarian keys")

    if not missing_en and not missing_bg:
        ok("All code references have translations")

    # ── 3. Orphaned ─────────────────────────────────────────────────────
    section("3. Orphaned Translations (in locale, never used in code)")
    orphaned = check_orphaned(en_keys, used_keys, dynamic_prefixes)
    if orphaned:
        grouped = group_by_namespace(orphaned)
        print(f"  {YELLOW}⚠{RESET} Defined but never referenced in source code: {len(orphaned)}")
        print(f"  {YELLOW}⚠{RESET} Grouped by namespace:")
        for ns, keys in grouped.items():
            print(f"      {CYAN}{ns}{RESET} ({len(keys)} keys)")
            for k in keys:
                val = en_keys.get(k, "")
                display = val[:60] + "..." if len(val) > 60 else val
                print(f"        {YELLOW}{k}{RESET}  →  \"{display}\"")
        warnings += 1
    else:
        ok("No orphaned translations — every key is referenced")

    # ── Summary ──────────────────────────────────────────────────────────
    section("Summary")
    print(f"  English keys      : {len(en_keys)}")
    print(f"  Bulgarian keys    : {len(bg_keys)}")
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
