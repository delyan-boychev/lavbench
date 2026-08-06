#!/bin/sh
set -e

# Ensure runtime directories exist and are writable by nobody (65534).
# Best-effort: the image pre-owns these at build time; bind/legacy mounts
# can only be fixed up when the entrypoint starts as root.
for dir in /app/uploads /app/hf_cache /app/backups /backups /app/logs /app/run /app/.gunicorn; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir" 2>/dev/null || true
  fi
  if ! chown -R 65534:65534 "$dir" 2>/dev/null; then
    echo "WARNING: cannot chown '$dir' (running reduced-capability image); ensure it is owned by UID 65534"
  fi
done

# Raise the file descriptor limit (only possible as root; compose already
# configures ulimits for the non-root runtime).
if [ "$(id -u)" -eq 0 ]; then
  ulimit -n "${GUNICORN_ULIMIT_NOFILE:-65536}"
fi

# Build extra gunicorn args from env vars (only for gunicorn commands)
if echo "$*" | grep -qE 'gunicorn'; then
  set -- "$@" \
    --max-requests "${GUNICORN_MAX_REQUESTS:-10000}" \
    --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-2000}" \
    --access-logfile "${GUNICORN_ACCESS_LOGFILE:--}" \
    --error-logfile "${GUNICORN_ERROR_LOGFILE:--}"
fi

# Drop privileges to nobody (UID 65534) and exec the command. When the image
# already runs as nobody (USER 65534), exec directly — setpriv needs root.
if [ "$(id -u)" -eq 0 ]; then
  exec setpriv --reuid=65534 --regid=65534 --clear-groups -- "$@"
fi
exec "$@"
