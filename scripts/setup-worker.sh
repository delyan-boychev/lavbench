#!/usr/bin/env bash
# scripts/setup-worker.sh — Interactive worker environment & configuration.
# Called by: make setup-worker
# Checks prerequisites, sets up runtime environment, saves config to worker.env.
set -euo pipefail

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║           LavBench Worker Setup               ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

echo "  [1/2] Checking prerequisites..."

PREREQ_OK=true

if command -v micromamba &>/dev/null; then
  echo "    ✔ micromamba"
else
  echo "    ✘ micromamba not found (optional — needed for local mode)"
fi

if command -v docker &>/dev/null; then
  echo "    ✔ docker"
  if docker info &>/dev/null; then
    echo "    ✔ docker daemon"
  else
    # Not fatal — user may choose local mode or start Docker later
    echo "    ⚠ docker daemon not running"
  fi
else
  echo "    ⚠ docker not found (optional — needed for Docker mode)"
fi

if command -v python3 &>/dev/null; then
  echo "    ✔ python3 ($(python3 --version 2>&1 | head -1))"
else
  echo "    ✘ python3 — install Python 3.12+"
  PREREQ_OK=false
fi

if [ "$PREREQ_OK" = false ]; then
  echo ""
  echo "  [ERROR] Install missing prerequisites and re-run: make setup-worker"
  exit 1
fi
echo ""

# ── Validation helpers ──────────────────────────────────────────────
validate_positive_int() {
  local val="$1" name="$2"
  if ! [[ "$val" =~ ^[1-9][0-9]*$ ]]; then
    echo "  [ERROR] $name must be a positive integer (got: '$val')" >&2
    return 1
  fi
}

validate_even_int() {
  local val="$1"
  if [ $(( val % 2 )) -ne 0 ]; then
    echo "  [ERROR] CPU cores per task must be an even number (got: $val)" >&2
    return 1
  fi
}

validate_gpu_ids() {
  local input="$1" max_idx="$2"
  local IFS=',' seen="" idx
  for idx in $input; do
    if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
      echo "  [ERROR] GPU index '$idx' is not a valid number" >&2
      return 1
    fi
    if [ "$idx" -gt "$max_idx" ]; then
      echo "  [ERROR] GPU index $idx exceeds available max ($max_idx)" >&2
      return 1
    fi
    if [[ ",$seen," == *",$idx,"* ]]; then
      echo "  [ERROR] Duplicate GPU index: $idx" >&2
      return 1
    fi
    seen="${seen:+$seen,}$idx"
  done
}

# ── Detect system resources ─────────────────────────────────────────
TOTAL_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

TOTAL_RAM_GB=8
if [[ "$OSTYPE" == "linux-gnu"* ]] && [ -f /proc/meminfo ]; then
  mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
  [ "$mem_kb" -gt 0 ] && TOTAL_RAM_GB=$(( mem_kb / 1024 / 1024 ))
elif [[ "$OSTYPE" == "darwin"* ]]; then
  mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  [ "$mem_bytes" -gt 0 ] && TOTAL_RAM_GB=$(( mem_bytes / 1024 / 1024 / 1024 ))
fi

