#!/bin/bash
set -e

# Ensure persistent storage dirs exist (named volumes are auto-created by
# Docker, but keep this defensive for bind/local setups). Best-effort: legacy
# root-owned volumes are fixed up by deploy-worker.sh before starting.
for dir in /var/lib/lavbench/task_images /var/lib/lavbench/workspace /var/lib/lavbench/hf_cache; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir" 2>/dev/null || echo "WARNING: cannot create '$dir'"
  fi
done

GPU_WORKER_CONCURRENCY="${GPU_WORKER_CONCURRENCY:-0}"
CPU_WORKER_CONCURRENCY="${CPU_WORKER_CONCURRENCY:-1}"
HOST=$(hostname)

if [ "$GPU_WORKER_CONCURRENCY" -gt 0 ]; then
    echo "  → GPU worker: concurrency=$GPU_WORKER_CONCURRENCY (queue: gpu_queue)"
    celery -A tasks.celery worker -Q gpu_queue -c "$GPU_WORKER_CONCURRENCY" \
        --loglevel=info --hostname="gpu@${HOST}" &
    PID_GPU=$!
else
    echo "  → No GPU worker"
    PID_GPU=""
fi

echo "  → CPU worker: concurrency=$CPU_WORKER_CONCURRENCY (queue: cpu_queue)"
celery -A tasks.celery worker -Q cpu_queue -c "$CPU_WORKER_CONCURRENCY" \
    --loglevel=info --hostname="cpu@${HOST}" &
PID_CPU=$!

cleanup() {
    [ -n "$PID_GPU" ] && kill "$PID_GPU" 2>/dev/null
    kill "$PID_CPU" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup SIGTERM SIGINT

wait
