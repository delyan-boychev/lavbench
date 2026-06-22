#!/usr/bin/env bash
# scripts/start-worker.sh
# Decoupled Startup Script for Remote Celery GPU/CPU Workers
# Usage: make start-worker REDIS_URL=redis://... [GPU_ID=0]
# Example: make start-worker REDIS_URL=redis://worker_user:secure_password@shared-redis:6379/0 GPU_ID=0

set -euo pipefail

if [ -z "$1" ]; then
    echo "Usage: $0 <REDIS_URL> [GPU_ID]"
    echo "Example: $0 redis://worker_user:secure_password@shared-redis-host:6379/0 0"
    exit 1
fi

export CELERY_BROKER_URL="$1"
export CELERY_RESULT_BACKEND="$1"
export RUNNING_AS_WORKER="true"
export PYTHONPATH=".:backend:${PYTHONPATH:-}"

# Load server callback configurations from .env if present
if [ -f ".env" ]; then
    echo "--> Loading variables from local .env file..."
    set -a
    source .env
    set +a
fi

export HF_CACHE_DIR="${HF_CACHE_DIR:-/app/hf_cache}"

if [ ! -z "$2" ]; then
    export WORKER_GPU_ID="$2"
    export CUDA_VISIBLE_DEVICES="$2"
    echo "--> Configuring worker for GPU device: $2"
fi

# 1. Micromamba environment setup (required)
if ! command -v micromamba &> /dev/null; then
    echo "[ERROR] micromamba is required. Install it first:"
    echo "        https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html"
    exit 1
fi

echo "--> Micromamba detected. Initializing shell hook..."
eval "$(micromamba shell hook --shell bash)"

if ! micromamba env list | grep -q "lavbench_worker"; then
    echo "--> Creating micromamba environment 'lavbench_worker' with Python 3.10..."
    micromamba create -n lavbench_worker python=3.10 -y
fi

echo "--> Activating micromamba environment 'lavbench_worker'..."
micromamba activate lavbench_worker
echo "--> Installing pip dependencies..."
pip install -r backend/requirements.txt -q

# Ensure we run from backend directory
if [ -d "backend" ]; then
    cd backend
fi

echo "--> Starting decoupled remote Celery Worker node..."
echo "    Broker: $CELERY_BROKER_URL"
echo "    Main Server Callback URL: ${MAIN_SERVER_URL:-http://localhost:5001}"
echo "=========================================================================="

# Select queue depending on GPU availability
if [ ! -z "${WORKER_GPU_ID:-}" ]; then
    celery -A tasks.celery worker --loglevel=info -Q gpu_queue
else
    celery -A tasks.celery worker --loglevel=info -Q celery
fi
