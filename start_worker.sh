#!/bin/bash
# start_worker.sh
# Decoupled Startup Script for Remote Celery GPU/CPU Workers
# Usage: ./start_worker.sh <REDIS_URL> [GPU_ID]
# Example: ./start_worker.sh redis://worker_user:secure_password@shared-redis:6379/0 0

if [ -z "$1" ]; then
    echo "Usage: $0 <REDIS_URL> [GPU_ID]"
    echo "Example: $0 redis://worker_user:secure_password@shared-redis-host:6379/0 0"
    exit 1
fi

export CELERY_BROKER_URL="$1"
export CELERY_RESULT_BACKEND="$1"
export RUNNING_AS_WORKER="true" # Enforce database-free decoupled worker execution
export PYTHONPATH=".:backend:$PYTHONPATH"

# Load server callback configurations from .env if present
if [ -f ".env" ]; then
    echo "--> Loading variables from local .env file..."
    # Export vars, ignoring comments
    export $(grep -v '^#' .env | xargs)
fi

export HF_CACHE_DIR="${HF_CACHE_DIR:-/app/hf_cache}"

if [ ! -z "$2" ]; then
    export WORKER_GPU_ID="$2"
    export CUDA_VISIBLE_DEVICES="$2"
    echo "--> Configuring worker for GPU device: $2"
fi

# 1. Check for Micromamba/Conda environment setup
if command -v micromamba &> /dev/null; then
    echo "--> Micromamba detected. Initializing shell hook..."
    eval "$(micromamba shell hook --shell bash)"
    
    # Check if 'lavbench_worker' environment exists, otherwise create it
    if ! micromamba env list | grep -q "lavbench_worker"; then
        echo "--> Creating micromamba environment 'lavbench_worker' with Python 3.10..."
        micromamba create -n lavbench_worker python=3.10 -y
        micromamba activate lavbench_worker
        echo "--> Installing pip dependencies..."
        pip install -r backend/requirements.txt
    else
        echo "--> Activating micromamba environment 'lavbench_worker'..."
        micromamba activate lavbench_worker
    fi
# 2. Fallback to standard virtualenv
elif [ -d "venv" ]; then
    echo "--> Activating virtualenv 'venv'..."
    source venv/bin/activate
elif [ -d "../venv" ]; then
    echo "--> Activating virtualenv '../venv'..."
    source ../venv/bin/activate
else
    echo "--> [WARNING] No micromamba or virtualenv found. Running in global system Python..."
fi

# Ensure we run from backend directory
if [ -d "backend" ]; then
    cd backend
fi

echo "--> Starting decoupled remote Celery Worker node..."
echo "    Broker: $CELERY_BROKER_URL"
echo "    Main Server Callback URL: ${MAIN_SERVER_URL:-http://localhost:5001}"
echo "=========================================================================="

# Select queue depending on GPU availability
if [ ! -z "$WORKER_GPU_ID" ]; then
    celery -A tasks.celery worker --loglevel=info -Q gpu_queue
else
    celery -A tasks.celery worker --loglevel=info -Q celery
fi
