FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (build tools, PostgreSQL developer libraries, and pg_dump client)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose the Gunicorn listener port
EXPOSE 5001

CMD ["gunicorn", "-k", "gevent", "--worker-connections", "1000", "-w", "4", "--timeout", "300", "--graceful-timeout", "30", "-b", "0.0.0.0:5001", "app:app"]
