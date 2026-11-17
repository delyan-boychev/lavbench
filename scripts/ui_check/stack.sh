#!/usr/bin/env bash
# Start or remove a THROWAWAY local LavBench stack for the visual check, the way the CI
# docker-build job does (.github/workflows/ci.yml is the source of truth): build the
# images, compose up, attach an evaluation worker, create the admin.
#
#   scripts/ui_check/stack.sh up     # writes admin_credentials.txt in the repo root
#   scripts/ui_check/stack.sh down   # removes the containers AND their volumes
#
# Never point this at a stack whose data you want to keep: "down" deletes every volume.
# HTTPS_PORT moves the TLS listener when another service already holds port 443.
set -euo pipefail
cd "$(dirname "$0")/../.."

export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ui-check-password}"
export REDIS_PASSWORD="${REDIS_PASSWORD:-ui-check-redis}"
export SECRET_KEY="${SECRET_KEY:-ui-check-secret-key-00000000000000000000}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-tVG8-i368hyvsKNRoBKqZIXuExByVbQgKrUHKvqNFis=}"
# The same throwaway worker key pair CI uses; the private half is below
export WORKER_PUBLIC_KEYS_JSON='{"ci-eval-worker":"gwEOQ7vkepTvOxbVFGy/iayILrRTEsYbw54+I5BF7RY="}'
export WORKER_CAPABILITY_SECRET="${WORKER_CAPABILITY_SECRET:-ui-check-capability-secret-000000000000}"
export EVALUATION_SPLIT_SECRET="${EVALUATION_SPLIT_SECRET:-ui-check-split-secret-00000000000000000}"
export SERVER_ADDRESS=localhost
export MAIN_SERVER_URL=http://backend:5001
export SECURE_COOKIES=false
export HTTPS_PORT="${HTTPS_PORT:-443}"

down() {
  docker rm -f lavbench_eval_worker >/dev/null 2>&1 || true
  docker compose down -v --remove-orphans
  docker volume rm lavbench_task_images lavbench_hf_cache lavbench_workspace >/dev/null 2>&1 || true
}

up() {
  docker build -q -t lavbench-backend backend/ >/dev/null
  docker build -q -t lavbench-frontend frontend/ >/dev/null
  docker build -q -f backend/Dockerfile.worker -t lavbench-worker backend/ >/dev/null
  mkdir -p certs secrets
  docker compose -f docker-compose.yml up -d --build
  for svc in lavbench_db lavbench_redis lavbench_redis_cache lavbench_backend lavbench_beat \
             lavbench_worker lavbench_frontend; do
    for _ in $(seq 1 60); do
      [ "$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null)" = healthy ] && break
      sleep 2
    done
    [ "$(docker inspect --format='{{.State.Health.Status}}' "$svc")" = healthy ] \
      || { echo "$svc is not healthy" >&2; docker logs "$svc" --tail 40; exit 1; }
  done

  local network
  network=$(docker inspect -f '{{.HostConfig.NetworkMode}}' lavbench_backend)
  docker volume create lavbench_task_images >/dev/null
  docker volume create lavbench_hf_cache >/dev/null
  docker volume create lavbench_workspace >/dev/null
  # Two slots, so the long "live log" run never blocks the other evaluations
  docker run -d --name lavbench_eval_worker --network "$network" \
    --group-add "$(stat -c %g /var/run/docker.sock)" \
    -e CELERY_BROKER_URL="redis://:${REDIS_PASSWORD}@redis:6379/0" \
    -e CACHE_REDIS_URL="redis://:${REDIS_PASSWORD}@redis-cache:6379/1" \
    -e SECRET_KEY -e ENCRYPTION_KEY -e WORKER_CAPABILITY_SECRET -e EVALUATION_SPLIT_SECRET \
    -e WORKER_PRIVATE_KEY="NaKOt/qVZHOA4rAe6MmGoj/bNkHSG1FjTxrzcYL7zBU=" \
    -e WORKER_ID="ci-eval-worker" -e MAIN_SERVER_URL -e WORKER_ROLE="eval" \
    -e HF_CACHE_DIR="/var/lib/lavbench/hf_cache" \
    -e TASK_IMAGES_DIR="/var/lib/lavbench/task_images" \
    -e LAVBENCH_WORKSPACE_DIR="/var/lib/lavbench/workspace" \
    -e CPU_WORKER_CONCURRENCY="2" -e WORKER_SANDBOX_STORAGE_OPT="" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v lavbench_task_images:/var/lib/lavbench/task_images \
    -v lavbench_hf_cache:/var/lib/lavbench/hf_cache \
    -v lavbench_workspace:/var/lib/lavbench/workspace \
    lavbench-worker >/dev/null
  local host
  host=$(docker inspect -f '{{.Config.Hostname}}' lavbench_eval_worker)
  for _ in $(seq 1 60); do
    docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning \
      --scan --pattern 'worker_spec:*' 2>/dev/null | grep -q "cpu@${host}" && break
    sleep 2
  done
  docker compose exec -T backend python3 /app/scripts/setup-admin.py >/dev/null
  docker compose cp backend:/app/admin_credentials.txt ./admin_credentials.txt
  echo "stack up on http://localhost:80; admin credentials in admin_credentials.txt"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
