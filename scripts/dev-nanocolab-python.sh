#!/usr/bin/env bash
# Run the backend's Python with the environment of `make dev-nanocolab` (for example: - to read stdin)
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/.local-nanocolab/backend.env"
[[ -f "$env_file" ]] || { echo "start the stack with make dev-nanocolab first" >&2; exit 1; }
# shellcheck disable=SC1090
source "$env_file"
cd "$repo_root/backend"
exec micromamba run -n lavbench_backend python "$@"
