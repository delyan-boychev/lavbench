#!/bin/sh
set -e

mkdir -p /app/logs
chmod 1777 /app/logs

# Enable the TLS listener (443) only when certificates are actually present.
# ssl.conf.disabled is always in the image; copying it to ssl.conf makes nginx
# pick it up as an active config. Without certs, nginx stays HTTP-only.
if [ -f /etc/nginx/ssl/lavbench.crt ] && [ -f /etc/nginx/ssl/lavbench.key ]; then
  cp /etc/nginx/conf.d/ssl.conf.disabled /etc/nginx/conf.d/ssl.conf
  echo "nginx: TLS certificates found — 443 listener enabled"
fi

exec nginx -g "daemon off;"