GPU_DETECTED=""
GPU_DETECTED_DISPLAY=""
GPU_COUNT=0
if command -v nvidia-smi &>/dev/null; then
  GPU_DETECTED=$(nvidia-smi --query-gpu=index,name --format=csv,noheader 2>/dev/null || true)
  if [ -n "$GPU_DETECTED" ]; then
    GPU_COUNT=$(echo "$GPU_DETECTED" | wc -l | tr -d ' ')
    GPU_DETECTED_DISPLAY=$(echo "$GPU_DETECTED" | LC_ALL=C awk -F, '
{
  name = $2
  gsub(/^ /, "", name)
  if (!(name in seen)) {
    order[++oc] = name
    seen[name] = 1
  }
  indices[name] = indices[name] ? indices[name] "," $1 : $1
  count[name]++
}
END {
  for (oi = 1; oi <= oc; oi++) {
    name = order[oi]
    n = split(indices[name], arr, ",")
    range_str = arr[1]
    rlen = 1
    for (i = 2; i <= n; i++) {
      if (arr[i] == arr[i-1] + 1) {
        rlen++
        if (i == n) range_str = range_str "-" arr[i]
      } else {
        if (rlen > 1) range_str = range_str "-" arr[i-1]
        range_str = range_str ", " arr[i]
        rlen = 1
      }
    }
    print count[name] " x " name "  [indices: " range_str "]"
  }
}')
  fi
fi

RESERVED_CORES=1
RESERVED_RAM=4

# ── Interactive configuration ─────────────────────────────────────
if [ -f "worker.env" ]; then
  echo "  worker.env already exists. Re-run to reconfigure."
  echo "  Delete it first: rm worker.env"
  exit 0
fi

CONFIG_OK=false
while [ "$CONFIG_OK" = "false" ]; do
  unset WORKER_MODE WORKER_TYPE WORKER_GPU_ID GPU_CORES_PER_TASK CPU_CORES_PER_TASK
  unset GPU_RAM_PER_TASK_GB CPU_RAM_PER_TASK_GB CELERY_WORKER_CONCURRENCY
  unset GPU_ID NUM_GPUS GPU_COUNT_VAL CPU_COUNT_VAL

  echo "  ── Worker parameter setup ──"
  if [ -n "$GPU_DETECTED_DISPLAY" ]; then
    echo "    ${GPU_COUNT} × NVIDIA GPUs detected:"
    echo "$GPU_DETECTED_DISPLAY" | while IFS= read -r line; do
      echo "      ${line}"
    done
  else
    echo "    No NVIDIA GPUs detected"
  fi
  echo "    System: ${TOTAL_CORES} CPU cores, ${TOTAL_RAM_GB} GB RAM"
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

  # ── Set up runtime environment ─────────────────────────────────-
  if [ "$WORKER_MODE" = "local" ]; then
    if ! command -v micromamba &>/dev/null; then
      echo "  [ERROR] micromamba required for local mode."
      exit 1
    fi
    echo "  → Setting up local environment..."
    eval "$(micromamba shell hook --shell bash 2>/dev/null)"
    if ! micromamba env list | grep -q "lavbench_worker"; then
      echo "    Creating environment 'lavbench_worker'..."
      micromamba create -n lavbench_worker python=3.12 -y -q
    fi
    micromamba activate lavbench_worker
    echo "    ✔ micromamba env 'lavbench_worker'"
    pip install -q -r backend/requirements.txt
    echo "    ✔ Dependencies installed"
    echo ""
  elif [ "$WORKER_MODE" = "docker" ]; then
    if ! docker info &>/dev/null; then
      echo "  [ERROR] Docker daemon not running — required for Docker mode."
      exit 1
    fi
    echo "  ✔ Docker available"
    echo ""
  fi

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
  GPU_RAM_PER_TASK_GB=""
  CPU_RAM_PER_TASK_GB=""
  CELERY_WORKER_CONCURRENCY=""
  GPU_COUNT_VAL=0
  CPU_COUNT_VAL=0
  CORES_AVAILABLE=$(( TOTAL_CORES - RESERVED_CORES ))
  RAM_AVAILABLE=$(( TOTAL_RAM_GB - RESERVED_RAM ))

  if [ "$WORKER_TYPE" = "internal" ]; then
    DEFAULT_CONC=$(( TOTAL_CORES / 2 > 1 ? TOTAL_CORES / 2 : 1 ))
    read -p "  Worker concurrency [$DEFAULT_CONC]: " CONC_USER
    CELERY_WORKER_CONCURRENCY="${CONC_USER:-$DEFAULT_CONC}"
    echo ""
  else
    if [ -n "$GPU_DETECTED" ]; then
      GPU_MAX_IDX=$(( GPU_COUNT - 1 ))
      while true; do
        read -p "  GPU IDs to use (e.g., 0 or 0,1 — empty for CPU-only): " GPU_ID
        if [ -z "$GPU_ID" ]; then
          break
        fi
        if validate_gpu_ids "$GPU_ID" "$GPU_MAX_IDX"; then
          break
        fi
      done
      if [ -n "$GPU_ID" ]; then
        WORKER_GPU_ID="$GPU_ID"
        NUM_GPUS=$(echo "$GPU_ID" | tr ',' '\n' | wc -l | tr -d ' ')
        echo "    ${TOTAL_CORES} CPU cores, ${TOTAL_RAM_GB} GB RAM, ${NUM_GPUS} GPU(s) selected"
        DEFAULT_GPU_CORES=$(( CORES_AVAILABLE / NUM_GPUS / 2 * 2 ))
        [ "$DEFAULT_GPU_CORES" -lt 2 ] && DEFAULT_GPU_CORES=2
        echo "  CPU cores per GPU task [$DEFAULT_GPU_CORES]:"
        echo "    (${NUM_GPUS} tasks × ${DEFAULT_GPU_CORES} cores = $(( NUM_GPUS * DEFAULT_GPU_CORES )) cores)"
        while true; do
          read -p "  Cores per GPU task: " GPU_INPUT
          GPU_CORES_PER_TASK="${GPU_INPUT:-$DEFAULT_GPU_CORES}"
          validate_positive_int "$GPU_CORES_PER_TASK" "Cores per GPU task" && validate_even_int "$GPU_CORES_PER_TASK" && break
        done
        DEFAULT_GPU_RAM=8
        echo "  RAM (GB) per GPU task [$DEFAULT_GPU_RAM]:"
        echo "    (${NUM_GPUS} tasks × ${DEFAULT_GPU_RAM} GB = $(( NUM_GPUS * DEFAULT_GPU_RAM )) GB)"
        read -p "  RAM per GPU task: " GPU_RAM_INPUT
        GPU_RAM_PER_TASK_GB="${GPU_RAM_INPUT:-$DEFAULT_GPU_RAM}"
        GPU_CORES_USED=$(( NUM_GPUS * GPU_CORES_PER_TASK ))
        GPU_RAM_USED=$(( NUM_GPUS * GPU_RAM_PER_TASK_GB ))
        CORES_REMAINING=$(( CORES_AVAILABLE - GPU_CORES_USED ))
        RAM_REMAINING=$(( RAM_AVAILABLE - GPU_RAM_USED ))
        echo "    Remaining: ${CORES_REMAINING} CPU cores, ${RAM_REMAINING} GB RAM"
        echo ""
        if [ "$CORES_REMAINING" -ge 2 ] && [ "$RAM_REMAINING" -ge 4 ]; then
          DEFAULT_CPU_CORES=2
          echo "  CPU cores per CPU task [$DEFAULT_CPU_CORES]:"
          echo "    (at most $(( CORES_REMAINING / DEFAULT_CPU_CORES )) by cores)"
          read -p "  Cores per CPU task: " CPU_INPUT
          CPU_CORES_PER_TASK="${CPU_INPUT:-$DEFAULT_CPU_CORES}"
          DEFAULT_CPU_RAM=4
          echo "  RAM (GB) per CPU task [$DEFAULT_CPU_RAM]:"
          echo "    (at most $(( RAM_REMAINING / DEFAULT_CPU_RAM )) by RAM)"
          read -p "  RAM per CPU task: " CPU_RAM_INPUT
          CPU_RAM_PER_TASK_GB="${CPU_RAM_INPUT:-$DEFAULT_CPU_RAM}"
          CPU_BY_CORES=$(( CORES_REMAINING / CPU_CORES_PER_TASK ))
          CPU_BY_RAM=$(( RAM_REMAINING / CPU_RAM_PER_TASK_GB ))
          CPU_COUNT_VAL=$(( CPU_BY_CORES < CPU_BY_RAM ? CPU_BY_CORES : CPU_BY_RAM ))
          [ "$CPU_COUNT_VAL" -lt 0 ] && CPU_COUNT_VAL=0
          echo "    → ${CPU_COUNT_VAL} CPU task(s)"
        else
          echo "  No spare resources for CPU tasks (need 2+ cores and 4+ GB)."
          CPU_CORES_PER_TASK=2
          CPU_RAM_PER_TASK_GB=4
          CPU_COUNT_VAL=0
        fi
        GPU_COUNT_VAL=$NUM_GPUS
        GPU_BY_CORES=$(( CORES_AVAILABLE / GPU_CORES_PER_TASK ))
        GPU_BY_RAM=$(( RAM_AVAILABLE / GPU_RAM_PER_TASK_GB ))
        [ "$GPU_BY_CORES" -lt "$GPU_COUNT_VAL" ] && GPU_COUNT_VAL=$GPU_BY_CORES
        [ "$GPU_BY_RAM" -lt "$GPU_COUNT_VAL" ] && GPU_COUNT_VAL=$GPU_BY_RAM
        [ "$GPU_COUNT_VAL" -lt 0 ] && GPU_COUNT_VAL=0
      fi
    fi
    if [ -z "${WORKER_GPU_ID:-}" ]; then
      echo ""
      DEFAULT_CPU_CORES=2
      echo "  CPU cores per evaluation task [$DEFAULT_CPU_CORES]:"
      echo "    (at most $(( CORES_AVAILABLE / DEFAULT_CPU_CORES )) by cores)"
      read -p "  Cores per CPU task: " CPU_INPUT
      CPU_CORES_PER_TASK="${CPU_INPUT:-$DEFAULT_CPU_CORES}"
      DEFAULT_CPU_RAM=4
      echo "  RAM (GB) per CPU task [$DEFAULT_CPU_RAM]:"
      echo "    (at most $(( RAM_AVAILABLE / DEFAULT_CPU_RAM )) by RAM)"
      read -p "  RAM per CPU task: " CPU_RAM_INPUT
      CPU_RAM_PER_TASK_GB="${CPU_RAM_INPUT:-$DEFAULT_CPU_RAM}"
      CPU_BY_CORES=$(( CORES_AVAILABLE / CPU_CORES_PER_TASK ))
      CPU_BY_RAM=$(( RAM_AVAILABLE / CPU_RAM_PER_TASK_GB ))
      CPU_COUNT_VAL=$(( CPU_BY_CORES < CPU_BY_RAM ? CPU_BY_CORES : CPU_BY_RAM ))
      [ "$CPU_COUNT_VAL" -lt 0 ] && CPU_COUNT_VAL=0
      GPU_COUNT_VAL=0
    fi
    CELERY_WORKER_CONCURRENCY=$(( GPU_COUNT_VAL + CPU_COUNT_VAL ))
  fi

  if [ "$WORKER_TYPE" != "internal" ]; then
    GPU_CORES=${GPU_CORES_PER_TASK:-0}
    GPU_RAM=${GPU_RAM_PER_TASK_GB:-0}
    CPU_CORES=${CPU_CORES_PER_TASK:-0}
    CPU_RAM=${CPU_RAM_PER_TASK_GB:-0}
    SPARE_CORES=$(( CORES_AVAILABLE - GPU_COUNT_VAL * GPU_CORES - CPU_COUNT_VAL * CPU_CORES ))
    SPARE_RAM=$(( RAM_AVAILABLE - GPU_COUNT_VAL * GPU_RAM - CPU_COUNT_VAL * CPU_RAM ))
  fi

  echo ""
  echo "  ──────────────────────────────────────────────"
  echo "    System:              ${TOTAL_CORES} cores, ${TOTAL_RAM_GB} GB"
  echo "    Reserved (system):   ${RESERVED_CORES} core, ${RESERVED_RAM} GB"
  echo "    Available:           ${CORES_AVAILABLE} cores, ${RAM_AVAILABLE} GB"
  if [ "$WORKER_TYPE" = "internal" ]; then
    echo "    Type:                internal (system tasks only)"
    echo "    Concurrency:         ${CELERY_WORKER_CONCURRENCY}"
  else
    if [ -n "${WORKER_GPU_ID:-}" ]; then
      echo "    GPU IDs:             ${WORKER_GPU_ID}"
      echo "    GPU tasks:           ${GPU_COUNT_VAL} × (${GPU_CORES_PER_TASK} cores, ${GPU_RAM_PER_TASK_GB} GB)"
    fi
    if [ "$CPU_COUNT_VAL" -gt 0 ]; then
      echo "    CPU tasks:           ${CPU_COUNT_VAL} × (${CPU_CORES_PER_TASK} cores, ${CPU_RAM_PER_TASK_GB} GB)"
    fi
    echo "    Spare (idle):        ${SPARE_CORES} cores, ${SPARE_RAM} GB"
    echo "    Concurrency:         ${CELERY_WORKER_CONCURRENCY}"
  fi
  echo "    Mode:                ${WORKER_MODE}"
  echo "    Type:                ${WORKER_TYPE}"
  echo "  ──────────────────────────────────────────────"
  echo ""
  read -p "  Is this OK? [Y/n/edit]: " CONFIRM
  case "${CONFIRM:-Y}" in
    n|N) echo "  Exiting. No changes saved."; exit 0 ;;
    edit) echo "  Restarting setup..." ;;
    *) CONFIG_OK=true ;;
  esac
