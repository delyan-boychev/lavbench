#!/usr/bin/env bash
# Stop what dev-nanocolab.sh started; --purge also deletes LavBench's local data and nanoColab's cluster
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
nanocolab_root="${NANOCOLAB_ROOT:-$repo_root/../nano-colab}"
state="$repo_root/.local-nanocolab"

if [[ -f "$state/pids" ]]; then
  while read -r pid; do
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  done < "$state/pids"
  rm -f "$state/pids"
fi
pkill -f "uvicorn nanocolab_api.entrypoint:" 2>/dev/null || true
pkill -f "deploy/local/preparer.py" 2>/dev/null || true
docker rm -f lavbench_nanocolab_eval >/dev/null 2>&1 || true
docker stop lavbench_nanocolab_pg lavbench_nanocolab_redis >/dev/null 2>&1 || true

if [[ "${1:-}" == "--purge" ]]; then
  docker rm -fv lavbench_nanocolab_pg lavbench_nanocolab_redis >/dev/null 2>&1 || true
  docker volume rm lavbench_nanocolab_task_images lavbench_nanocolab_hf_cache \
    lavbench_nanocolab_workspace >/dev/null 2>&1 || true
  rm -rf "$state"
  [[ -x "$nanocolab_root/deploy/local/down.sh" ]] && "$nanocolab_root/deploy/local/down.sh"
fi
echo "LavBench and the nanoColab API are stopped"
