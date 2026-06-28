.PHONY: help setup-server setup-worker deploy-server deploy-worker dev \
        generate-keys setup-admin docs check-error-codes lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?# "}; {printf "  \033[1;34m%-20s\033[0m %s\n", $$1, $$2}'

setup-server:   # Server: prerequisites, micromamba env, pip, npm ci, keys
	@scripts/setup.sh server

setup-worker:   # Worker: prerequisites, local env setup (if needed), interactive config
	@scripts/setup-worker.sh

deploy-server:  # Deploy server with Docker Compose (build + up -d)
	@scripts/deploy-docker.sh

deploy-worker:  # Build (if needed) and deploy worker from saved config
	@scripts/deploy-worker.sh

dev:            # Local debug mode (micromamba + Flask + Celery + frontend)
	@scripts/deploy-debug.sh

generate-keys:  # Re-generate missing security keys
	@scripts/generate-keys.sh

setup-admin:    # Create an admin user (works with and without Docker)
	@if docker compose ps backend 2>/dev/null | grep -q "Up"; then \
		docker compose exec backend python3 /app/setup-admin.py; \
		docker compose cp backend:/app/admin_credentials.txt ./admin_credentials.txt 2>/dev/null || true; \
	else \
		python3 backend/setup-admin.py; \
	fi

docs:           # Build Sphinx documentation
	@$(MAKE) -C docs html

check-error-codes:  # Check that all error responses include a machine-readable 'code' field
	@python3 backend/scripts/check_error_codes.py

lint: check-error-codes  # Run all lint checks
	@cd backend && ruff format --check . && ruff check .
	@cd frontend && npx tsc --noEmit
