#!/usr/bin/env bash
# scripts/deploy-debug.sh — Run LavBench locally in debug mode.
set -euo pipefail

# Trap for clean shutdown
cleanup() {
  echo ""
  echo "  Stopping all services..."
  trap - SIGINT SIGTERM EXIT
  kill -TERM -$$ 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║  Starting LavBench in Local Debug Mode         ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

# ── Preflight: .env ────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "  [ERROR] .env not found. Run 'make server' first." >&2
  exit 1
fi
REQUIRED_VARS=("SECRET_KEY" "POSTGRES_PASSWORD" "REDIS_PASSWORD" "DATABASE_URL" "CELERY_BROKER_URL")
for var in "${REQUIRED_VARS[@]}"; do
  val=$(grep "^${var}=" .env 2>/dev/null | tail -1 | cut -d= -f2-)
  if [ -z "$val" ]; then
    echo "  [ERROR] ${var} is not set in .env. Run 'make server' first." >&2
    exit 1
  fi
done
echo "  ✔ .env configured"
echo ""

# ── Micromamba ─────────────────────────────────────────────────────
if ! command -v micromamba &>/dev/null; then
  echo "  [ERROR] micromamba is required."
  echo "          Install from: https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html"
  exit 1
fi

eval "$(micromamba shell hook --shell bash)"
if ! micromamba env list | grep -q "lavbench_backend"; then
  echo "  → Creating micromamba environment 'lavbench_backend'..."
  micromamba create -n lavbench_backend python=3.12 -y -q
fi
micromamba activate lavbench_backend
echo "  ✔ micromamba env 'lavbench_backend' (Python 3.12)"

echo "  → Verifying pip dependencies..."
pip install -q -r backend/requirements.txt -r backend/dev-requirements.txt
echo "  ✔ Dependencies up to date"
echo ""

# ── Frontend check ─────────────────────────────────────────────────
if [ ! -d "frontend/node_modules" ]; then
  echo "  → Installing frontend dependencies..."
  (cd frontend && npm ci --silent 2>/dev/null || npm ci)
fi
echo "  ✔ Frontend dependencies installed"
echo ""

# ── PostgreSQL via Docker ──────────────────────────────────────────
echo "  → Checking PostgreSQL..."
# Start container only if not already running for debug mode
if ! docker ps --format '{{.Names}}' | grep -q "^lavbench_db$"; then
  echo "    Starting PostgreSQL via Docker..."
  docker compose up -d db
  RETRIES=15
  until docker compose exec -T db pg_isready -U lavbench_user -d lavbench_db &>/dev/null || [ $RETRIES -eq 0 ]; do
    sleep 1
    RETRIES=$((RETRIES - 1))
  done
  if [ $RETRIES -eq 0 ]; then
    echo "  [ERROR] PostgreSQL did not become ready." >&2
    exit 1
  fi
fi
echo "  ✔ PostgreSQL ready"
echo ""

# ── Redis via Docker ───────────────────────────────────────────────
echo "  → Checking Redis..."
if ! docker ps --format '{{.Names}}' | grep -q "^lavbench_redis$"; then
  echo "    Starting Redis via Docker..."
  docker compose up -d redis
  sleep 2
fi
echo "  ✔ Redis ready"
echo ""

# ── Database schema ────────────────────────────────────────────────
echo "  → Initializing database schema..."
cd backend
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
" && echo "  ✔ Database schema initialized"
cd ..
echo ""

# ── Start Flask ────────────────────────────────────────────────────
echo "  → Starting Flask API server..."
cd backend
python3 app.py &
cd ..
sleep 2
echo ""

# ── Start Celery worker ────────────────────────────────────────────
echo "  → Starting Celery worker..."
cd backend
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-2}"
INTERNAL_ONLY_WORKER="true" celery -A tasks.celery worker --loglevel=info -c "$CONCURRENCY" -Q celery > celery.log 2>&1 &
cd ..
echo "    Logs: backend/celery.log"
echo ""

# ── Start Celery beat ──────────────────────────────────────────────
echo "  → Starting Celery beat..."
cd backend
celery -A tasks.celery beat --loglevel=info > celery_beat.log 2>&1 &
cd ..
echo "    Logs: backend/celery_beat.log"
echo ""

# ── Start frontend ─────────────────────────────────────────────────
echo "  → Starting React frontend..."
cd frontend
npm run dev &
cd ..
echo ""

# ── Done ───────────────────────────────────────────────────────────
echo "  ──────────────────────────────────────────────────────────────"
echo "    All services launching!"
echo "    API:       http://localhost/api"
echo "    Frontend:  http://localhost:5173"
echo "    Ctrl+C to stop all services"
echo "  ──────────────────────────────────────────────────────────────"
echo ""

while true; do
  sleep 1
done
