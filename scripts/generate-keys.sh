#!/usr/bin/env bash
# scripts/generate-keys.sh — Auto-generate all security keys for LavBench.
# Called by make setup. Prompts for server address, HTTP/HTTPS, Redis TLS.
set -euo pipefail
umask 077

ENV_FILE=".env"
WORKER_ENV="worker.env"

# ── Ensure .env exists ─────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example "$ENV_FILE"
    echo "  → .env created from .env.example"
  else
    echo "  [ERROR] .env.example not found." >&2
    exit 1
  fi
fi

# ── Helper: set a key=value in .env if not already present ─────────
set_if_missing() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    current=$(grep "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)
    if [ -z "$current" ] || [ "$current" = "replace_with_secure_random_64_chars_min" ] || [ "$current" = "replace_with_base64_encoded_ed25519_public_key" ]; then
      sed -i.bak "s/^${key}=.*/${key}=${value}/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
      echo "  → ${key}    ✓ generated"
    else
      echo "  → ${key}    ✓ already set (skipped)"
    fi
  else
    echo "${key}=${value}" >> "$ENV_FILE"
    echo "  → ${key}    ✓ generated"
  fi
}

# ── Helper: update a key=value in .env (overwrite always) ──────────
set_env() {
  local key="$1"
  local value="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${value}|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

# ── Generate keys ──────────────────────────────────────────────────
echo ""
echo "  Auto-generating security keys..."

GENERATE_HTTPS_CERTS=false

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
set_if_missing "SECRET_KEY" "$SECRET_KEY"

generate_fernet_key() {
  python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
}

ensure_fernet_key() {
  local key="$1"
  local current
  current=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-) || true
  if python3 -c "
import base64, sys
try:
    valid = len(base64.urlsafe_b64decode(sys.argv[1].encode())) == 32
except Exception:
    valid = False
raise SystemExit(0 if valid else 1)
" "$current"; then
    echo "  → ${key}    ✓ already set (skipped)"
  else
    set_env "$key" "$(generate_fernet_key)"
    echo "  → ${key}    ✓ generated"
  fi
}

ensure_fernet_key "ENCRYPTION_KEY"

# Independent Fernet key for remote workers — never the server JWT key.
ensure_fernet_key "WORKER_ENCRYPTION_KEY"

POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
set_if_missing "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD"
set_if_missing "POSTGRES_USER" "lavbench_user"
set_if_missing "POSTGRES_DB" "lavbench_db"

REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
set_if_missing "REDIS_PASSWORD" "$REDIS_PASSWORD"

