#!/usr/bin/env bash
# scripts/deploy-worker.sh — Build and deploy a LavBench worker from saved config.
# Called by: make deploy-worker
# Prerequisite: make setup-worker (creates worker.env)
set -euo pipefail

WORKER_IMAGE="lavbench-worker"
CONTAINER_NAME="lavbench-worker"

# ── Load config ────────────────────────────────────────────────────
echo "  → Loading worker.env..."

if [ ! -f "worker.env" ]; then
  cat <<ERR
  [ERROR] worker.env not found.

  Run 'make setup-worker' first to configure the worker,
  or copy worker.env from the server.

ERR
  exit 1
fi

set -a
source worker.env
set +a

# Also load .env for shared settings (HF_CACHE_DIR, etc.)
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

# ── Validate required settings ──────────────────────────────────────
if [ -z "${WORKER_TYPE:-}" ]; then
  echo "  [ERROR] WORKER_TYPE not set in worker.env. Re-run: make setup-worker"
  exit 1
fi

if [ -z "${WORKER_PRIVATE_KEY:-}" ]; then
  echo "  [ERROR] WORKER_PRIVATE_KEY not set. Copy worker.env from the server."
  exit 1
fi

REDIS_URL="${CELERY_BROKER_URL:-}"
if [ -z "$REDIS_URL" ]; then
  echo "  [ERROR] CELERY_BROKER_URL not set. Copy worker.env from the server."
  exit 1
fi

# ── Resolve mode ───────────────────────────────────────────────────
MODE="${WORKER_MODE:-docker}"
GPU_ID="${WORKER_GPU_ID:-}"
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-4}"

# ── Celery queue selection ─────────────────────────────────────────
INTERNAL=false
if [ "${WORKER_TYPE:-eval}" = "internal" ]; then
  INTERNAL=true
  CELERY_QUEUES="celery"
elif [ "${WORKER_TYPE:-eval}" = "both" ]; then
  CELERY_QUEUES="${GPU_ID:+gpu_queue,}cpu_queue,celery"
else
  CELERY_QUEUES="${GPU_ID:+gpu_queue,}cpu_queue"
fi

# ── Common env vars ────────────────────────────────────────────────
export CELERY_BROKER_URL="$REDIS_URL"
export CELERY_RESULT_BACKEND="$REDIS_URL"
export RUNNING_AS_WORKER="true"
export PYTHONPATH=".:backend:${PYTHONPATH:-}"
export HF_CACHE_DIR="${HF_CACHE_DIR:-$(pwd)/hf_cache}"

if [ -n "$GPU_ID" ]; then
  export CUDA_VISIBLE_DEVICES="$GPU_ID"
fi

