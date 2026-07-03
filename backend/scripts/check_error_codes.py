#!/usr/bin/env python3
"""
Lint script: ensure every error response uses the err() helper instead of
raw jsonify({"error": ...}), that err() calls reference a valid error
code defined in error_utils.DEFAULT_ERROR_MESSAGES, that no defined
error codes go unused, and that frontend translation keys match.

Checks:
1. jsonify({"error": ...}) is rejected entirely — must use err() helper
2. err() calls must have a string-literal ERR_[A-Z0-9_]+ as first argument
3. err() code must exist in DEFAULT_ERROR_MESSAGES dict in error_utils.py
4. Every code in DEFAULT_ERROR_MESSAGES must be referenced by at least one err() call
5. Every code in DEFAULT_ERROR_MESSAGES must have a translation key in frontend's api section
6. No extra api.ERR_* keys in frontend translations (were likely removed/renamed)

Usage:
    python scripts/check_error_codes.py [files...]
    # If no files given, checks all *.py under routes/ plus auth_utils.py, app.py
"""

import ast
import re
import sys
from pathlib import Path


def _get_str_keys(dict_node):
    """Extract string key names from an ast.Dict literal."""
    keys = set()
    for k in dict_node.keys:
        if k is None:
            continue
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys


def _get_str_value(node):
    """Return the string value of an AST node if it's a string constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _load_valid_codes(error_utils_path):
    """Extract all ERR_* keys from DEFAULT_ERROR_MESSAGES dict in error_utils.py."""
    text = Path(error_utils_path).read_text()
    tree = ast.parse(text, filename=str(error_utils_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "DEFAULT_ERROR_MESSAGES"
                    and isinstance(node.value, ast.Dict)
                ):
                    codes = set()
                    for k in node.value.keys:
                        val = _get_str_value(k)
                        if val and val.startswith("ERR_"):
                            codes.add(val)
                    return codes
    return set()


def check_file(filepath, valid_codes):
    """Return (violations, used_codes) tuple.

    violations: list of (filepath, lineno, message)
    used_codes: set of ERR_* code strings found in err() calls
    """
    text = Path(filepath).read_text()
    tree = ast.parse(text, filename=str(filepath))
    violations = []
    used_codes = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        # ── Check 1: raw jsonify({"error": ...}) — must use err() helper ──
        if func_name == "jsonify":
            for arg in node.args:
                if not isinstance(arg, ast.Dict):
                    continue
                keys = _get_str_keys(arg)

                if "error" not in keys:
                    continue

                violations.append(
                    (
                        filepath,
                        node.lineno,
                        'Use err() helper instead of raw jsonify({"error": ...})',
                    )
                )

        # ── Check 2: err() calls must have literal first arg ──
        if func_name == "err" and node.args:
            code_val = _get_str_value(node.args[0])
            if code_val is None:
                violations.append(
                    (
                        filepath,
                        node.lineno,
                        "err() first argument must be a string literal (error code)",
                    )
                )
            elif not re.match(r"^ERR_[A-Z0-9_]+$", code_val):
                violations.append(
                    (
                        filepath,
                        node.lineno,
                        f"err() code '{code_val}' does not match ERR_[A-Z0-9_]+ pattern",
                    )
                )
            elif valid_codes and code_val not in valid_codes:
                violations.append(
                    (
                        filepath,
                        node.lineno,
                        f"err() code '{code_val}' is not defined in DEFAULT_ERROR_MESSAGES",
                    )
                )

            if code_val:
                used_codes.add(code_val)

    return violations, used_codes


def main():
    root = Path(__file__).resolve().parent.parent
    args = sys.argv[1:]

    if args:
        files = [Path(f).resolve() for f in args]
    else:
        routes_dir = root / "routes"
        files = sorted(routes_dir.glob("*.py"))
        for extra in ["auth_utils.py", "app.py"]:
            p = root / extra
            if p.exists():
                files.append(p)

    error_utils_path = root / "error_utils.py"
    valid_codes = _load_valid_codes(error_utils_path) if error_utils_path.exists() else set()

    all_violations = []
    all_used_codes = set()
    for f in files:
        if not f.exists():
            print(f"Skipping {f} (not found)")
            continue
        violations, used = check_file(f, valid_codes)
        all_violations.extend(violations)
        all_used_codes.update(used)

    # Check 3: unused error codes defined in DEFAULT_ERROR_MESSAGES
    unused_codes = sorted(valid_codes - all_used_codes)
    if unused_codes:
        all_violations.extend(
            (error_utils_path, 0, f"Unused error code '{code}' defined in DEFAULT_ERROR_MESSAGES")
            for code in unused_codes
        )

    # Check 5 & 6: frontend translation key parity
    frontend_root = root.parent / "frontend"
    for locale in ["en", "bg"]:
        trans_path = frontend_root / "public" / "locales" / locale / "translation.json"
        if not trans_path.exists():
            continue
        import json as _json

        with open(trans_path) as _f:
            trans = _json.load(_f)
        api_keys = set()
        if "api" in trans:
            for k in trans["api"]:
                if k.startswith("ERR_"):
                    api_keys.add(k)
        # Missing translations
        missing = sorted(valid_codes - api_keys)
        if missing:
            all_violations.extend(
                (trans_path, 0, f"Missing translation for '{code}' in {locale}/translation.json")
                for code in missing[:10]
            )
            if len(missing) > 10:
                all_violations.append(
                    (trans_path, 0, f"  ... and {len(missing) - 10} more missing in {locale}")
                )
        # Extra (dead) translations
        extra = sorted(api_keys - valid_codes)
        if extra:
            all_violations.extend(
                (trans_path, 0, f"Extra translation for '{code}' in {locale}/translation.json")
                for code in extra
            )

    if all_violations:
        print(f"ERROR: {len(all_violations)} violation(s) found.\n")
        for fp, lineno, msg in sorted(all_violations, key=lambda x: (x[0], x[1], x[2])):
            rel = fp.relative_to(root.parent) if root.parent in fp.parents else fp
            loc = f":{lineno}" if lineno else ""
            print(f"  {rel}{loc}  {msg}")
        sys.exit(1)
    else:
        print(
            "OK: all error responses use err() helper with valid codes defined in error_utils.py."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
