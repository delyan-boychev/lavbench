#!/usr/bin/env bash
# Start nanoColab and LavBench locally (backend/README.md); stop with dev-nanocolab-down.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
nanocolab_root="$(cd "${NANOCOLAB_ROOT:-$repo_root/../nano-colab}" && pwd)"
state="$repo_root/.local-nanocolab"
pg_port="${LB_PG_PORT:-5433}"
redis_port="${LB_REDIS_PORT:-6381}"
pg="lavbench_nanocolab_pg"
redis="lavbench_nanocolab_redis"
eval_worker="lavbench_nanocolab_eval"
# The throwaway worker key pair CI uses (scripts/ui_check/stack.sh)
worker_public='{"dev-eval-worker":"gwEOQ7vkepTvOxbVFGy/iayILrRTEsYbw54+I5BF7RY="}'
worker_private="NaKOt/qVZHOA4rAe6MmGoj/bNkHSG1FjTxrzcYL7zBU="

fail() { echo "dev-nanocolab: $*" >&2; exit 1; }

# ── Tools ──
for tool in docker kind kubectl helm micromamba node npm openssl curl; do
  command -v "$tool" >/dev/null || fail "$tool is missing (see backend/README.md, local nanoColab stack)"
done
helm version --short | grep -q '^v3\.' || fail "helm 3 is required (tested: v3.22.1)"
micromamba run -n lavbench_backend python -c 'import sys; assert sys.version_info[:2] == (3, 12)' \
  || fail "the micromamba env lavbench_backend must exist with Python 3.12"
echo "kind $(kind version | awk '{print $2}'), $(kubectl version --client | head -1), helm $(helm version --short), node $(node --version)"
[[ -d "$nanocolab_root/deploy/local" ]] || fail "no nanoColab checkout at $nanocolab_root (set NANOCOLAB_ROOT)"

mkdir -p "$state/logs" "$state/uploads"
chmod 700 "$state"

# ── nanoColab ──
if ! kind get clusters 2>/dev/null | grep -qx nanocolab-local; then
  echo "Starting nanoColab's kind cluster (about 6 minutes the first time)"
  "$nanocolab_root/deploy/local/up.sh" > "$state/logs/nanocolab-up.log" 2>&1 \
    || fail "nanoColab up.sh failed, see $state/logs/nanocolab-up.log"
fi
if ! pgrep -f "uvicorn nanocolab_api.entrypoint:" >/dev/null; then
  nohup "$nanocolab_root/deploy/local/api.sh" > "$state/logs/nanocolab-api.log" 2>&1 &
  echo $! >> "$state/pids"
fi
nanocolab_url="$(bash -c "eval \"\$('$nanocolab_root/deploy/local/lavbench.env.sh')\"; echo \$NANOCOLAB_API_URL")"
(umask 077; bash -c "eval \"\$('$nanocolab_root/deploy/local/lavbench.env.sh')\"; printf '%s\n' \"\$NANOCOLAB_API_KEY\"" > "$state/nanocolab_api_key")
for _ in $(seq 1 60); do curl -fsS "$nanocolab_url/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "$nanocolab_url/healthz" >/dev/null || fail "nanoColab API did not start, see $state/logs/nanocolab-api.log"

# ── LavBench secrets, Postgres and Redis ──
env_file="$state/env"
if [[ ! -f "$env_file" ]]; then
  (umask 077; {
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "ENCRYPTION_KEY=$(micromamba run -n lavbench_backend python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    echo "WORKER_CAPABILITY_SECRET=$(openssl rand -hex 32)"
    echo "EVALUATION_SPLIT_SECRET=$(openssl rand -hex 32)"
  } > "$env_file")
fi
set -a; source "$env_file"; set +a

docker inspect "$pg" >/dev/null 2>&1 || docker run -d --name "$pg" --memory=512m \
  -p "127.0.0.1:$pg_port:5432" -e POSTGRES_USER=lavbench_user \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" -e POSTGRES_DB=lavbench_db postgres:15-alpine >/dev/null
docker inspect "$redis" >/dev/null 2>&1 || docker run -d --name "$redis" --memory=192m \
  -p "127.0.0.1:$redis_port:6379" redis:7.4-alpine \
  redis-server --save "" --appendonly yes --maxmemory 128mb --maxmemory-policy noeviction >/dev/null
docker start "$pg" "$redis" >/dev/null
until docker exec "$pg" pg_isready -U lavbench_user -d lavbench_db >/dev/null 2>&1; do sleep 1; done

