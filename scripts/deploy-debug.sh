#!/usr/bin/env bash

# scripts/deploy-debug.sh - Run LavBench locally in host debug mode.

# Terminate all background jobs in the process group on exit
cleanup() {
    echo ""
    echo "============================================="
    echo "   Stopping all services..."
    echo "============================================="
    # Remove traps to prevent loops
    trap - SIGINT SIGTERM EXIT
    # Kill process group
    kill -TERM -$$ 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

echo "============================================="
echo "   Starting LavBench Platform in Local Debug Mode  "
echo "============================================="

# 1. Prepare Micromamba Environment
echo "--> Setting up Micromamba environment..."
if ! command -v micromamba &> /dev/null; then
    echo "    [ERROR] micromamba is not installed. Please install micromamba first."
    echo "            https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html"
    exit 1
fi

eval "$(micromamba shell hook --shell bash)"

if ! micromamba env list | grep -q "lavbench_backend"; then
    echo "    Creating micromamba environment 'lavbench_backend' with Python 3.10..."
    micromamba create -n lavbench_backend python=3.12 -y
fi

echo "--> Activating micromamba environment 'lavbench_backend'..."
micromamba activate lavbench_backend

echo "--> Installing Python dependencies..."
pip install -r backend/requirements.txt -q
echo "    Python packages verified."

# 2. Ensure PostgreSQL is active (Fallback to Docker if not native)
echo "--> Checking PostgreSQL port 5432..."
if ! nc -z localhost 5432 >/dev/null 2>&1; then
    echo "    PostgreSQL is not running natively on port 5432."
    if command -v docker >/dev/null 2>&1; then
        echo "    Starting PostgreSQL database container via docker-compose..."
        docker-compose up -d db
        echo "    Waiting for PostgreSQL to start..."
        sleep 5
    else
        echo "    [ERROR] PostgreSQL not found on 5432 and Docker is not installed."
        echo "            Please install or start PostgreSQL."
        exit 1
    fi
else
    echo "    PostgreSQL is online."
fi

# 3. Ensure Redis is active (Fallback to Docker if not native)
echo "--> Checking Redis port 6379..."
if ! nc -z localhost 6379 >/dev/null 2>&1; then
    echo "    Redis is not running natively on port 6379."
    if command -v docker >/dev/null 2>&1; then
        echo "    Starting Redis broker container via docker-compose..."
        docker-compose up -d redis
        echo "    Waiting for Redis to start..."
        sleep 2
    else
        echo "    [ERROR] Redis not found on 6379 and Docker is not installed."
        echo "            Please install or start Redis."
        exit 1
    fi
else
    echo "    Redis broker is online."
fi

# 4. Create database tables
echo "--> Initializing database schema..."
cd backend
python3 -c "
from app import app, db
with app.app_context():
    db.create_all()
" && echo "    Database tables verified."
cd ..

# 5. Start Flask API server
echo "--> Starting Flask API Server..."
cd backend
    python3 app.py &
cd ..
sleep 2

# 6. Start Celery Worker (restricted to system tasks queue, low concurrency default to save resource overhead)
echo "--> Starting Celery Worker..."
cd backend
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-2}"
INTERNAL_ONLY_WORKER="true" celery -A tasks.celery worker --loglevel=info -c "$CONCURRENCY" -Q celery > celery.log 2>&1 &
cd ..
echo "    Celery running. Logs redirected to backend/celery.log"

# 7. Start Celery Beat (watchdog scheduler)
echo "--> Starting Celery Beat..."
cd backend
celery -A tasks.celery beat --loglevel=info > celery_beat.log 2>&1 &
cd ..
echo "    Celery Beat running. Logs redirected to backend/celery_beat.log"

# 8. Start React Dev Server
echo "--> Starting React Front-end..."
cd frontend
npm run dev &
cd ..

echo "============================================="
echo "   All services are launching!"
echo "   - Backend API: http://localhost:5001/api"
echo "   - Frontend UI: Check terminal output for Vite port (typically http://localhost:5173)"
echo "   - Celery Log: backend/celery.log"
echo "   Press Ctrl+C to terminate all services."
echo "============================================="

# Keep script running to maintain background jobs
while true; do
    sleep 1
done