# Per-worker Ed25519 keypair and append-only server registry. Re-running setup
# Reuses the local worker identity instead of invalidating deployed workers.
WORKER_ID=$(grep "^WORKER_ID=" "$WORKER_ENV" 2>/dev/null | tail -1 | cut -d= -f2-) || true
WORKER_PRIVATE_KEY=$(grep "^WORKER_PRIVATE_KEY=" "$WORKER_ENV" 2>/dev/null | tail -1 | cut -d= -f2-) || true
if [ -z "$WORKER_ID" ] || [ -z "$WORKER_PRIVATE_KEY" ]; then
  WORKER_ID="eval-$(python3 -c "import secrets; print(secrets.token_hex(6))")"
  KEYPAIR=$(python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64
k = Ed25519PrivateKey.generate()
pub = base64.b64encode(k.public_key().public_bytes_raw()).decode()
priv = base64.b64encode(k.private_bytes_raw()).decode()
print(f'WORKER_PUBLIC_KEY={pub}')
print(f'WORKER_PRIVATE_KEY={priv}')
")
  WORKER_PRIVATE_KEY=$(echo "$KEYPAIR" | grep WORKER_PRIVATE_KEY | cut -d= -f2-)
fi
WORKER_PUBLIC_KEY=$(python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64, sys
private = base64.b64decode(sys.argv[1])
print(base64.b64encode(Ed25519PrivateKey.from_private_bytes(private).public_key().public_bytes_raw()).decode())
" "$WORKER_PRIVATE_KEY")
EXISTING_WORKER_REGISTRY=$(grep "^WORKER_PUBLIC_KEYS_JSON=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-) || true
WORKER_PUBLIC_KEYS_JSON=$(python3 -c "
import json, sys
registry = json.loads(sys.argv[1] or '{}')
if not isinstance(registry, dict):
    raise SystemExit('WORKER_PUBLIC_KEYS_JSON must be a JSON object')
registry[sys.argv[2]] = sys.argv[3]
print(json.dumps(registry, separators=(',', ':')))
" "$EXISTING_WORKER_REGISTRY" "$WORKER_ID" "$WORKER_PUBLIC_KEY")
set_env "WORKER_PUBLIC_KEYS_JSON" "$WORKER_PUBLIC_KEYS_JSON"

WORKER_CAPABILITY_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
set_if_missing "WORKER_CAPABILITY_SECRET" "$WORKER_CAPABILITY_SECRET"

EVALUATION_SPLIT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
set_if_missing "EVALUATION_SPLIT_SECRET" "$EVALUATION_SPLIT_SECRET"

# ── Read existing values ───────────────────────────────────────────
read_env() {
  grep "^${1}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-
}
POSTGRES_PASSWORD=$(read_env "POSTGRES_PASSWORD")
REDIS_PASSWORD=$(read_env "REDIS_PASSWORD")
WORKER_ENCRYPTION_KEY=$(read_env "WORKER_ENCRYPTION_KEY")
WORKER_PRIVATE_KEY="${WORKER_PRIVATE_KEY:-$(grep "^WORKER_PRIVATE_KEY=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)}" || true

# ── Interative prompts ─────────────────────────────────────────────
echo ""
echo "  ── Remote worker configuration ──────────────────────────"
echo ""

# 1. Server address
read -p "  Server address (IP or domain) [localhost]: " SERVER_ADDR
SERVER_ADDR="${SERVER_ADDR:-localhost}"
echo ""

# 2. HTTP or HTTPS
echo "  Does the server use HTTPS?"
echo "    1) HTTP   (http://${SERVER_ADDR})"
echo "    2) HTTPS  (https://${SERVER_ADDR})"
read -p "  Choose [1]: " HTTP_CHOICE
HTTP_CHOICE="${HTTP_CHOICE:-1}"
if [ "$HTTP_CHOICE" = "2" ]; then
  PROTOCOL="https"
  SERVER_URL="https://${SERVER_ADDR}"
  set_env "CORS_ORIGINS" "https://${SERVER_ADDR}"
  set_env "SECURE_COOKIES" "true"
  GENERATE_HTTPS_CERTS=false
  echo ""
  echo "  Generate self-signed HTTPS certificates?"
  echo "    (or choose No to place your own in certs/ later)"
  read -p "  Generate now? (Y/n): " GEN_HTTPS_CHOICE
  if [ "$GEN_HTTPS_CHOICE" != "n" ] && [ "$GEN_HTTPS_CHOICE" != "N" ]; then
    GENERATE_HTTPS_CERTS=true
  fi
  if [ "$GENERATE_HTTPS_CERTS" = "true" ]; then
    mkdir -p certs/web
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout certs/web/lavbench.key -out certs/web/lavbench.crt \
      -days 825 -subj "/CN=${SERVER_ADDR}" \
      -addext "subjectAltName=DNS:${SERVER_ADDR},IP:${SERVER_ADDR}" 2>/dev/null || \
      openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout certs/web/lavbench.key -out certs/web/lavbench.crt \
        -days 825 -subj "/CN=${SERVER_ADDR}"
    set_env "HTTPS_PORT" "443"
    echo "  ✔ Self-signed TLS certs written to certs/web/ (lavbench.crt + lavbench.key)"
    echo "    The frontend nginx will enable its 443 listener automatically."
  fi
else
  PROTOCOL="http"
  echo ""
  read -p "  Nginx port (external) [80]: " NGINX_PORT
  NGINX_PORT="${NGINX_PORT:-80}"
  SERVER_URL="http://${SERVER_ADDR}:${NGINX_PORT}"
  set_env "NGINX_PORT" "$NGINX_PORT"
  set_env "CORS_ORIGINS" "${SERVER_URL}"
  set_env "SECURE_COOKIES" "false"
fi
echo ""

# 3. Redis TLS
echo "  Does Redis use TLS (rediss://)?"
echo "    1) No TLS  (redis://)"
echo "    2) TLS     (rediss://)"
read -p "  Choose [1]: " REDIS_TLS_CHOICE
REDIS_TLS_CHOICE="${REDIS_TLS_CHOICE:-1}"
if [ "$REDIS_TLS_CHOICE" = "2" ]; then
  REDIS_PROTO="rediss"
  REDIS_TLS=true
else
  REDIS_PROTO="redis"
  REDIS_TLS=false
fi
echo ""

# 4. Generate self-signed certs or manual? (only if Redis TLS)
GENERATE_CERTS=false
if [ "$REDIS_TLS" = true ]; then
  echo "  Generate self-signed Redis TLS certificates?"
  echo "    (or choose No to place your own in certs/ later)"
  read -p "  Generate now? (Y/n): " GEN_CERTS_CHOICE
  if [ "$GEN_CERTS_CHOICE" != "n" ] && [ "$GEN_CERTS_CHOICE" != "N" ]; then
    GENERATE_CERTS=true
  fi
  echo ""
fi

echo "  ──────────────────────────────────────────────────────────"
echo ""

# ── Update .env with protocol-specific settings ────────────────────
set_env "SERVER_ADDRESS" "$SERVER_ADDR"
set_env "MAIN_SERVER_URL" "$SERVER_URL"
set_env "REDIS_PROTO" "$REDIS_PROTO"

if [ "$REDIS_TLS" = true ]; then
  set_env "REDIS_SSL_CA_CERTS" "/etc/ssl/certs/redis/redis-ca.crt"
  set_env "REDIS_SSL_CERTFILE" "/etc/ssl/certs/redis/redis-client.crt"
  set_env "REDIS_SSL_KEYFILE" "/etc/ssl/certs/redis/redis-client.key"
  set_env "REDIS_SSL_CERT_REQS" "required"
else
  # Comment out or clear TLS settings if they exist
  for tls_var in REDIS_SSL_CA_CERTS REDIS_SSL_CERTFILE REDIS_SSL_KEYFILE REDIS_SSL_CERT_REQS; do
    if grep -qE "^${tls_var}=" "$ENV_FILE" 2>/dev/null; then
      sed -i.bak "s/^${tls_var}=.*/# ${tls_var}=/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
    fi
  done
fi

# ── Resolve derived URLs with actual password values ─────────────────
POSTGRES_USER=$(grep "^POSTGRES_USER=" "$ENV_FILE" | tail -1 | cut -d= -f2-)
POSTGRES_DB=$(grep "^POSTGRES_DB=" "$ENV_FILE" | tail -1 | cut -d= -f2-)
set_env "DATABASE_URL" "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"
set_env "CELERY_BROKER_URL" "${REDIS_PROTO}://:${REDIS_PASSWORD}@localhost:6379/0"
set_env "CELERY_RESULT_BACKEND" "${REDIS_PROTO}://:${REDIS_PASSWORD}@localhost:6379/0"

# ── Generate worker.env ────────────────────────────────────────────
CERTS_SECTION=""
if [ "$REDIS_TLS" = true ]; then
  if [ "$GENERATE_CERTS" = true ]; then
    CERTS_SECTION="
# Redis TLS certificates (auto-generated)
REDIS_SSL_CA_CERTS=/etc/ssl/certs/redis/redis-ca.crt
REDIS_SSL_CERTFILE=/etc/ssl/certs/redis/redis-client.crt
REDIS_SSL_KEYFILE=/etc/ssl/certs/redis/redis-client.key
REDIS_SSL_CERT_REQS=required"
  else
    CERTS_SECTION="
# Redis TLS certificates — place your files in ./certs/ first
# REDIS_SSL_CA_CERTS=/etc/ssl/certs/redis/redis-ca.crt
# REDIS_SSL_CERTFILE=/etc/ssl/certs/redis/redis-client.crt
# REDIS_SSL_KEYFILE=/etc/ssl/certs/redis/redis-client.key
# REDIS_SSL_CERT_REQS=required"
  fi
fi

cat > "$WORKER_ENV" <<WORKEREOF
# LavBench Worker Configuration
# Generated by scripts/generate-keys.sh
# Copy this file to your worker machine.

# Redis broker URL — used by Celery to receive tasks
CELERY_BROKER_URL=${REDIS_PROTO}://:${REDIS_PASSWORD}@${SERVER_ADDR}:6379/0
CELERY_RESULT_BACKEND=\${CELERY_BROKER_URL}

# Server callback URL — used by worker to report results
MAIN_SERVER_URL=${SERVER_URL}

# Worker authentication (auto-generated Ed25519 private key)
WORKER_ID=${WORKER_ID}
WORKER_PRIVATE_KEY=${WORKER_PRIVATE_KEY}

# Worker encryption key — independent Fernet key for models/ field encryption.
# Deliberately NOT the server SECRET_KEY (a compromised worker must not be able
# to mint JWTs or decrypt server-side PII).
WORKER_ENCRYPTION_KEY=${WORKER_ENCRYPTION_KEY}
${CERTS_SECTION}
# Worker role and resources — set by 'make setup-worker' on the worker machine
# WORKER_GPU_ID=0
# CELERY_WORKER_CONCURRENCY=4
WORKEREOF
chmod 0600 "$ENV_FILE" "$WORKER_ENV"
echo "  ✔ worker.env created"
echo ""

# ── Generate HTTPS (server) certificates ─────────────────────────────
mkdir -p certs
if [ "$GENERATE_HTTPS_CERTS" = true ]; then
  echo "  Generating self-signed HTTPS certificates..."
  echo ""
  openssl genrsa -out certs/server.key 2048 2>/dev/null
  openssl req -new -x509 -key certs/server.key -out certs/server.crt \
    -days 365 -subj "/CN=${SERVER_ADDR}" 2>/dev/null
  echo "  ✔ Generated in certs/:"
  echo "      ├── server.crt   ← HTTPS certificate"
  echo "      └── server.key   ← HTTPS private key"
  echo ""
  echo "  → Configure your web server (nginx / caddy) to use:"
  echo "      certs/server.crt"
  echo "      certs/server.key"
  echo ""
elif [ "$HTTP_CHOICE" = "2" ]; then
  echo "  ✔ certs/ directory ready — place your HTTPS certificates in it:"
  echo "      certs/server.crt"
  echo "      certs/server.key"
  echo ""
fi

# ── Generate Redis TLS certificates ─────────────────────────────────
if [ "$REDIS_TLS" = true ] && [ "$GENERATE_CERTS" = true ]; then
  echo "  Generating self-signed Redis TLS certificates..."
  echo ""

  # CA
  openssl genrsa -out certs/ca.key 2048 2>/dev/null
  openssl req -new -x509 -key certs/ca.key -out certs/ca.crt \
    -days 3650 -subj "/CN=Redis CA" 2>/dev/null

  # Redis server cert
  openssl genrsa -out certs/redis.key 2048 2>/dev/null
  openssl req -new -key certs/redis.key -out certs/redis.csr \
    -subj "/CN=redis" 2>/dev/null
  openssl x509 -req -in certs/redis.csr -CA certs/ca.crt \
    -CAkey certs/ca.key -CAcreateserial -out certs/redis.crt \
    -days 365 2>/dev/null
  rm -f certs/redis.csr

  # Copy for LavBench client use
  cp certs/ca.crt certs/redis-ca.crt
  cp certs/redis.crt certs/redis-client.crt
  cp certs/redis.key certs/redis-client.key

  echo "  ✔ Generated in certs/:"
  echo "      ├── ca.crt               ← CA certificate (keep safe)"
  echo "      ├── redis.crt + .key     ← Redis server cert — COPY TO REDIS CONTAINER"
  echo "      ├── redis-ca.crt         ← CA cert for LavBench clients"
  echo "      ├── redis-client.crt     ← Client cert for LavBench → Redis"
  echo "      └── redis-client.key     ← Client key  for LavBench → Redis"
  echo ""
  echo "  → On the Redis server, configure:"
  echo "      tls-cert-file /path/to/redis.crt"
  echo "      tls-key-file  /path/to/redis.key"
  echo "      tls-ca-cert-file /path/to/ca.crt"
  echo "      tls-auth-clients no"
  echo ""
elif [ "$REDIS_TLS" = true ]; then
  echo "  ✔ certs/ directory ready — place your Redis TLS certificates in it:"
  echo "      certs/redis-ca.crt"
  echo "      certs/redis-client.crt"
  echo "      certs/redis-client.key"
  echo ""
else
  echo "  ✔ certs/ directory ready (add certificates here if needed later)"
fi
echo ""

# ── Done ───────────────────────────────────────────────────────────
echo "  ──────────────────────────────────────────────────────────"
echo "    Configuration summary:"
echo "    Server URL:   ${SERVER_URL}"
echo "    Redis:        ${REDIS_PROTO}://:****@${SERVER_ADDR}:6379/0"
echo "    Worker auth:  Ed25519 keypair generated"
echo ""
echo "    Next:"
if [ "$SERVER_ADDR" != "localhost" ] || [ "$HTTP_CHOICE" = "2" ] || [ "$REDIS_TLS_CHOICE" = "2" ]; then
  echo "      scp worker.env user@${SERVER_ADDR}:~/"
  echo "      On worker: make setup-worker && make deploy-worker"
fi
echo "  ──────────────────────────────────────────────────────────"
echo ""
