#!/usr/bin/env bash
# scripts/deploy-server.sh — Deploy LavBench server with Docker Compose.
# Called by: make deploy-server
set -euo pipefail

# Clean up the temporary Compose environment file on exit.
cleanup() {
  if [ -n "${DOCKER_ENV_FILE:-}" ]; then
    rm -f "$DOCKER_ENV_FILE"
  fi
}
trap cleanup EXIT

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║  Deploying LavBench with Docker Compose        ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

# ── Preflight: Docker daemon ───────────────────────────────────────
if ! docker info &>/dev/null; then
  echo "  [ERROR] Docker daemon is not running." >&2
  exit 1
fi
echo "  ✔ Docker daemon running"

# ── Preflight: .env exists with required vars ──────────────────────
if [ ! -f ".env" ]; then
  echo "  [ERROR] .env not found. Run: make setup-server"
  exit 1
fi
REQUIRED_VARS=(
  "SECRET_KEY"
  "ENCRYPTION_KEY"
  "POSTGRES_PASSWORD"
  "REDIS_PASSWORD"
  "WORKER_PUBLIC_KEYS_JSON"
  "WORKER_CAPABILITY_SECRET"
  "EVALUATION_SPLIT_SECRET"
)
for var in "${REQUIRED_VARS[@]}"; do
  val=$(grep "^${var}=" .env 2>/dev/null | tail -1 | cut -d= -f2-) || true
  if [ -z "$val" ]; then
    echo "  [ERROR] ${var} is not set in .env. Run: make setup-server"
    exit 1
  fi
done
echo "  ✔ .env configured (all required keys present)"
echo ""

# ── Create Docker-specific .env (resolves nested variables) ──────────
REDIS_PASSWORD=$(grep "^REDIS_PASSWORD=" .env | tail -1 | cut -d= -f2-)
POSTGRES_PASSWORD=$(grep "^POSTGRES_PASSWORD=" .env | tail -1 | cut -d= -f2-)
POSTGRES_USER=$(grep "^POSTGRES_USER=" .env 2>/dev/null | tail -1 | cut -d= -f2-) || true
POSTGRES_DB=$(grep "^POSTGRES_DB=" .env 2>/dev/null | tail -1 | cut -d= -f2-) || true
: "${POSTGRES_USER:=lavbench_user}"
: "${POSTGRES_DB:=lavbench_db}"
export REDIS_PASSWORD POSTGRES_PASSWORD POSTGRES_USER POSTGRES_DB
umask 077
DOCKER_ENV_FILE=$(mktemp "${TMPDIR:-/tmp}/lavbench-compose-env.XXXXXX")
grep -v -E '^(CELERY_BROKER_URL|CELERY_RESULT_BACKEND|DATABASE_URL)=' .env > "$DOCKER_ENV_FILE"
echo "CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0" >> "$DOCKER_ENV_FILE"
echo "CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/0" >> "$DOCKER_ENV_FILE"
echo "DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}" >> "$DOCKER_ENV_FILE"

# ── Preserve uploads stored by older images outside the shared volume ──
if ! BACKEND_ID=$(docker compose --env-file "$DOCKER_ENV_FILE" ps -a -q backend); then
  echo "  [ERROR] Could not inspect the existing backend container." >&2
  exit 1
fi
if [ -n "$BACKEND_ID" ]; then
  if [ "$(docker inspect -f '{{.State.Running}}' "$BACKEND_ID")" != true ]; then
    echo "  [ERROR] Existing backend is stopped. Start it to migrate legacy uploads before deployment." >&2
    exit 1
  fi
  echo "  → Preserving legacy uploads in the shared volume..."
  if docker compose --env-file "$DOCKER_ENV_FILE" exec -T backend python - <<'PY'
import filecmp
import os
import shutil
import stat
import tempfile
from pathlib import Path

source = Path("/app/config/uploads")
destination = Path("/app/uploads")
if source.is_symlink() or (source.exists() and not source.is_dir()):
    raise SystemExit("Legacy upload path is not a directory")
