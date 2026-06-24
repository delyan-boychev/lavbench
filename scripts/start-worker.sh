#!/usr/bin/env bash
# scripts/start-worker.sh
# Decoupled Startup Script for Remote Celery GPU/CPU Workers
# Usage: scripts/start-worker.sh <REDIS_URL> [options]
# Example: scripts/start-worker.sh redis://localhost:6379/0 --gpu 0 --concurrency 2

set -euo pipefail

# Parse command-line parameters
REDIS_URL=""
GPU_ID=""
CONCURRENCY_ARG=""
INTERNAL_ONLY="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --concurrency|-c)
            CONCURRENCY_ARG="$2"
            shift 2
            ;;
        --internal|-i)
            INTERNAL_ONLY="true"
            shift
            ;;
        --gpu|-g)
            GPU_ID="$2"
            shift 2
            ;;
        *)
            if [ -z "$REDIS_URL" ]; then
                REDIS_URL="$1"
                shift
            elif [ -z "$GPU_ID" ]; then
                GPU_ID="$1"
                shift
            else
                echo "Unknown argument: $1"
                exit 1
            fi
            ;;
    esac
done

if [ -z "$REDIS_URL" ]; then
    echo "Usage: $0 <REDIS_URL> [options]"
    echo "Options:"
    echo "  --gpu, -g <GPU_ID>         Configure worker for specific GPU device(s)"
    echo "  --concurrency, -c <N>      Number of concurrent worker processes"
    echo "  --internal, -i             Run worker for internal tasks only (no evaluations)"
    exit 1
fi

export CELERY_BROKER_URL="$REDIS_URL"
export CELERY_RESULT_BACKEND="$REDIS_URL"
export RUNNING_AS_WORKER="true"
export PYTHONPATH=".:backend:${PYTHONPATH:-}"

# Load server callback configurations from .env if present
if [ -f ".env" ]; then
    echo "--> Loading variables from local .env file..."
    set -a
    source .env
    set +a
fi

# Require Ed25519 private key for worker authentication
if [ -z "${WORKER_PRIVATE_KEY:-}" ]; then
    echo "FATAL: WORKER_PRIVATE_KEY is not set in .env"
    echo "  Generate a keypair on the server and copy WORKER_PRIVATE_KEY to the worker's .env"
    exit 1
fi

export HF_CACHE_DIR="${HF_CACHE_DIR:-/app/hf_cache}"

if [ ! -z "$GPU_ID" ]; then
    export WORKER_GPU_ID="$GPU_ID"
    export CUDA_VISIBLE_DEVICES="$GPU_ID"
    echo "--> Configuring worker for GPU device: $GPU_ID"
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

# Determine CPU cores dynamically
NUM_CORES=$(python3 -c "import os; print(os.cpu_count() or 1)")
NUM_GPUS=0

if [ ! -z "${WORKER_GPU_ID:-}" ]; then
    NUM_GPUS=$(python3 -c "gpu_id = '${WORKER_GPU_ID}'; print(len([g for g in gpu_id.split(',') if g.strip()]))")
fi

# Determine worker concurrency (respect manual override if set)
if [ ! -z "${CONCURRENCY_ARG:-}" ]; then
    CONCURRENCY="$CONCURRENCY_ARG"
    echo "--> Using manual worker concurrency override: $CONCURRENCY"
else
    if [ ! -z "${WORKER_GPU_ID:-}" ]; then
        # Concurrency formula: max(1, NUM_GPUS, NUM_CORES / 2)
        HALF_CORES=$((NUM_CORES / 2))
        CONCURRENCY=$HALF_CORES
        if [ "$CONCURRENCY" -lt "$NUM_GPUS" ]; then
            CONCURRENCY=$NUM_GPUS
        fi
        if [ "$CONCURRENCY" -lt 1 ]; then
            CONCURRENCY=1
        fi
    else
        # Concurrency formula: max(1, NUM_CORES / 2)
        CONCURRENCY=$((NUM_CORES / 2))
        if [ "$CONCURRENCY" -lt 1 ]; then
            CONCURRENCY=1
        fi
    fi
fi

# Export task scoping variables based on internal_only parameter
if [ "$INTERNAL_ONLY" = "true" ]; then
    export INTERNAL_ONLY_WORKER="true"
    export EVALUATION_ONLY_WORKER="false"
else
    export INTERNAL_ONLY_WORKER="false"
    export EVALUATION_ONLY_WORKER="true"
fi

# Start the Celery worker
if [ "$INTERNAL_ONLY" = "true" ]; then
    echo "--> Launching internal task worker (Cores: $NUM_CORES, Concurrency: $CONCURRENCY)..."
    celery -A tasks.celery worker --loglevel=info -Q celery -c "$CONCURRENCY"
elif [ ! -z "${WORKER_GPU_ID:-}" ]; then
    echo "--> Launching GPU evaluation worker (GPUs: $NUM_GPUS, Cores: $NUM_CORES, Concurrency: $CONCURRENCY)..."
    celery -A tasks.celery worker --loglevel=info -Q gpu_queue,cpu_queue -c "$CONCURRENCY"
else
    echo "--> Launching CPU evaluation worker (Cores: $NUM_CORES, Concurrency: $CONCURRENCY)..."
    celery -A tasks.celery worker --loglevel=info -Q cpu_queue -c "$CONCURRENCY"
fi