done

# Save to worker.env
{
  echo ""
  echo "# Worker config — set by make setup-worker"
  echo "WORKER_MODE=$WORKER_MODE"
  echo "WORKER_TYPE=$WORKER_TYPE"
  if [ -n "${WORKER_GPU_ID:-}" ]; then
    echo "WORKER_GPU_ID=$WORKER_GPU_ID"
    echo "GPU_CORES_PER_TASK=$GPU_CORES_PER_TASK"
    echo "GPU_RAM_PER_TASK_GB=$GPU_RAM_PER_TASK_GB"
  fi
  if [ -n "$CPU_CORES_PER_TASK" ]; then
    echo "CPU_CORES_PER_TASK=$CPU_CORES_PER_TASK"
  fi
  if [ -n "$CPU_RAM_PER_TASK_GB" ]; then
    echo "CPU_RAM_PER_TASK_GB=$CPU_RAM_PER_TASK_GB"
  fi
  echo "CELERY_WORKER_CONCURRENCY=$CELERY_WORKER_CONCURRENCY"
  echo "RESERVED_RAM_GB=${RESERVED_RAM}"
  echo "RESERVED_CPU_CORES=${RESERVED_CORES}"
  echo "RAM_CLAMP_FACTOR=1.05"
} >> worker.env
echo "  ✔ Configuration saved to worker.env"
echo "  Run 'make deploy-worker' to start the worker."