if not source.exists():
    print("No legacy uploads found")
    raise SystemExit(0)

copied = 0
def raise_walk_error(error: OSError) -> None:
    raise error


for current, directories, files in os.walk(source, onerror=raise_walk_error):
    relative = Path(current).relative_to(source)
    target_dir = destination / relative
    if target_dir.is_symlink():
        raise SystemExit(f"Destination directory is a symlink: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in directories:
        if (Path(current) / name).is_symlink():
            raise SystemExit(f"Legacy upload directory is a symlink: {name}")
    for name in files:
        original = Path(current) / name
        target = target_dir / name
        if not stat.S_ISREG(original.stat(follow_symlinks=False).st_mode):
            raise SystemExit(f"Legacy upload is not a regular file: {original}")
        if target.is_symlink():
            raise SystemExit(f"Destination file is a symlink: {target}")
        if target.exists():
            if not target.is_file() or not filecmp.cmp(original, target, shallow=False):
                raise SystemExit(f"Upload conflict: {target}")
            continue
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".lavbench-upload-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                with original.open("rb") as stream:
                    shutil.copyfileobj(stream, temporary)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
        try:
            os.link(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        copied += 1
print(f"Preserved {copied} legacy upload files")
PY
  then
    echo "  ✔ Legacy uploads preserved"
  else
    echo "  [ERROR] Legacy upload migration failed; existing services were left running." >&2
    exit 1
  fi
fi

# ── Stop existing services ─────────────────────────────────────────
echo "  → Stopping existing services..."
docker compose --env-file "$DOCKER_ENV_FILE" down 2>/dev/null || true
echo ""

# ── Build images ───────────────────────────────────────────────────
echo "  → Building Docker images..."
docker compose --env-file "$DOCKER_ENV_FILE" build
echo ""

# ── Start database and cache ───────────────────────────────────────
echo "  → Starting database and cache..."
docker compose --env-file "$DOCKER_ENV_FILE" up -d db redis
echo "    Waiting for PostgreSQL..."
RETRIES=15
until docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" &>/dev/null || [ $RETRIES -eq 0 ]; do
  echo "      ... ($RETRIES retries left)"
  sleep 1
  RETRIES=$((RETRIES - 1))
done
if [ $RETRIES -eq 0 ]; then
  echo "  [ERROR] PostgreSQL did not become ready." >&2
  docker compose logs db
  exit 1
fi
echo "    ✔ PostgreSQL ready"
echo ""

# ── Start all services ─────────────────────────────────────────────
echo "  → Starting all services..."
docker compose --env-file "$DOCKER_ENV_FILE" up -d
echo ""

# ── Read URL config from .env ───────────────────────────────────────
SERVER_ADDRESS=$(grep "^SERVER_ADDRESS=" .env | tail -1 | cut -d= -f2-) || true
NGINX_PORT=$(grep "^NGINX_PORT=" .env | tail -1 | cut -d= -f2-) || true
HTTPS_PORT=$(grep "^HTTPS_PORT=" .env | tail -1 | cut -d= -f2-) || true
MAIN_SERVER_URL=$(grep "^MAIN_SERVER_URL=" .env | tail -1 | cut -d= -f2-) || true
: "${SERVER_ADDRESS:=localhost}"
if [[ "$MAIN_SERVER_URL" == https://* ]]; then
  : "${HTTPS_PORT:=443}"
  BASE_URL="https://${SERVER_ADDRESS}:${HTTPS_PORT}"
else
  : "${NGINX_PORT:=80}"
  BASE_URL="http://${SERVER_ADDRESS}:${NGINX_PORT}"
fi

# ── Done ───────────────────────────────────────────────────────────
echo "  ──────────────────────────────────────────────────────────────"
echo "    Deployment complete!"
echo "    Frontend:  ${BASE_URL}"
echo "    API:       ${BASE_URL}/api"
echo "    Logs:      docker compose logs -f"
echo "    Stop:      docker compose down"
echo "  ──────────────────────────────────────────────────────────────"
echo ""
