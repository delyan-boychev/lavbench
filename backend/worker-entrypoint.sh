#!/bin/bash
set -e

GPU_WORKER_CONCURRENCY="${GPU_WORKER_CONCURRENCY:-0}"
CPU_WORKER_CONCURRENCY="${CPU_WORKER_CONCURRENCY:-1}"

if [ "$GPU_WORKER_CONCURRENCY" -gt 0 ]; then
    echo "  → GPU worker: concurrency=$GPU_WORKER_CONCURRENCY (queue: gpu_queue)"
    celery -A tasks.celery worker -Q gpu_queue -c "$GPU_WORKER_CONCURRENCY" --loglevel=info &
    PID_GPU=$!
else
    echo "  → No GPU worker"
    PID_GPU=""
fi

echo "  → CPU worker: concurrency=$CPU_WORKER_CONCURRENCY (queues: cpu_queue,celery)"
celery -A tasks.celery worker -Q cpu_queue,celery -c "$CPU_WORKER_CONCURRENCY" --loglevel=info &
PID_CPU=$!

cleanup() {
    [ -n "$PID_GPU" ] && kill "$PID_GPU" 2>/dev/null
    kill "$PID_CPU" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup SIGTERM SIGINT

wait
