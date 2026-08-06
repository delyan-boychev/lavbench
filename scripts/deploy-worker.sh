#!/usr/bin/env bash
# scripts/deploy-worker.sh — Build and deploy a LavBench worker from saved config.
# Called by: make deploy-worker
# Prerequisite: make setup-worker (creates worker.env)
set -euo pipefail
umask 077

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
if [ -z "${WORKER_ID:-}" ]; then
  echo "  [ERROR] WORKER_ID not set. Re-run setup to create a registered worker identity."
  exit 1
fi
chmod 0600 worker.env

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
export WORKER_ROLE="eval"
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

  # ── Prepare persistent volumes ────────────────────────────────
  # Task images, HF cache and the workspace live in Docker named volumes
  # (persistent, managed by Docker) instead of host-path binds. Sandboxes
  # are seeded via put_archive/get_archive (see run_command_streaming), so
  # no path needs to be visible to the host daemon.
  docker volume create lavbench_task_images >/dev/null 2>&1 || true
  docker volume create lavbench_hf_cache >/dev/null 2>&1 || true
  docker volume create lavbench_workspace >/dev/null 2>&1 || true
  TASK_IMAGES_DIR="/var/lib/lavbench/task_images"
  LAVBENCH_WORKSPACE_DIR="/var/lib/lavbench/workspace"
  HF_CACHE_DIR="/var/lib/lavbench/hf_cache"

  # Legacy volumes are root-owned; make them writable by the worker's
  # non-root user (uid 10001) so celery can persist task images and caches.
  for vol in lavbench_task_images lavbench_hf_cache lavbench_workspace; do
    docker run --rm --user root --entrypoint chown \
      -v "$vol":/var/lib/lavbench/data "$WORKER_IMAGE" \
      -R 10001:10001 /var/lib/lavbench/data 2>/dev/null || true
  done

  # The worker drives the Docker daemon through the mounted socket, so it
  # must run in the host's docker-socket group (Linux: `stat -c %g`;
  # macOS: `stat -f %g`).
  DOCKER_SOCK_GID=$(stat -c %g /var/run/docker.sock 2>/dev/null || stat -f %g /var/run/docker.sock 2>/dev/null || true)

  # ── Run container ──────────────────────────────────────────────
  echo "  → Starting container..."
  docker run -d --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --network host \
    -e CELERY_BROKER_URL \
    -e CELERY_RESULT_BACKEND \
    -e WORKER_ENCRYPTION_KEY \
    -e WORKER_PRIVATE_KEY \
    -e WORKER_ID \
    -e MAIN_SERVER_URL \
    -e CUDA_VISIBLE_DEVICES \
    -e WORKER_GPU_ID \
    -e WORKER_GPU_IDS \
    -e WORKER_SANDBOX_STORAGE_OPT \
    -e MAX_WORKER_LOG_BYTES \
    -e MAX_COLLECT_BUFFER_BYTES \
    -e MAX_EXTRACT_MEMBER_BYTES \
    -e WORKER_TYPE \
    -e WORKER_ROLE \
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
    $( [ -n "${REDIS_SSL_CA_CERTS:-}" ] && echo "-e REDIS_SSL_CA_CERTS=${REDIS_SSL_CA_CERTS}" || true ) \
    $( [ -n "${REDIS_SSL_CERTFILE:-}" ] && echo "-e REDIS_SSL_CERTFILE=${REDIS_SSL_CERTFILE}" || true ) \
    $( [ -n "${REDIS_SSL_KEYFILE:-}" ] && echo "-e REDIS_SSL_KEYFILE=${REDIS_SSL_KEYFILE}" || true ) \
    $( [ -n "${REDIS_SSL_CERT_REQS:-}" ] && echo "-e REDIS_SSL_CERT_REQS=${REDIS_SSL_CERT_REQS}" || true ) \
    -e PYTHONPATH=/app \
    $( [ -n "$DOCKER_SOCK_GID" ] && echo "--group-add $DOCKER_SOCK_GID" || true ) \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v lavbench_task_images:/var/lib/lavbench/task_images \
    -v lavbench_hf_cache:/var/lib/lavbench/hf_cache \
    -v lavbench_workspace:/var/lib/lavbench/workspace \
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
    export WORKER_ROLE="eval"
    celery -A tasks.celery worker --loglevel=info -Q gpu_queue -c "$GPU_COUNT" &
    exec celery -A tasks.celery worker --loglevel=info -Q cpu_queue -c "$CPU_CONCURRENCY"
  else
    echo "  → CPU worker: concurrency=${CPU_CONCURRENCY} (queue: cpu_queue)"
    export WORKER_ROLE="eval"
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
