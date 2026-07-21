#!/bin/sh
set -e

# Ensure runtime directories exist and are writable by nobody (65534)
for dir in /app/uploads /app/hf_cache /app/backups /backups /app/run /app/.gunicorn; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
  fi
  chown -R 65534:65534 "$dir"
done

# Raise file descriptor limit for high concurrency
ulimit -n "${GUNICORN_ULIMIT_NOFILE:-65536}"

# Build extra gunicorn args from env vars (only for gunicorn commands)
if echo "$*" | grep -qE 'gunicorn'; then
  set -- "$@" \
    --max-requests "${GUNICORN_MAX_REQUESTS:-10000}" \
    --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-2000}" \
    --access-logfile "${GUNICORN_ACCESS_LOGFILE:--}" \
    --error-logfile "${GUNICORN_ERROR_LOGFILE:--}"
fi

# Drop privileges to nobody (UID 65534) and exec the command
exec setpriv --reuid=65534 --regid=65534 --clear-groups -- "$@"
