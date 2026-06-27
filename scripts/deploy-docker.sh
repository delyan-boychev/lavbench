#!/usr/bin/env bash
# scripts/deploy-docker.sh — Deploy LavBench with Docker Compose.
set -euo pipefail

SKIP_BUILD=false
for arg in "$@"; do
  case "$arg" in
    --skip-build|--no-build)
      SKIP_BUILD=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--skip-build]"
      echo "  --skip-build  Skip rebuilding images (faster restarts)"
      exit 0
      ;;
  esac
done

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║  Deploying LavBench with Docker Compose        ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

# ── Preflight: Docker daemon ───────────────────────────────────────
if ! docker info &>/dev/null; then
  echo "  [ERROR] Docker daemon is not running." >&2
  echo "          Start Docker Desktop or run: dockerd &" >&2
  exit 1
fi
echo "  ✔ Docker daemon running"

# ── Preflight: .env exists with required vars ──────────────────────
if [ ! -f ".env" ]; then
  echo "  [ERROR] .env not found. Run 'make setup' first." >&2
  exit 1
fi
REQUIRED_VARS=("SECRET_KEY" "POSTGRES_PASSWORD" "REDIS_PASSWORD" "WORKER_PUBLIC_KEY")
for var in "${REQUIRED_VARS[@]}"; do
  val=$(grep "^${var}=" .env 2>/dev/null | tail -1 | cut -d= -f2-)
  if [ -z "$val" ]; then
    echo "  [ERROR] ${var} is not set in .env. Run 'make setup' first." >&2
    exit 1
  fi
done
echo "  ✔ .env configured (all required keys present)"
echo ""

# ── Unset localhost URLs so docker-compose defaults kick in ────────
# docker-compose.yml uses service names (redis, db) when .env vars are absent
unset CELERY_BROKER_URL
unset CELERY_RESULT_BACKEND
unset DATABASE_URL

# ── Stop existing containers ───────────────────────────────────────
echo "  → Stopping existing containers..."
docker compose down 2>/dev/null || true
echo ""

# ── Build images ───────────────────────────────────────────────────
if [ "$SKIP_BUILD" = true ]; then
  echo "  → Skipping build (--skip-build)"
else
  echo "  → Building Docker images..."
  docker compose build
fi
echo ""

# ── Start database and cache ───────────────────────────────────────
echo "  → Starting database and cache..."
docker compose up -d db redis
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
docker compose up -d
echo ""

# ── Initialize database ────────────────────────────────────────────
echo "  → Initializing database schema..."
docker compose exec -T backend python -c "
from app import app, db, seed_database
with app.app_context():
    db.create_all()
    seed_database()
"
echo "    ✔ Database schema created and seeded"
echo ""

# ── Done ───────────────────────────────────────────────────────────
echo "  ──────────────────────────────────────────────────────────────"
echo "    Deployment complete!"
echo "    Frontend:  http://localhost"
echo "    API:       http://localhost:5001/api"
echo "    Logs:      docker compose logs -f"
echo "    Stop:      docker compose down"
echo "  ──────────────────────────────────────────────────────────────"
echo ""
