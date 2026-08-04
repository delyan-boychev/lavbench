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

if [ -n "$GPU_ID" ]; then
    GPU_COUNT=$(echo "$GPU_ID" | tr ',' '\n' | wc -l | tr -d ' ')
else
    GPU_COUNT=0
fi
CPU_CONCURRENCY=$(( CONCURRENCY - GPU_COUNT ))
[ "$CPU_CONCURRENCY" -lt 1 ] && CPU_CONCURRENCY=1

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
  echo "  → Deploying Docker worker..."
    echo "    GPU worker:  concurrency=${GPU_COUNT} (queue: gpu_queue)"
    echo "    CPU worker:  concurrency=${CPU_CONCURRENCY} (queue: cpu_queue)"
  echo ""

  # ── Preflight ──────────────────────────────────────────────────
  if ! docker info &>/dev/null; then
    echo "  [ERROR] Docker daemon is not running." >&2
    exit 1
  fi

  # ── Build (Docker layer cache avoids unnecessary work) ──────────
  echo "  → Building $WORKER_IMAGE..."
  docker build -t "$WORKER_IMAGE" -f backend/Dockerfile.worker backend/
  echo "  ✔ Build complete"

  # ── Remove old worker containers ───────────────────────────────
  EXISTING=$(docker ps -a --filter "name=lavbench-worker" --format '{{.ID}}')
  if [ -n "$EXISTING" ]; then
    for cid in $EXISTING; do
      echo "  → Removing old worker container: $(docker inspect --format '{{.Name}}' "$cid" | sed 's|/||')"
      docker rm -f "$cid" >/dev/null 2>&1 || true
    done
  fi

  # ── Prepare volumes ────────────────────────────────────────────
  mkdir -p "${HF_CACHE_DIR}"
  LAVBENCH_WORKSPACE_DIR="$(pwd)/.lavbench_workspace"
  mkdir -p "$LAVBENCH_WORKSPACE_DIR"
  rm -rf "$LAVBENCH_WORKSPACE_DIR"/*
  TASK_IMAGES_DIR="$(pwd)/task_images"
  mkdir -p "$TASK_IMAGES_DIR"
  rm -rf "$TASK_IMAGES_DIR"/*
  # NOTE: LAVBENCH_WORKSPACE_DIR and TASK_IMAGES_DIR are mounted at the SAME
  # host path inside the container. The worker launches sandboxes through the
  # mounted Docker socket, so bind-mount sources are resolved by the HOST
  # daemon — container-internal paths like /app/task_images would fail with
  # "mounts denied".

  # ── Run container ──────────────────────────────────────────────
  echo "  → Starting container..."
  docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --network host \
    -e CELERY_BROKER_URL \
    -e CELERY_RESULT_BACKEND \
    -e SECRET_KEY \
    -e WORKER_PRIVATE_KEY \
    -e MAIN_SERVER_URL \
    -e CUDA_VISIBLE_DEVICES \
    -e WORKER_GPU_ID \
    -e WORKER_TYPE \
    -e HF_CACHE_DIR \
    -e LAVBENCH_WORKSPACE_DIR="${LAVBENCH_WORKSPACE_DIR}" \
    -e TASK_IMAGES_DIR="${TASK_IMAGES_DIR}" \
    -e GPU_CORES_PER_TASK \
    -e CPU_CORES_PER_TASK \
    -e GPU_RAM_PER_TASK_GB \
    -e CPU_RAM_PER_TASK_GB \
    -e RESERVED_RAM_GB \
    -e RESERVED_CPU_CORES \
    -e RAM_CLAMP_FACTOR \
    -e GPU_WORKER_CONCURRENCY="$GPU_COUNT" \
    -e CPU_WORKER_CONCURRENCY="$CPU_CONCURRENCY" \
    -e RUNNING_AS_WORKER=true \
    -e EVALUATION_ONLY_WORKER=true \
    $( [ -n "${REDIS_SSL_CA_CERTS:-}" ] && echo "-e REDIS_SSL_CA_CERTS=${REDIS_SSL_CA_CERTS}" || true ) \
    $( [ -n "${REDIS_SSL_CERTFILE:-}" ] && echo "-e REDIS_SSL_CERTFILE=${REDIS_SSL_CERTFILE}" || true ) \
    $( [ -n "${REDIS_SSL_KEYFILE:-}" ] && echo "-e REDIS_SSL_KEYFILE=${REDIS_SSL_KEYFILE}" || true ) \
    $( [ -n "${REDIS_SSL_CERT_REQS:-}" ] && echo "-e REDIS_SSL_CERT_REQS=${REDIS_SSL_CERT_REQS}" || true ) \
    -e PYTHONPATH=/app \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${HF_CACHE_DIR}:${HF_CACHE_DIR}" \
    -v "${LAVBENCH_WORKSPACE_DIR}:${LAVBENCH_WORKSPACE_DIR}" \
    -v "${TASK_IMAGES_DIR}:${TASK_IMAGES_DIR}" \
    $( [ -n "${REDIS_SSL_CA_CERTS:-}" ] && echo "-v $(pwd)/certs:/etc/ssl/certs/redis:ro" || true ) \
    $( [ -n "$GPU_ID" ] && echo "--gpus all" || true ) \
    "$WORKER_IMAGE"

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

  if [ -n "$GPU_ID" ]; then
    echo "  → GPU worker: concurrency=${GPU_COUNT} (queue: gpu_queue)"
    echo "  → CPU worker: concurrency=${CPU_CONCURRENCY} (queue: cpu_queue)"
    export EVALUATION_ONLY_WORKER="true"
    celery -A tasks.celery worker --loglevel=info -Q gpu_queue -c "$GPU_COUNT" &
    exec celery -A tasks.celery worker --loglevel=info -Q cpu_queue -c "$CPU_CONCURRENCY"
  else
    echo "  → CPU worker: concurrency=${CPU_CONCURRENCY} (queue: cpu_queue)"
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
