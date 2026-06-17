.PHONY: help deploy-docker deploy-debug start-worker docs dev

help:
	@grep -E '^[a-zA-Z_-]+:.*?# .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?# "}; {printf "  \033[1;34m%-20s\033[0m %s\n", $$1, $$2}'

deploy-docker:  # Full Docker Compose deployment (db, redis, backend, beat, frontend)
	@scripts/deploy-docker.sh

deploy-debug:   # Local debug mode (micromamba + Flask + Celery worker + beat + frontend)
	@scripts/deploy-debug.sh

start-worker:   # Start a remote Celery worker — usage: make start-worker REDIS_URL=redis://... [GPU_ID=0]
	@if [ -z "$(REDIS_URL)" ]; then \
		echo "Usage: make start-worker REDIS_URL=redis://... [GPU_ID=0]"; \
		exit 1; \
	fi
	@scripts/start-worker.sh "$(REDIS_URL)" "$(GPU_ID)"

docs:           # Build Sphinx documentation
	@$(MAKE) -C docs html

dev: deploy-debug # Alias for deploy-debug
