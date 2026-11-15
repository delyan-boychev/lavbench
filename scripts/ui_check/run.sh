#!/usr/bin/env bash
# Run the full UI visual check against a running throwaway stack (see stack.sh), or
# re-capture single scenarios. Output: index.html, sheets/, shots/, report.json.
#
#   scripts/ui_check/run.sh                      # seed, every phase
#   scripts/ui_check/run.sh --only KEY[,KEY...]  # re-capture scenarios ("role--name")
#
# Environment: UI_CHECK_OUT (default ui-check-output), UI_CHECK_BASE (default
# http://localhost:80), UI_CHECK_WORKERS (parallel browsers, default 6), PYTHON (a Python
# with pandas and pyarrow for the host-side scripts).
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
OUT=$(realpath -m "${UI_CHECK_OUT:-ui-check-output}")
BASE="${UI_CHECK_BASE:-http://localhost:80}"
PY="${PYTHON:-python3}"
IMAGE="lavbench-ui-check"
TOOL="scripts/ui_check"

capture() {
  docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e UI_CHECK_WORKERS="${UI_CHECK_WORKERS:-6}" \
    -v "$ROOT/$TOOL:/tool:ro" -v "$ROOT/frontend/public/locales:/locales:ro" -v "$OUT:/out" \
    "$IMAGE" python /tool/capture.py "$1"
}

state() { $PY "$TOOL/states.py" --out "$OUT" "$1"; }

# The capture image: Playwright plus the pinned packages, cached after the first build
docker build -q -t "$IMAGE" "$TOOL" >/dev/null

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
# The archived phase runs while the grace window closes
state archive-empty
capture archived
# Then show that the grace submission is still viewable once the window has closed
wait_s=$($PY -c "import json,time;print(max(0,int(json.load(open('$OUT/seed.json'))['grace_ends_at']-time.time())+5))")
sleep "$wait_s"
capture after-grace
state finalize
capture final
echo "visual check done: $OUT/index.html"