export DATABASE_URL="postgresql://lavbench_user:$POSTGRES_PASSWORD@127.0.0.1:$pg_port/lavbench_db"
export CELERY_BROKER_URL="redis://127.0.0.1:$redis_port/0"
export CACHE_REDIS_URL="redis://127.0.0.1:$redis_port/1"
export UPLOAD_FOLDER="$state/uploads"
export LOG_DIR="$state/logs"
export MAIN_SERVER_URL="http://127.0.0.1:5001"
export WORKER_PUBLIC_KEYS_JSON="$worker_public"
export NANOCOLAB_API_URL="$nanocolab_url"
export NANOCOLAB_API_KEY_FILE="$state/nanocolab_api_key"
export NANOCOLAB_ALLOW_INSECURE_HTTP=true
# Tools such as scripts/dev-nanocolab-python.sh reuse this environment
(umask 077; export -p | grep -E ' (POSTGRES_PASSWORD|SECRET_KEY|ENCRYPTION_KEY|WORKER_CAPABILITY_SECRET|EVALUATION_SPLIT_SECRET|DATABASE_URL|CELERY_BROKER_URL|CACHE_REDIS_URL|UPLOAD_FOLDER|LOG_DIR|MAIN_SERVER_URL|WORKER_PUBLIC_KEYS_JSON|NANOCOLAB_[A-Z_]+)=' > "$state/backend.env")

# ── Migrations and admin ──
cd "$repo_root/backend"
micromamba run -n lavbench_backend python scripts/migrate.py > "$state/logs/migrate.log" 2>&1 \
  || fail "migrations failed, see $state/logs/migrate.log"
if [[ ! -f "$state/admin_credentials.txt" ]]; then
  output="$(micromamba run -n lavbench_backend python scripts/setup-admin.py 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g')"
  user="$(grep -A1 'Generated Admin Username:' <<< "$output" | tail -1 | xargs)"
  key="$(grep -A1 'Generated Master Key:' <<< "$output" | tail -1 | xargs)"
  [[ -n "$user" && -n "$key" ]] || fail "could not create the admin"
  (umask 077; printf 'Admin Username : %s\nMaster Key     : %s\n' "$user" "$key" > "$state/admin_credentials.txt")
fi

# ── LavBench processes ──
start() {
  local name="$1"; shift
  # Each process leads its own group, so the down script stops its children too
  nohup setsid "$@" > "$state/logs/$name.log" 2>&1 &
  echo $! >> "$state/pids"
}
# Served like production (backend/Dockerfile): the threaded Flask server crashes in pyarrow
start gunicorn micromamba run -n lavbench_backend \
  gunicorn -k gevent -w 2 --timeout 300 -b 127.0.0.1:5001 utils.wsgi:app
start celery-internal env WORKER_ROLE=internal micromamba run -n lavbench_backend \
  celery -A tasks.celery worker -Q celery,internal -c 2 --loglevel=info -n "internal@%h"
start celery-beat env WORKER_ROLE=scheduler micromamba run -n lavbench_backend \
  celery -A tasks.celery beat --loglevel=info --schedule "$state/celerybeat-schedule"
[[ -d "$repo_root/frontend/node_modules" ]] || (cd "$repo_root/frontend" && npm ci --silent)
start vite bash -c "cd '$repo_root/frontend' && exec npm run dev -- --host localhost --port 5173 --strictPort"

docker build -q -f "$repo_root/backend/Dockerfile.worker" -t lavbench-worker "$repo_root/backend" >/dev/null
docker rm -f "$eval_worker" >/dev/null 2>&1 || true
docker run -d --name "$eval_worker" --network host \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  -e CELERY_BROKER_URL -e CACHE_REDIS_URL -e SECRET_KEY -e ENCRYPTION_KEY \
  -e WORKER_CAPABILITY_SECRET -e EVALUATION_SPLIT_SECRET -e MAIN_SERVER_URL \
  -e WORKER_PRIVATE_KEY="$worker_private" -e WORKER_ID="dev-eval-worker" -e WORKER_ROLE=eval \
  -e CPU_WORKER_CONCURRENCY=1 -e WORKER_SANDBOX_STORAGE_OPT="" \
  -e TASK_IMAGES_DIR=/var/lib/lavbench/task_images -e HF_CACHE_DIR=/var/lib/lavbench/hf_cache \
  -e LAVBENCH_WORKSPACE_DIR=/var/lib/lavbench/workspace \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v lavbench_nanocolab_task_images:/var/lib/lavbench/task_images \
  -v lavbench_nanocolab_hf_cache:/var/lib/lavbench/hf_cache \
  -v lavbench_nanocolab_workspace:/var/lib/lavbench/workspace \
  lavbench-worker >/dev/null

for _ in $(seq 1 60); do curl -fsS http://127.0.0.1:5001/api/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:5001/api/health >/dev/null || fail "the backend did not start, see $state/logs/gunicorn.log"

echo
echo "LavBench UI:   http://localhost:5173   (use localhost: the Hub accepts launches only from it)"
echo "LavBench API:  http://127.0.0.1:5001/api"
echo "nanoColab API: $nanocolab_url/v1/docs"
echo "Logs:          $state/logs"
cat "$state/admin_credentials.txt"
echo "Stop with: make dev-nanocolab-down"
