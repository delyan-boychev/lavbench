#!/usr/bin/env bash
# scripts/start-worker.sh — Start a LavBench remote worker.
#
# Usage:
#   Interactive:       make worker              (first-run setup prompts)
#   Docker:            make worker-docker        (uses worker.env)
#   Local micromamba:  make start-worker REDIS_URL=redis://...
#   Manual:            scripts/start-worker.sh [--docker] [options]
#
# Options:
#   --gpu, -g <GPU_ID>         Comma-separated GPU device indices
#   --concurrency, -c <N>      Worker concurrency (default: from worker.env)
#   --internal, -i             System tasks only (no evaluations)
#   --docker                   Run via Docker (no micromamba needed)
#   --help, -h                 Show this help
set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
MODE="local"
REDIS_URL=""
GPU_ID=""
CONCURRENCY_ARG=""
INTERNAL_ONLY="false"

# ── Parse arguments ─────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker)
      MODE="docker"
      shift
      ;;
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
    --help|-h)
      echo "Usage: $0 [--docker] [options]"
      echo ""
      echo "  First run creates worker.env interactively."
      echo "  Run via make targets:"
      echo "    make worker           Interactive first-run, then saved config"
      echo "    make worker-docker    Start Docker worker from worker.env"
      echo "    make start-worker     Start local micromamba worker"
      echo ""
      echo "  <REDIS_URL>           Redis broker URL (or set in worker.env)"
      echo "  --docker              Run via Docker instead of micromamba"
      echo "  --gpu, -g <GPU_ID>    GPU device(s): 0 or 0,1,2"
      echo "  --concurrency, -c <N> Worker concurrency"
      echo "  --internal, -i        Internal tasks only (backups, leaderboards)"
      echo ""
      echo "Examples:"
      echo "  $0 --docker redis://:pass@server:6379/0 -c 4"
      echo "  $0 --docker                        # interactive if no worker.env"
      exit 0
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

# ── Load worker.env if present and no explicit REDIS_URL ────────────
if [ -f "worker.env" ] && [ -z "$REDIS_URL" ]; then
  echo "  → Loading worker.env..."
  set -a
  source worker.env
  set +a
  REDIS_URL="${CELERY_BROKER_URL}"
fi

if [ -z "$REDIS_URL" ]; then
  cat <<ERR
  [ERROR] No Redis connection configured.

  First, copy worker.env from the server:
    scp user@server:~/worker.env .

  Or provide a Redis URL directly:
    $0 --docker redis://:password@server:6379/0

  Then run again:
    make worker
ERR
  exit 1
fi

# Use WORKER_GPU_ID from worker.env if GPU_ID not set via CLI
if [ -z "${GPU_ID:-}" ] && [ -n "${WORKER_GPU_ID:-}" ]; then
  GPU_ID="$WORKER_GPU_ID"
fi

# Export common worker environment
export CELERY_BROKER_URL="$REDIS_URL"
export CELERY_RESULT_BACKEND="$REDIS_URL"
export RUNNING_AS_WORKER="true"
export PYTHONPATH=".:backend:${PYTHONPATH:-}"

# Load .env extras (for HF_CACHE_DIR, etc.)
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

# Require Ed25519 private key
if [ -z "${WORKER_PRIVATE_KEY:-}" ]; then
  cat <<ERR
  [ERROR] WORKER_PRIVATE_KEY is not set.

  Copy worker.env from the server (it contains the key):
    scp user@server:~/worker.env .

  Or on the server, re-run setup to generate keys:
    make setup
ERR
  exit 1
fi

export HF_CACHE_DIR="${HF_CACHE_DIR:-$(pwd)/hf_cache}"

if [ -n "$GPU_ID" ]; then
  export WORKER_GPU_ID="$GPU_ID"
  export CUDA_VISIBLE_DEVICES="$GPU_ID"
  echo "  → GPU device: $GPU_ID"
fi

# ── Interactive first-run setup ──────────────────────────────────
TOTAL_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
GPU_DETECTED=""
if command -v nvidia-smi &>/dev/null; then
  GPU_DETECTED=$(nvidia-smi --query-gpu=index,name --format=csv,noheader 2>/dev/null || true)
fi

