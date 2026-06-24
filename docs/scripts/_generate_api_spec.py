"""Fetch the OpenAPI spec from the running backend, split by tag,
and generate a hierarchical api_spec.rst with per-tag sections."""

import json
import os
import sys
import re
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SOURCE_DIR = os.path.join(PROJECT_DIR, "docs", "source")
API_DIR = os.path.join(SOURCE_DIR, "api")
RST_PATH = os.path.join(SOURCE_DIR, "api_spec.rst")
DEFAULT_SPEC_PATH = os.path.join(API_DIR, "spec.json")
FETCH_URL = os.environ.get("API_SPEC_URL", "http://localhost:5001/apispec_1.json")


def fetch_spec():
    """Fetch the OpenAPI spec from the running backend, with fallback to cached spec.json."""
    import urllib.request
    import urllib.error

    if os.environ.get("API_SPEC_SKIP_FETCH"):
        # CI / offline: skip fetch entirely, use cached spec
        if os.path.exists(DEFAULT_SPEC_PATH):
            print(f"SKIP_FETCH set, loading cached spec from {DEFAULT_SPEC_PATH}")
            with open(DEFAULT_SPEC_PATH) as f:
                return json.load(f)
        print(
            "WARNING: API_SPEC_SKIP_FETCH set but no cached spec.json found.",
            file=sys.stderr,
        )
        return {
            "openapi": "3.0.0",
            "info": {"title": "LavBench API", "version": "unknown"},
            "paths": {},
        }

    try:
        resp = urllib.request.urlopen(FETCH_URL, timeout=5)
        spec = json.loads(resp.read().decode())
        print(f"Fetched spec from {FETCH_URL}")
        return spec
    except Exception as e:
        print(f"Could not fetch from {FETCH_URL}: {e}", file=sys.stderr)
        if os.path.exists(DEFAULT_SPEC_PATH):
            print(
                f"Falling back to cached spec at {DEFAULT_SPEC_PATH}", file=sys.stderr
            )
            with open(DEFAULT_SPEC_PATH) as f:
                spec = json.load(f)
            print(f"Loaded cached spec ({len(spec.get('paths', {}))} paths)")
            return spec
        print(
            "WARNING: No spec source available. Generating empty spec.", file=sys.stderr
        )
        return {
            "openapi": "3.0.0",
            "info": {"title": "LavBench API", "version": "unknown"},
            "paths": {},
        }


def safe_filename(tag):
    """Convert a tag string to a safe filename fragment."""
    name = tag.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    return f"spec_{name}.json"


def fix_params_schema(spec):
    """Convert Swagger 2.0-style params (top-level type) to OpenAPI 3.0 (schema wrapper)."""
    converted = 0
    for path, methods in spec.get("paths", {}).items():
        for method, detail in methods.items():
            params = detail.get("parameters", [])
            for p in params:
                if "schema" not in p and "type" in p:
                    p["schema"] = {"type": p["type"]}
                    del p["type"]
                    converted += 1
    if converted:
        print(f"Fixed {converted} parameters (wrapped top-level type into schema)")
    return spec


def group_by_tag(spec):
    """Group spec paths by tag. Returns OrderedDict of tag -> (paths_dict, sorted_paths)."""
    by_tag = OrderedDict()

    for path, methods in spec.get("paths", {}).items():
        for method, detail in methods.items():
            tags = detail.get("tags", ["General"])
            primary_tag = tags[0]
            if primary_tag not in by_tag:
                by_tag[primary_tag] = {}
            if path not in by_tag[primary_tag]:
                by_tag[primary_tag][path] = {}
            by_tag[primary_tag][path][method] = detail

    return by_tag


def write_tag_specs(spec, by_tag):
    """Write one spec file per tag, and return the ordered list of (tag, filename) pairs."""
    tag_files = []
    for tag, paths in by_tag.items():
        tag_spec = {
            "openapi": spec.get("openapi", "3.0.0"),
            "info": spec.get("info", {}),
        }
        if "components" in spec:
            tag_spec["components"] = spec["components"]
        if "security" in spec:
            tag_spec["security"] = spec["security"]

        # Sort paths within the tag
        sorted_paths = OrderedDict(sorted(paths.items()))
        tag_spec["paths"] = sorted_paths

        filename = safe_filename(tag)
        filepath = os.path.join(API_DIR, filename)
        with open(filepath, "w") as f:
            json.dump(tag_spec, f, indent=2)
        endpoint_count = sum(len(methods) for methods in paths.values())
        print(f"  {tag}: {endpoint_count} endpoints -> {filename}")
        tag_files.append((tag, filename))

    return tag_files


def write_rst(tag_files):
    """Generate api_spec.rst with per-tag sections."""
    lines = [
        "API Specification",
        "=================",
        "",
        ".. raw:: html",
        "",
        "    <p>Endpoints are grouped by tag. Each section below is rendered from a subset of the full OpenAPI specification.</p>",
        "",
    ]

    for tag, filename in tag_files:
        safe_tag = tag.replace("_", r"\_")
        lines.extend(
            [
                safe_tag,
                "-" * len(tag),
                "",
                f".. openapi:: api/{filename}",
                "",
            ]
        )

    lines.extend(
        [
            "Full specification",
            "------------------",
            "",
            f".. openapi:: api/spec.json",
            "",
        ]
    )

    content = "\n".join(lines) + "\n"
    with open(RST_PATH, "w") as f:
        f.write(content)
    print(f"Generated {RST_PATH} with {len(tag_files)} tag sections")


def main():
    spec = fetch_spec()
    spec = fix_params_schema(spec)

    # Save the fixed main spec
    with open(DEFAULT_SPEC_PATH, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"Saved main spec ({len(spec.get('paths', {}))} paths)")

    by_tag = group_by_tag(spec)
    tag_files = write_tag_specs(spec, by_tag)
    write_rst(tag_files)
    print("Done.")


if __name__ == "__main__":
    main()