# ═══════════════════════════════════════════════════════════════════
# DOCKER MODE
# ═══════════════════════════════════════════════════════════════════
deploy_docker() {
  echo ""
  echo "  → Deploying Docker worker... (Concurrency: $CONCURRENCY)"
  echo ""

  # ── Preflight ──────────────────────────────────────────────────
  if ! docker info &>/dev/null; then
    echo "  [ERROR] Docker daemon is not running." >&2
    exit 1
  fi

  # ── Cache-aware build ──────────────────────────────────────────
  echo "  → Checking image..."
  SOURCE_HASH=$(
    find backend/ -type f \( -name '*.py' -o -name 'Dockerfile.worker' -o -name 'requirements.txt' \) \
      -exec md5 -r {} + 2>/dev/null | md5 -r | cut -d' ' -f1
  )
  IMAGE_HASH=$(docker image inspect "$WORKER_IMAGE" \
    --format '{{.Config.Labels.source_hash}}' 2>/dev/null || echo "")

  if [ -z "$IMAGE_HASH" ] || [ "$SOURCE_HASH" != "$IMAGE_HASH" ]; then
    echo "  → Building $WORKER_IMAGE..."
    docker build \
      -t "$WORKER_IMAGE" \
      --label "source_hash=$SOURCE_HASH" \
      -f backend/Dockerfile.worker backend/
    echo "  ✔ Build complete"
  else
    echo "  → Image up-to-date, skipping build"
  fi

  # ── Remove old container ───────────────────────────────────────
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "  → Removing existing container..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi

  # ── Prepare volumes ────────────────────────────────────────────
  mkdir -p "${HF_CACHE_DIR}"
  LAVBENCH_WORKSPACE_DIR="$(pwd)/.lavbench_workspace"
  mkdir -p "$LAVBENCH_WORKSPACE_DIR"
  rm -rf "$LAVBENCH_WORKSPACE_DIR"/*

  # ── Run container ──────────────────────────────────────────────
  echo "  → Starting container..."
  docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --network host \
    -e CELERY_BROKER_URL \
    -e CELERY_RESULT_BACKEND \
    -e SECRET_KEY \
    -e WORKER_PRIVATE_KEY \
    -e CUDA_VISIBLE_DEVICES \
    -e WORKER_TYPE \
    -e HF_CACHE_DIR \
    -e LAVBENCH_WORKSPACE_DIR="${LAVBENCH_WORKSPACE_DIR}" \
    -e GPU_CORES_PER_TASK \
    -e CPU_CORES_PER_TASK \
    -e GPU_RAM_PER_TASK_GB \
    -e CPU_RAM_PER_TASK_GB \
    -e RESERVED_RAM_GB \
    -e RESERVED_CPU_CORES \
    -e RAM_CLAMP_FACTOR \
    -e RUNNING_AS_WORKER=true \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${HF_CACHE_DIR}:${HF_CACHE_DIR}" \
    -v "${LAVBENCH_WORKSPACE_DIR}:${LAVBENCH_WORKSPACE_DIR}" \
    $( [ -n "$GPU_ID" ] && echo "--gpus all" || true ) \
    "$WORKER_IMAGE" \
    celery -A tasks.celery worker --loglevel=info -Q "$CELERY_QUEUES" -c "$CONCURRENCY"

  echo ""
  echo "  ✔ Worker deployed"
  echo "    Name: ${CONTAINER_NAME}"
  echo "    Logs: docker logs ${CONTAINER_NAME} -f"
  echo "    Stop: docker stop ${CONTAINER_NAME} && docker rm ${CONTAINER_NAME}"
}

# ═══════════════════════════════════════════════════════════════════
# LOCAL MODE (micromamba)
# ═══════════════════════════════════════════════════════════════════
deploy_local() {
  echo ""
  echo "  → Deploying local worker... (Concurrency: $CONCURRENCY)"
  echo ""

  if ! command -v micromamba &>/dev/null; then
    echo "  [ERROR] micromamba required for local mode."
    exit 1
  fi

  # ── Kill existing worker ────────────────────────────────────────
  echo "  → Stopping existing worker..."
  pkill -f "celery -A tasks.celery worker" 2>/dev/null || true
  sleep 1

  # ── Micromamba ──────────────────────────────────────────────────
  eval "$(micromamba shell hook --shell bash 2>/dev/null)"
  if ! micromamba env list | grep -q "lavbench_worker"; then
    echo "  [ERROR] Environment 'lavbench_worker' not found."
    echo "          Run 'make setup-worker' and choose local mode."
    exit 1
  fi
  micromamba activate lavbench_worker
  echo "  ✔ micromamba env 'lavbench_worker'"

  # ── Dependencies ────────────────────────────────────────────────
  echo "  → Verifying dependencies..."
  pip install -q -r backend/requirements.txt
  echo "  ✔ Dependencies up to date"
  echo ""

  # ── Start Celery ────────────────────────────────────────────────
  cd backend

  if [ "$INTERNAL" = "true" ]; then
    echo "  → Internal worker"
    export INTERNAL_ONLY_WORKER="true"
    export EVALUATION_ONLY_WORKER="false"
    exec celery -A tasks.celery worker --loglevel=info -Q celery -c "$CONCURRENCY"
  elif [ -n "$GPU_ID" ]; then
    echo "  → GPU worker (GPUs: $GPU_ID)"
    export INTERNAL_ONLY_WORKER="false"
    export EVALUATION_ONLY_WORKER="true"
    exec celery -A tasks.celery worker --loglevel=info -Q gpu_queue,cpu_queue -c "$CONCURRENCY"
  else
    echo "  → CPU worker"
    export INTERNAL_ONLY_WORKER="false"
    export EVALUATION_ONLY_WORKER="true"
    exec celery -A tasks.celery worker --loglevel=info -Q cpu_queue -c "$CONCURRENCY"
  fi
}

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
case "$MODE" in
  docker) deploy_docker ;;
  local)  deploy_local  ;;
  *)
    echo "  [ERROR] Unknown WORKER_MODE='$MODE' in worker.env (expected: docker or local)"
    exit 1
    ;;
esac