if [ -z "${WORKER_TYPE:-}" ]; then
  echo "  ── First-time worker setup ──"
  if [ -n "$GPU_DETECTED" ]; then
    echo "    GPUs:"
    echo "$GPU_DETECTED" | while IFS=, read -r idx name; do
      echo "      [$idx] $name"
    done
  else
    echo "    No NVIDIA GPUs detected"
  fi
  echo "    Total: $TOTAL_CORES CPU cores"
  echo ""

  # 1. Docker or local
  echo "  How should the worker run?"
  echo "    1) Docker container   (recommended — minimal setup)"
  echo "    2) Local micromamba   (for development)"
  read -p "  Choose [1]: " MODE_CHOICE
  case "${MODE_CHOICE:-1}" in
    2) WORKER_MODE="local" ;;
    *) WORKER_MODE="docker" ;;
  esac
  echo ""

  # 2. Worker type
  echo "  What type of tasks should this worker handle?"
  echo "    1) Evaluation tasks only  (CPU/GPU queues)"
  echo "    2) Internal tasks only    (system/beat tasks)"
  echo "    3) Both                   (evaluation + internal)"
  read -p "  Choose [1]: " WT_CHOICE
  case "${WT_CHOICE:-1}" in
    2) WORKER_TYPE="internal" ;;
    3) WORKER_TYPE="both" ;;
    *) WORKER_TYPE="eval" ;;
  esac

  GPU_CORES_PER_TASK=""
  CPU_CORES_PER_TASK=""
  CELERY_WORKER_CONCURRENCY=""

  if [ "$WORKER_TYPE" = "internal" ]; then
    # Internal worker: simple concurrency
    DEFAULT_CONC=$(( TOTAL_CORES / 2 > 1 ? TOTAL_CORES / 2 : 1 ))
    read -p "  Worker concurrency [$DEFAULT_CONC]: " CONC_USER
    CELERY_WORKER_CONCURRENCY="${CONC_USER:-$DEFAULT_CONC}"
    echo ""
  else
    # Eval / both with GPU detection
    if [ -n "$GPU_DETECTED" ]; then
      read -p "  GPU IDs to use (e.g., 0 or 0,1 — empty for CPU-only): " GPU_ID
      if [ -n "$GPU_ID" ]; then
        WORKER_GPU_ID="$GPU_ID"
        NUM_GPUS=$(echo "$GPU_ID" | tr ',' '\n' | wc -l | tr -d ' ')
        echo "    Total: $TOTAL_CORES CPU cores, ${NUM_GPUS} GPU(s) selected"
        DEFAULT_GPU_CORES=$(( TOTAL_CORES / NUM_GPUS / 2 * 2 ))
        [ "$DEFAULT_GPU_CORES" -lt 2 ] && DEFAULT_GPU_CORES=2
        GPU_CORES_USED=$(( NUM_GPUS * DEFAULT_GPU_CORES ))
        REMAINING=$(( TOTAL_CORES - GPU_CORES_USED ))
        DEFAULT_CPU_CORES=2

        echo ""
        echo "  CPU cores per GPU task [$DEFAULT_GPU_CORES]:"
        echo "    (even number, 1 task per GPU — ${NUM_GPUS} tasks × ${DEFAULT_GPU_CORES} cores = ${GPU_CORES_USED} cores)"
        read -p "  Cores per GPU task: " GPU_INPUT
        GPU_CORES_PER_TASK="${GPU_INPUT:-$DEFAULT_GPU_CORES}"
        GPU_CORES_USED=$(( NUM_GPUS * GPU_CORES_PER_TASK ))
        REMAINING=$(( TOTAL_CORES - GPU_CORES_USED ))

        if [ "$REMAINING" -ge "$DEFAULT_CPU_CORES" ]; then
          echo ""
          echo "  ${REMAINING} cores remaining for CPU-only tasks"
          read -p "  CPU cores per CPU task [$DEFAULT_CPU_CORES]: " CPU_INPUT
          CPU_CORES_PER_TASK="${CPU_INPUT:-$DEFAULT_CPU_CORES}"
          MAX_CPU_TASKS=$(( REMAINING / CPU_CORES_PER_TASK ))
          echo "  Max concurrent CPU tasks: $MAX_CPU_TASKS (0 = none, all spare idle)"
          read -p "  CPU task concurrency [${MAX_CPU_TASKS}]: " CPU_CONC_INPUT
          CPU_CONCURRENCY="${CPU_CONC_INPUT:-$MAX_CPU_TASKS}"
        else
          CPU_CORES_PER_TASK="$DEFAULT_CPU_CORES"
          CPU_CONCURRENCY=0
          echo "  No spare cores for CPU tasks."
        fi
        CELERY_WORKER_CONCURRENCY=$(( NUM_GPUS + CPU_CONCURRENCY ))
      fi
    fi

    # Fallback: CPU-only eval
    if [ -z "$WORKER_GPU_ID" ]; then
      echo ""
      DEFAULT_CPU_CORES=2
      read -p "  CPU cores per evaluation task [$DEFAULT_CPU_CORES]: " CPU_INPUT
      CPU_CORES_PER_TASK="${CPU_INPUT:-$DEFAULT_CPU_CORES}"
      MAX_TASKS=$(( TOTAL_CORES / CPU_CORES_PER_TASK ))
      echo "  Max concurrent tasks: $MAX_TASKS"
      read -p "  Worker concurrency [$MAX_TASKS]: " CONC_USER
      CELERY_WORKER_CONCURRENCY="${CONC_USER:-$MAX_TASKS}"
    fi
  fi

  # Print config summary
  echo ""
  echo "  ──────────────────────────────────────────────"
  echo "    Mode:       ${WORKER_MODE}"
  echo "    Type:       ${WORKER_TYPE}"
  if [ -n "${WORKER_GPU_ID:-}" ]; then
    echo "    GPU IDs:    ${WORKER_GPU_ID}"
    echo "    GPU cores:  ${GPU_CORES_PER_TASK} per task"
  fi
  if [ -n "$CPU_CORES_PER_TASK" ]; then
    echo "    CPU cores:  ${CPU_CORES_PER_TASK} per task"
  fi
  echo "    Concurrency: ${CELERY_WORKER_CONCURRENCY}"
  echo "  ──────────────────────────────────────────────"
  echo ""

  # Save to worker.env
  {
    echo ""
    echo "# Worker config — set by first-run setup"
    echo "WORKER_MODE=$WORKER_MODE"
    echo "WORKER_TYPE=$WORKER_TYPE"
    if [ -n "${WORKER_GPU_ID:-}" ]; then
      echo "WORKER_GPU_ID=$WORKER_GPU_ID"
      echo "GPU_CORES_PER_TASK=$GPU_CORES_PER_TASK"
    fi
    if [ -n "$CPU_CORES_PER_TASK" ]; then
      echo "CPU_CORES_PER_TASK=$CPU_CORES_PER_TASK"
    fi
    echo "CELERY_WORKER_CONCURRENCY=$CELERY_WORKER_CONCURRENCY"
  } >> worker.env
  echo "  ✔ Configuration saved to worker.env"
  echo ""
  unset WT_CHOICE MODE_CHOICE CONC_USER GPU_INPUT CPU_INPUT CPU_CONC_INPUT
  unset GPU_CORES_USED REMAINING MAX_TASKS MAX_CPU_TASKS DEFAULT_GPU_CORES DEFAULT_CPU_CORES DEFAULT_CONC
