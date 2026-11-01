#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
purge=false
[[ "${1:-}" == "--purge" ]] && purge=true

pkill -f "scripts/dev-nanocolab.sh" 2>/dev/null || true
pkill -f "$repo_root/backend/.venv/bin/python app.py" 2>/dev/null && echo "Stopped Flask" || true
pkill -f "vite --port 5173" 2>/dev/null && echo "Stopped Vite" || true

docker rm -f lavbench_local_pg lavbench_local_redis >/dev/null 2>&1 && echo "Removed Postgres and Redis containers" || true

if [[ "$purge" == true ]]; then
  rm -rf "$repo_root/.local-nanocolab"
  echo "Removed local secrets, admin credentials, logs and uploads ($repo_root/.local-nanocolab)"
fi
echo "LavBench local stack is down"
