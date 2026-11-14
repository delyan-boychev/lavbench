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

# ── Preflight: Docker Compose 2.24+ (optional env_file entries) ──────
COMPOSE_VERSION=$(docker compose version --short 2>/dev/null | sed 's/^v//') || true
if [ -z "$COMPOSE_VERSION" ] \
  || [ "$(printf '%s\n' 2.24.0 "$COMPOSE_VERSION" | sort -V | head -1)" != "2.24.0" ]; then
  echo "  [ERROR] Docker Compose 2.24 or later is required (found: ${COMPOSE_VERSION:-none})." >&2
  exit 1
fi
echo "  ✔ Docker Compose ${COMPOSE_VERSION}"

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
echo "DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}" >> "$DOCKER_ENV_FILE"

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