fi

# ── Resolve run mode ──────────────────────────────────────────────
# Priority: CLI --docker flag > saved WORKER_MODE > default "local"
if [ "$MODE" != "docker" ] && [ "${WORKER_MODE:-}" = "docker" ]; then
  MODE="docker"
fi

# Source worker.env again so all saved values are available
if [ -f "worker.env" ]; then
  set -a
  source worker.env
  set +a
fi

# Ensure GPU_ID is set from worker.env if not from CLI
if [ -z "${GPU_ID:-}" ] && [ -n "${WORKER_GPU_ID:-}" ]; then
  GPU_ID="$WORKER_GPU_ID"
  export GPU_ID
  export CUDA_VISIBLE_DEVICES="$GPU_ID"
fi

# CLI --internal overrides worker.env
if [ "$INTERNAL_ONLY" = "true" ]; then
  WORKER_TYPE="internal"
fi

# CLI --concurrency overrides worker.env
CONCURRENCY="${CONCURRENCY_ARG:-${CELERY_WORKER_CONCURRENCY:-4}}"

# ── Build Celery args (shared between docker and local) ───────────
CELERY_QUEUES=""
CELERY_EXTRA=""
if [ "$INTERNAL_ONLY" = "true" ] || [ "${WORKER_TYPE:-eval}" = "internal" ]; then
  CELERY_QUEUES="celery"
  CELERY_EXTRA="--internal"
elif [ "${WORKER_TYPE:-eval}" = "both" ]; then
  CELERY_QUEUES="${GPU_ID:+gpu_queue,}cpu_queue,celery"
else
  CELERY_QUEUES="${GPU_ID:+gpu_queue,}cpu_queue"
fi

