#!/usr/bin/env bash
# Run the full UI visual check against a running throwaway stack (see stack.sh), or
# re-capture single scenarios. Output: index.html, sheets/, shots/, report.json.
#
#   scripts/ui_check/run.sh                      # seed, every phase, about 90 minutes
#   scripts/ui_check/run.sh --only KEY[,KEY...]  # re-capture scenarios ("role--name")
#
# Environment: UI_CHECK_OUT (default ui-check-output), UI_CHECK_BASE (default
# http://localhost:80), PYTHON (a Python with pandas and pyarrow for the host-side scripts).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
OUT=$(realpath -m "${UI_CHECK_OUT:-ui-check-output}")
BASE="${UI_CHECK_BASE:-http://localhost:80}"
PY="${PYTHON:-python3}"
IMAGE="mcr.microsoft.com/playwright/python:v1.63.0-noble"
TOOL="scripts/ui_check"

capture() {
  docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$ROOT/$TOOL:/tool:ro" -v "$ROOT/frontend/public/locales:/locales:ro" -v "$OUT:/out" \
    "$IMAGE" bash -c "pip install -q --user --no-warn-script-location \
      -r /tool/requirements.txt 2>/dev/null && python /tool/capture.py '$1'"
}

state() { $PY "$TOOL/states.py" --out "$OUT" "$1"; }

if [ "${1:-}" = "--only" ]; then
  [ -f "$OUT/seed.json" ] || { echo "no $OUT/seed.json: run the full check first" >&2; exit 1; }
  capture "only:$2"
  exit 0
fi

curl -fsS "$BASE/api/health" >/dev/null || { echo "no stack at $BASE (see stack.sh)" >&2; exit 1; }
[ -f admin_credentials.txt ] || { echo "admin_credentials.txt missing (stack.sh up writes it)" >&2; exit 1; }
rm -rf "$OUT"
mkdir -p "$OUT"

$PY "$TOOL/seed.py" --base "$BASE" --out "$OUT"
capture main
state live
capture live
state stop-live
capture actions
state freeze
capture frozen
state unfreeze
state grace
capture grace
# Wait until the grace window has closed, then show the grace submission is still viewable
wait_s=$($PY -c "import json,time;print(max(0,int(json.load(open('$OUT/seed.json'))['grace_ends_at']-time.time())+5))")
sleep "$wait_s"
capture after-grace
state archive-empty
capture archived
state finalize
capture final
echo "visual check done: $OUT/index.html"
