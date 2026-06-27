.PHONY: help setup setup-worker dev deploy-docker deploy-docker-fast deploy-debug \
        start-worker worker worker-docker build-worker edit edit-worker \
        docs check-error-codes lint setup-admin

help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?# "}; {printf "  \033[1;34m%-20s\033[0m %s\n", $$1, $$2}'

setup:          # First-time setup: prereqs, micromamba env, keys, deps
	@scripts/setup.sh server

setup-worker:   # Worker setup: check prereqs (Docker only)
	@scripts/setup.sh worker

dev: deploy-debug # Alias for deploy-debug

deploy-docker:  # Full Docker Compose deployment (build + start)
	@scripts/deploy-docker.sh

deploy-docker-fast:  # Docker Compose deployment (skip rebuild)
	@scripts/deploy-docker.sh --skip-build

deploy-debug:   # Local debug mode (micromamba + Flask + Celery + frontend)
	@scripts/deploy-debug.sh

start-worker:   # Start a worker via micromamba (must pass REDIS_URL)
	@if [ -z "$(REDIS_URL)" ]; then \
		echo "Usage: make start-worker REDIS_URL=redis://... [GPU_ID=0]"; \
		exit 1; \
	fi
	@scripts/start-worker.sh "$(REDIS_URL)" "$(GPU_ID)"

worker:         # Start a worker (interactive first-run, then uses saved config)
	@scripts/start-worker.sh

worker-docker:  # Start a remote Celery worker via Docker (reads worker.env)
	@scripts/start-worker.sh --docker

build-worker:   # Build the minimal worker Docker image
	docker build -t lavbench-worker -f backend/Dockerfile.worker backend/

generate-keys:  # Re-generate missing security keys
	@scripts/generate-keys.sh

setup-admin:    # Create an admin user (works with and without Docker)
	@if docker compose ps backend 2>/dev/null | grep -q "Up"; then \
		docker compose exec backend python3 /app/setup-admin.py; \
	else \
		python backend/setup-admin.py; \
	fi

docs:           # Build Sphinx documentation
	@$(MAKE) -C docs html

check-error-codes:  # Check that all error responses include a machine-readable 'code' field
	@python backend/scripts/check_error_codes.py

lint: check-error-codes  # Run all lint checks
	@cd backend && ruff format --check . && ruff check .
	@cd frontend && npx tsc --noEmit
