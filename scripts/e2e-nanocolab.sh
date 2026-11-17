#!/usr/bin/env bash
# Run the API-level role paths against the stack of `make dev-nanocolab`
set -euo pipefail
cd "$(dirname "$0")/.."

curl -fsS http://127.0.0.1:5001/api/health >/dev/null || { echo "start the stack with make dev-nanocolab" >&2; exit 1; }
exec micromamba run -n lavbench_backend python -u scripts/e2e_nanocolab.py "$@"
