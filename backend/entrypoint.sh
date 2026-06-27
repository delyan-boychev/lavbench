#!/bin/sh
set -e

# Ensure runtime directories exist and are writable by nobody (65534)
for dir in /app/uploads /app/hf_cache /app/backups /backups /app/run; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
  fi
  chown -R 65534:65534 "$dir"
done

# Drop privileges to nobody (UID 65534) and exec the command
exec setpriv --reuid=65534 --regid=65534 --clear-groups "$@"
