.PHONY: help server dev deploy deploy-debug deploy-deploy-fast \
        worker build-worker \
        docs check-error-codes lint setup-admin

help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?# "}; {printf "  \033[1;34m%-20s\033[0m %s\n", $$1, $$2}'

server:         # Server: first-time setup (prereqs, micromamba, keys, deps)
	@scripts/setup.sh server

deploy:         # Deploy with Docker Compose (build + start)
	@scripts/deploy-docker.sh

deploy-fast:    # Deploy with Docker Compose (skip rebuild)
	@scripts/deploy-docker.sh --skip-build

dev:            # Local debug mode (micromamba + Flask + Celery + frontend)
	@scripts/deploy-debug.sh

worker:         # Worker: first-run interactive setup + build + start
	@scripts/setup.sh worker && scripts/start-worker.sh

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
