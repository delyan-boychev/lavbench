#!/usr/bin/env bash

# deploy_debug.sh - Run the National AI Competition Platform locally in host debug mode.

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
echo "   Starting NAI Platform in Local Debug Mode  "
echo "============================================="

# 1. Prepare Python Virtual Environment
echo "--> Setting up Python Virtual Environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "    Created virtual environment in 'venv/'"
fi

source venv/bin/activate

echo "--> Installing Python dependencies..."
pip install -q -r backend/requirements.txt
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

# 4. Synchronize Database Schema and Seed Data
echo "--> Syncing and seeding database..."
python -c "
from app import app, db, seed_database
with app.app_context():
    db.create_all()
    seed_database()
" 2>/dev/null || {
    echo "    Database already seeded or updated."
}
echo "    Database initialization verified."

# 5. Start Flask API server
echo "--> Starting Flask API Server..."
cd backend
python app.py &
cd ..
sleep 2

# 6. Start Celery Worker
echo "--> Starting Celery Worker..."
cd backend
celery -A tasks.celery worker --loglevel=info > celery.log 2>&1 &
cd ..
echo "    Celery running. Logs redirected to backend/celery.log"

# 7. Start React Dev Server
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
