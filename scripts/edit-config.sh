#!/usr/bin/env bash
# scripts/edit-config.sh — Edit LavBench config without touching auto-generated keys.
# Called by: make edit (server .env), make edit-worker (worker.env)
set -euo pipefail

ENV_FILE=".env"
WORKER_FILE="worker.env"
PROTECTED_ENV="SECRET_KEY POSTGRES_PASSWORD REDIS_PASSWORD WORKER_PUBLIC_KEY ENCRYPTION_KEY"
PROTECTED_WORKER="CELERY_BROKER_URL CELERY_RESULT_BACKEND WORKER_PRIVATE_KEY"

get_val() {
  local file="$1" key="$2"
  sed -n "s/^${key}=//p" "$file" 2>/dev/null | tail -1
}

set_val() {
  local file="$1" key="$2" val="$3"
  if grep -qE "^${key}=" "$file" 2>/dev/null; then
    sed -i.bak "s|^${key}=.*|${key}=${val}|" "$file" && rm -f "$file.bak"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

toggle_comment() {
  local file="$1" key="$2" state="$3"
  if [ "$state" = "uncomment" ]; then
    sed -i.bak "s|^# ${key}=|${key}=|" "$file" && rm -f "$file.bak"
  else
    if grep -qE "^${key}=" "$file" 2>/dev/null; then
      sed -i.bak "s|^${key}=|# ${key}=|" "$file" && rm -f "$file.bak"
    fi
  fi
}

edit_server() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "  [ERROR] $ENV_FILE not found. Run 'make setup' first."
    exit 1
  fi
  set -a; source "$ENV_FILE"; set +a

  while true; do
    local addr="${SERVER_ADDRESS:-localhost}"
    local proto_val="${REDIS_PROTO:-redis}"
    local tls_status="OFF"; [ "$proto_val" = "rediss" ] && tls_status="ON"
    local https_status="OFF"
    if echo "${MAIN_SERVER_URL:-}" | grep -qE "^https://"; then
      https_status="ON"
    fi

    echo ""
    echo "  ── Edit Server Config (.env) ──"
    echo "    1) Server address          [${addr:-not set}]"
    echo "    2) HTTPS                   [${https_status}]"
    echo "    3) Redis TLS               [${tls_status}]"
    echo "    4) Redis bind address      [$(get_val "$ENV_FILE" "REDIS_BIND")]"
    echo "    5) CORS origins            [$(get_val "$ENV_FILE" "CORS_ORIGINS")]"
    echo "    6) Nginx port (HTTP only)  [$(get_val "$ENV_FILE" "NGINX_PORT")]"
    echo "    7) HF cache directory      [$(get_val "$ENV_FILE" "HF_CACHE_DIR")]"
    echo "    8) Regenerate self-signed HTTPS certs"
    echo "    9) Open in \$EDITOR"
    echo "    0) Save and exit"
    echo ""
    read -p "  Choose: " CHOICE

    case "$CHOICE" in
      1)
        read -p "  Server address (IP or domain): " NEW_ADDR
        if [ -n "$NEW_ADDR" ]; then
          local proto="$(get_val "$ENV_FILE" "MAIN_SERVER_URL" | sed 's|://.*||')"
          proto="${proto:-http}"
          set_val "$ENV_FILE" "SERVER_ADDRESS" "$NEW_ADDR"
          set_val "$ENV_FILE" "MAIN_SERVER_URL" "${proto}://${NEW_ADDR}"
          echo "  ✔ Server address updated"
        fi
        ;;
      2)
        local current_proto="$(get_val "$ENV_FILE" "MAIN_SERVER_URL" | sed 's|://.*||')"
        local addr="$(get_val "$ENV_FILE" "SERVER_ADDRESS")"
        if [ "$current_proto" = "https" ]; then
          set_val "$ENV_FILE" "MAIN_SERVER_URL" "http://${addr}"
          echo "  ✔ HTTPS → OFF"
        else
          set_val "$ENV_FILE" "MAIN_SERVER_URL" "https://${addr}"
          echo "  ✔ HTTPS → ON"
          echo "  Note: Place server.crt + server.key in certs/ or regenerate (option 7)"
        fi
        ;;
      3)
        local current_proto="$(get_val "$ENV_FILE" "REDIS_PROTO")"
        if [ "$current_proto" = "rediss" ]; then
          set_val "$ENV_FILE" "REDIS_PROTO" "redis"
          for v in REDIS_SSL_CA_CERTS REDIS_SSL_CERTFILE REDIS_SSL_KEYFILE; do
            toggle_comment "$ENV_FILE" "$v" "comment"
          done
          echo "  ✔ Redis TLS → OFF"
        else
          set_val "$ENV_FILE" "REDIS_PROTO" "rediss"
          set_val "$ENV_FILE" "REDIS_SSL_CA_CERTS" "/etc/ssl/certs/redis/redis-ca.crt"
          set_val "$ENV_FILE" "REDIS_SSL_CERTFILE" "/etc/ssl/certs/redis/redis-client.crt"
          set_val "$ENV_FILE" "REDIS_SSL_KEYFILE" "/etc/ssl/certs/redis/redis-client.key"
          set_val "$ENV_FILE" "REDIS_SSL_CERT_REQS" "required"
          echo "  ✔ Redis TLS → ON"
          echo "  Note: Place TLS certs in certs/ or re-run make setup"
        fi
        ;;
      4)
        read -p "  Redis bind address [$(get_val "$ENV_FILE" "REDIS_BIND")]: " NEW_BIND
        if [ -n "$NEW_BIND" ]; then
          set_val "$ENV_FILE" "REDIS_BIND" "$NEW_BIND"
          echo "  ✔ Redis bind updated"
        fi
        ;;
      5)
        read -p "  CORS origins [$(get_val "$ENV_FILE" "CORS_ORIGINS")]: " NEW_CORS
        if [ -n "$NEW_CORS" ]; then
          set_val "$ENV_FILE" "CORS_ORIGINS" "$NEW_CORS"
          echo "  ✔ CORS origins updated"
        fi
        ;;
      6)
        local https_proto="$(get_val "$ENV_FILE" "MAIN_SERVER_URL" | sed 's|://.*||')"
        if [ "$https_proto" = "https" ]; then
          echo "  Nginx port is fixed to 443 when HTTPS is enabled."
        else
          read -p "  Nginx port [$(get_val "$ENV_FILE" "NGINX_PORT")]: " NEW_PORT
          if [ -n "$NEW_PORT" ]; then
            set_val "$ENV_FILE" "NGINX_PORT" "$NEW_PORT"
            local addr="$(get_val "$ENV_FILE" "SERVER_ADDRESS")"
            set_val "$ENV_FILE" "CORS_ORIGINS" "http://${addr}:${NEW_PORT}"
            echo "  ✔ Nginx port updated to ${NEW_PORT} (CORS also updated)"
          fi
        fi
        ;;
      7)
        read -p "  HF cache directory [$(get_val "$ENV_FILE" "HF_CACHE_DIR")]: " NEW_HF
        if [ -n "$NEW_HF" ]; then
          set_val "$ENV_FILE" "HF_CACHE_DIR" "$NEW_HF"
          echo "  ✔ HF cache directory updated"
        fi
        ;;
      8)
        if command -v openssl &>/dev/null; then
          local addr="$(get_val "$ENV_FILE" "SERVER_ADDRESS")"
          mkdir -p certs
          openssl genrsa -out certs/server.key 2048 2>/dev/null
          openssl req -new -x509 -key certs/server.key -out certs/server.crt \
            -days 365 -subj "/CN=${addr}" 2>/dev/null
          echo "  ✔ Self-signed HTTPS certs regenerated in certs/"
        else
          echo "  [ERROR] openssl not found"
        fi
        ;;
      9)
        ${EDITOR:-vi} "$ENV_FILE"
        echo "  ✔ Saved"
        ;;
      0)
        local addr="${SERVER_ADDRESS:-localhost}"
        echo ""
        echo "  ──────────────────────────────────────────────"
        echo "    Server address:     ${addr}"
        echo "    HTTPS:              ${https_status}"
        echo "    Redis TLS:          ${tls_status}"
        echo "  ──────────────────────────────────────────────"
        read -p "  Save and exit? [Y/n]: " EXIT_CONFIRM
        case "${EXIT_CONFIRM:-Y}" in
          n|N) echo "  Returning to menu..." ;;
          *) break ;;
        esac
        ;;
      *) echo "  Invalid option" ;;
    esac
  done
}