# ── Docker mode ─────────────────────────────────────────────────────
if [ "$MODE" = "docker" ]; then
  echo "  → Starting Docker-based worker...  ($TOTAL_CORES CPU cores)"
  echo ""

  # Worker image: env var overrides default; try registry, fall back to local
  WORKER_IMAGE="${WORKER_IMAGE:-lavbench-worker}"
  if ! docker image inspect "$WORKER_IMAGE" &>/dev/null; then
    echo "  → Pulling $WORKER_IMAGE..."
    docker pull "$WORKER_IMAGE" 2>/dev/null || {
      echo "  [WARN] Could not pull $WORKER_IMAGE — will fail if not built locally"
    }
  fi

  # Build volume and env args
  VOLUME_ARGS=""
  ENV_ARGS=""

  # Docker socket (DinD — worker spawns eval sandbox containers)
  if [ -S /var/run/docker.sock ]; then
    VOLUME_ARGS="$VOLUME_ARGS -v /var/run/docker.sock:/var/run/docker.sock"
  fi

  # HF cache persistence
  mkdir -p "${HF_CACHE_DIR}"
  VOLUME_ARGS="$VOLUME_ARGS -v ${HF_CACHE_DIR}:${HF_CACHE_DIR}"

  # TLS certs (if present)
  if [ -d certs ] && [ -n "${REDIS_SSL_CA_CERTS:-}" ]; then
    VOLUME_ARGS="$VOLUME_ARGS -v $(pwd)/certs:/etc/ssl/certs/redis:ro"
    ENV_ARGS="$ENV_ARGS \
    -e REDIS_SSL_CA_CERTS \
    -e REDIS_SSL_CERTFILE \
    -e REDIS_SSL_KEYFILE \
    -e REDIS_SSL_CERT_REQS"
  fi

  docker run -d --name "lavbench-worker-$$" \
    --restart unless-stopped \
    -e CELERY_BROKER_URL \
    -e CELERY_RESULT_BACKEND \
    -e WORKER_PRIVATE_KEY \
    -e WORKER_GPU_ID \
    -e HF_CACHE_DIR \
    -e WORKER_TYPE \
    -e GPU_CORES_PER_TASK \
    -e CPU_CORES_PER_TASK \
    -e INTERNAL_ONLY_WORKER="$([ "$INTERNAL_ONLY" = "true" ] || [ "${WORKER_TYPE:-eval}" = "internal" ] && echo true || echo false)" \
    -e EVALUATION_ONLY_WORKER="$([ "$INTERNAL_ONLY" != "true" ] && [ "${WORKER_TYPE:-eval}" != "internal" ] && echo true || echo false)" \
    $ENV_ARGS \
    $VOLUME_ARGS \
    $( [ -n "${GPU_ID:-}" ] && echo "--gpus all" || echo "" ) \
    "$WORKER_IMAGE" \
    celery -A tasks.celery worker --loglevel=info -Q "$CELERY_QUEUES" -c "$CONCURRENCY"

  echo ""
  echo "  ✔ Worker started via Docker"
  echo "    Name: lavbench-worker-$$"
  echo "    Logs: docker logs lavbench-worker-$$ -f"
  echo "    Stop: docker stop lavbench-worker-$$"
  exit 0
fi

# ── Local mode (micromamba) ─────────────────────────────────────────
echo "  → Starting local worker...  ($TOTAL_CORES CPU cores)"
echo ""

if ! command -v micromamba &>/dev/null; then
  echo "  [ERROR] micromamba is required."
  echo "          Or use --docker mode: $0 --docker <URL>"
  exit 1
fi

eval "$(micromamba shell hook --shell bash)"

if ! micromamba env list | grep -q "lavbench_worker"; then
  echo "  → Creating micromamba environment 'lavbench_worker'..."
  micromamba create -n lavbench_worker python=3.12 -y -q
fi

micromamba activate lavbench_worker
echo "  ✔ micromamba env 'lavbench_worker' (Python 3.12)"

echo "  → Installing dependencies..."
pip install -q -r backend/requirements.txt
echo ""

# Change to backend directory
if [ -d "backend" ]; then
  cd backend
fi

# Export task scoping
if [ "$INTERNAL_ONLY" = "true" ] || [ "${WORKER_TYPE:-eval}" = "internal" ]; then
  export INTERNAL_ONLY_WORKER="true"
  export EVALUATION_ONLY_WORKER="false"
else
  export INTERNAL_ONLY_WORKER="false"
  export EVALUATION_ONLY_WORKER="true"
fi

# Start Celery
if [ "$INTERNAL_ONLY" = "true" ] || [ "${WORKER_TYPE:-eval}" = "internal" ]; then
  echo "  → Internal worker (Concurrency: $CONCURRENCY)"
  exec celery -A tasks.celery worker --loglevel=info -Q celery -c "$CONCURRENCY"
elif [ -n "${GPU_ID:-}" ]; then
  echo "  → GPU worker (GPUs: $GPU_ID, Concurrency: $CONCURRENCY)"
  exec celery -A tasks.celery worker --loglevel=info -Q gpu_queue,cpu_queue -c "$CONCURRENCY"
else
  echo "  → CPU worker (Concurrency: $CONCURRENCY)"
  exec celery -A tasks.celery worker --loglevel=info -Q cpu_queue -c "$CONCURRENCY"
fi
