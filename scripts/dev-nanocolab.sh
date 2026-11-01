#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
nanocolab_root="${NANOCOLAB_ROOT:-$repo_root/../nano-colab}"
state="$repo_root/.local-nanocolab"
python="$repo_root/backend/.venv/bin/python"
pg="lavbench_local_pg"
redis="lavbench_local_redis"

[[ -x "$python" ]] || { echo "Missing $python (create backend/.venv first)" >&2; exit 1; }
[[ -f "$nanocolab_root/deploy/local/.state/secrets.env" ]] || { echo "Run nano-colab deploy/local/up.sh first" >&2; exit 1; }

mkdir -p "$state/logs" "$state/uploads"
chmod 700 "$state"
env_file="$state/env"
if [[ ! -f "$env_file" ]]; then
  umask 077
  pg_password="$(openssl rand -hex 16)"
  {
    echo "POSTGRES_PASSWORD=$pg_password"
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "ENCRYPTION_KEY=$("$python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  } > "$env_file"
fi
set -a; source "$env_file"; set +a

if ! docker inspect "$pg" >/dev/null 2>&1; then
  docker run -d --name "$pg" --memory=512m -p 127.0.0.1:5433:5432 \
    -e POSTGRES_USER=lavbench_user -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" -e POSTGRES_DB=lavbench_db \
    postgres:15-alpine >/dev/null
fi
if ! docker inspect "$redis" >/dev/null 2>&1; then
  docker run -d --name "$redis" --memory=192m -p 127.0.0.1:6379:6379 \
    redis:7.4-alpine redis-server --save "" --appendonly yes --maxmemory 128mb --maxmemory-policy noeviction >/dev/null
fi
docker start "$pg" "$redis" >/dev/null
until docker exec "$pg" pg_isready -U lavbench_user -d lavbench_db >/dev/null 2>&1; do sleep 1; done

export DATABASE_URL="postgresql://lavbench_user:$POSTGRES_PASSWORD@127.0.0.1:5433/lavbench_db"
export CELERY_BROKER_URL="redis://127.0.0.1:6379/0"
export CELERY_RESULT_BACKEND="redis://127.0.0.1:6379/0"
export CACHE_REDIS_URL="redis://127.0.0.1:6379/1"
export UPLOAD_FOLDER="$state/uploads"
export LOG_DIR="$state/logs"
export FLASK_DEBUG=1
eval "$("$nanocolab_root/deploy/local/lavbench.env.sh")"

cd "$repo_root/backend"
if [[ ! -f "$state/admin_credentials.txt" ]]; then
  "$python" scripts/setup-admin.py > "$state/admin_credentials.txt" 2>&1 || { cat "$state/admin_credentials.txt" >&2; rm -f "$state/admin_credentials.txt"; exit 1; }
  chmod 600 "$state/admin_credentials.txt"
  echo "Admin credentials written to $state/admin_credentials.txt"
else
  "$python" scripts/migrate.py
fi

trap 'kill 0' EXIT INT TERM
"$python" app.py > "$state/flask.log" 2>&1 &
(cd "$repo_root/frontend" && npm run dev -- --port 5173 --strictPort > "$state/vite.log" 2>&1) &
echo "LavBench API: http://localhost:5001/api   (log: $state/flask.log)"
echo "LavBench UI:  http://localhost:5173       (log: $state/vite.log)"
wait