edit_worker() {
  if [ ! -f "$WORKER_FILE" ]; then
    echo "  [ERROR] $WORKER_FILE not found. Copy it from the server or run 'make worker'."
    exit 1
  fi
  set -a; source "$WORKER_FILE"; set +a

  while true; do
    local wtype="${WORKER_TYPE:-}"
    local gpu="${WORKER_GPU_ID:-}"
    local gpu_cores="${GPU_CORES_PER_TASK:-}"
    local cpu_cores="${CPU_CORES_PER_TASK:-}"
    local conc="${CELERY_WORKER_CONCURRENCY:-}"
    local mode="${WORKER_MODE:-docker}"

    local gpu_ram="${GPU_RAM_PER_TASK_GB:-8}"
    local cpu_ram="${CPU_RAM_PER_TASK_GB:-4}"
    local res_ram="${RESERVED_RAM_GB:-4}"
    local res_cores="${RESERVED_CPU_CORES:-1}"
    local clamp="${RAM_CLAMP_FACTOR:-1.05}"

    echo ""
    echo "  ── Edit Worker Config (worker.env) ──"
    echo "    1) Run mode              [${mode:-local}]"
    echo "    2) Worker type           [${wtype:-not set}]"
    echo "    3) GPU IDs               [${gpu:-none}]"
    echo "    4) CPU cores per GPU task [${gpu_cores:-not set}]"
    echo "    5) CPU cores per CPU task [${cpu_cores:-not set}]"
    echo "    6) Worker concurrency    [${conc:-auto}]"
    echo "    7) GPU RAM per task       [${gpu_ram} GB]"
    echo "    8) CPU RAM per task       [${cpu_ram} GB]"
    echo "    9) Reserved RAM (system)  [${res_ram} GB]"
    echo "   10) Reserved CPU cores     [${res_cores}]"
    echo "   11) Clamp factor           [${clamp}]"
    echo "   12) Open in \$EDITOR"
    echo "    0) Save and exit"
    echo ""
    read -p "  Choose: " CHOICE

    case "$CHOICE" in
      1)
        echo "  Run mode:"
        echo "    1) Docker"
        echo "    2) Local (micromamba)"
        read -p "  Choose [${mode:-1}]: " MODE_CHOICE
        case "${MODE_CHOICE:-1}" in
          2) set_val "$WORKER_FILE" "WORKER_MODE" "local" ;;
          *) set_val "$WORKER_FILE" "WORKER_MODE" "docker" ;;
        esac
        echo "  ✔ Run mode updated"
        ;;
      2)
        echo "  Worker type:"
        echo "    1) Evaluation tasks only"
        echo "    2) Internal tasks only"
        echo "    3) Both"
        read -p "  Choose: " WT_CHOICE
        case "$WT_CHOICE" in
          2) set_val "$WORKER_FILE" "WORKER_TYPE" "internal" ;;
          3) set_val "$WORKER_FILE" "WORKER_TYPE" "both" ;;
          1) set_val "$WORKER_FILE" "WORKER_TYPE" "eval" ;;
          *) echo "  Invalid" ;;
        esac
        echo "  ✔ Worker type updated"
        ;;
      3)
        read -p "  GPU IDs (comma-separated, empty for none): " NEW_GPU
        if [ -n "$NEW_GPU" ]; then
          set_val "$WORKER_FILE" "WORKER_GPU_ID" "$NEW_GPU"
        else
          sed -i.bak "/^WORKER_GPU_ID=/d" "$WORKER_FILE" && rm -f "$WORKER_FILE.bak"
        fi
        echo "  ✔ GPU IDs updated"
        ;;
      4)
        read -p "  CPU cores per GPU task [${gpu_cores:-4}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "GPU_CORES_PER_TASK" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      5)
        read -p "  CPU cores per CPU task [${cpu_cores:-2}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "CPU_CORES_PER_TASK" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      6)
        read -p "  Worker concurrency [${conc:-4}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "CELERY_WORKER_CONCURRENCY" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      7)
        read -p "  GPU RAM (GB) per task [${gpu_ram}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "GPU_RAM_PER_TASK_GB" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      8)
        read -p "  CPU RAM (GB) per task [${cpu_ram}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "CPU_RAM_PER_TASK_GB" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      9)
        read -p "  Reserved RAM (GB) for system [${res_ram}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "RESERVED_RAM_GB" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      10)
        read -p "  Reserved CPU cores for system [${res_cores}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          set_val "$WORKER_FILE" "RESERVED_CPU_CORES" "$NEW_VAL"
          echo "  ✔ Updated"
        fi
        ;;
      11)
        read -p "  Clamp factor (1.0 < x ≤ 1.10) [${clamp}]: " NEW_VAL
        if [ -n "$NEW_VAL" ]; then
          if (( $(echo "$NEW_VAL > 1.10" | bc -l) )) || (( $(echo "$NEW_VAL <= 1.0" | bc -l) )); then
            echo "  [ERROR] Clamp factor must be between 1.0 and 1.10"
          else
            set_val "$WORKER_FILE" "RAM_CLAMP_FACTOR" "$NEW_VAL"
            echo "  ✔ Updated"
          fi
        fi
        ;;
      12)
        ${EDITOR:-vi} "$WORKER_FILE"
        echo "  ✔ Saved"
        ;;
      0)
        echo ""
        echo "  ──────────────────────────────────────────────"
        echo "    Mode:              ${mode:-local}"
        echo "    Type:              ${wtype:-not set}"
        echo "    GPU IDs:           ${gpu:-none}"
        echo "    GPU cores/task:    ${gpu_cores:-not set}"
        echo "    GPU RAM/task:      ${gpu_ram} GB"
        echo "    CPU cores/task:    ${cpu_cores:-not set}"
        echo "    CPU RAM/task:      ${cpu_ram} GB"
        echo "    Reserved RAM:      ${res_ram} GB"
        echo "    Reserved cores:    ${res_cores}"
        echo "    Clamp factor:      ${clamp}"
        echo "    Concurrency:       ${conc:-auto}"
        echo "  ──────────────────────────────────────────────"
        read -p "  Save and exit? [Y/n]: " EXIT_CONFIRM
        case "${EXIT_CONFIRM:-Y}" in
          n|N) echo "  Returning to menu..." ;;
          *) break ;;
        esac
        ;;
      *) echo "  Invalid option" ;;
    esac
  done
}

# ── Main ────────────────────────────────────────────────────────────
echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║           Edit LavBench Configuration         ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

MODE="${1:-menu}"
case "$MODE" in
  server) edit_server ;;
  worker) edit_worker ;;
  menu)
    echo "  Which config to edit?"
    echo "    1) Server (.env)       — address, HTTPS, Redis TLS, CORS"
    echo "    2) Worker (worker.env)  — mode, type, GPU, cores, RAM"
    echo "    0) Exit"
    read -p "  Choose: " MODE_CHOICE
    case "$MODE_CHOICE" in
      1) edit_server ;;
      2) edit_worker ;;
    esac
    ;;
esac
echo ""
