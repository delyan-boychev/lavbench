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

USER nobody

EXPOSE 5001

CMD ["gunicorn", "-k", "gevent", "--worker-connections", "1000", "-w", "4", "--timeout", "300", "--graceful-timeout", "30", "-b", "0.0.0.0:5001", "app:app"]
