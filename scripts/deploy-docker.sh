#!/usr/bin/env bash

# scripts/deploy-docker.sh - Run LavBench fully in Docker Compose.

# Exit on error
set -e

echo "============================================="
echo "   Deploying LavBench Platform in Docker Compose   "
echo "============================================="

# 1. Clean up existing containers
echo "--> Stopping existing containers..."
docker-compose down

# 2. Build images
echo "--> Rebuilding docker images..."
docker-compose build

# 3. Start database and cache broker first
echo "--> Starting database (db) and broker (redis)..."
docker-compose up -d db redis

# 4. Wait for PostgreSQL container to become ready
echo "--> Waiting for PostgreSQL to initialize..."
RETRIES=15
until docker-compose exec -T db pg_isready -U lavbench_user -d lavbench_db >/dev/null 2>&1 || [ $RETRIES -eq 0 ]; do
    echo "    Waiting for database connection... ($RETRIES retries left)"
    sleep 1
    RETRIES=$((RETRIES - 1))
done

if [ $RETRIES -eq 0 ]; then
    echo "    [ERROR] PostgreSQL did not become ready in time."
    docker-compose logs db
    exit 1
fi
echo "    PostgreSQL is online and ready."

# 5. Start backend, worker, and frontend
echo "--> Starting backend, worker, and frontend..."
docker-compose up -d

# 6. Initialize database schema and run seed scripts
echo "--> Syncing and seeding database inside the backend container..."
docker-compose exec -T backend python -c "
from app import app, db, seed_database
with app.app_context():
    db.create_all()
    seed_database()
"
echo "    Database schema created and seeded successfully."

echo "============================================="
echo "   Deployment Successful!"
echo "   - Frontend UI:  http://localhost"
echo "   - Backend API:  http://localhost:5001/api"
echo "   - Logs command: docker-compose logs -f"
echo "   - Stop command: docker-compose down"
echo "============================================="
