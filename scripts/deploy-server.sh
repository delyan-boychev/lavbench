#!/usr/bin/env bash
# scripts/deploy-server.sh — Deploy LavBench server with Docker Compose.
# Called by: make deploy-server
set -euo pipefail

# Clean up .env.docker on exit
cleanup() {
  rm -f .env.docker
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
REQUIRED_VARS=("SECRET_KEY" "POSTGRES_PASSWORD" "REDIS_PASSWORD" "WORKER_PUBLIC_KEY")
for var in "${REQUIRED_VARS[@]}"; do
  val=$(grep "^${var}=" .env 2>/dev/null | tail -1 | cut -d= -f2-)
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
export REDIS_PASSWORD POSTGRES_PASSWORD
grep -v -E '^(CELERY_BROKER_URL|CELERY_RESULT_BACKEND|DATABASE_URL)=' .env > .env.docker
echo "CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0" >> .env.docker
echo "CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/0" >> .env.docker
echo "DATABASE_URL=postgresql://lavbench_user:${POSTGRES_PASSWORD}@db:5432/lavbench_db" >> .env.docker
DOCKER_ENV="--env-file .env.docker"

# ── Stop existing services ─────────────────────────────────────────
echo "  → Stopping existing services..."
docker compose $DOCKER_ENV down 2>/dev/null || true
echo ""

# ── Build images ───────────────────────────────────────────────────
echo "  → Building Docker images..."
docker compose $DOCKER_ENV build
echo ""

# ── Start database and cache ───────────────────────────────────────
echo "  → Starting database and cache..."
docker compose $DOCKER_ENV up -d db redis
echo "    Waiting for PostgreSQL..."
RETRIES=15
until docker compose exec -T db pg_isready -U lavbench_user -d lavbench_db &>/dev/null || [ $RETRIES -eq 0 ]; do
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
docker compose $DOCKER_ENV up -d
echo ""

# ── Initialize database ────────────────────────────────────────────
echo "  → Initializing database schema..."
docker compose exec -T backend python -c "
from app import app, db
with app.app_context():
    db.create_all()
"
echo "    ✔ Database schema created"
rm -f .env.docker
echo ""

# ── Read URL config from .env ───────────────────────────────────────
SERVER_ADDRESS=$(grep "^SERVER_ADDRESS=" .env | tail -1 | cut -d= -f2-)
NGINX_PORT=$(grep "^NGINX_PORT=" .env | tail -1 | cut -d= -f2-)
: "${SERVER_ADDRESS:=localhost}"
: "${NGINX_PORT:=80}"
BASE_URL="http://${SERVER_ADDRESS}:${NGINX_PORT}"

# ── Done ───────────────────────────────────────────────────────────
echo "  ──────────────────────────────────────────────────────────────"
echo "    Deployment complete!"
echo "    Frontend:  ${BASE_URL}"
echo "    API:       ${BASE_URL}/api"
echo "    Logs:      docker compose logs -f"
echo "    Stop:      docker compose down"
echo "  ──────────────────────────────────────────────────────────────"
echo ""
