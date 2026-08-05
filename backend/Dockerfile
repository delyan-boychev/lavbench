# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local

COPY --chown=nobody:nogroup . .

# Pre-own the runtime dirs so reduced-capability containers (cap_drop: ALL)
# that cannot chown at boot still have nobody-writable storage.
RUN mkdir -p /app/uploads /app/hf_cache /app/backups /backups /app/logs /app/run /app/.gunicorn \
    && chown -R 65534:65534 /app/uploads /app/hf_cache /app/backups /backups /app/logs /app/run /app/.gunicorn

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV HOME=/app

EXPOSE 5001

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "-k", "gevent", "--worker-connections", "1000", "-w", "4", "--timeout", "300", "--graceful-timeout", "30", "--pid", "/app/run/gunicorn.pid", "-b", "0.0.0.0:5001", "wsgi:app"]
