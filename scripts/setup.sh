#!/usr/bin/env bash
# scripts/setup.sh — First-time setup for LavBench.
# Called by: make setup
set -euo pipefail

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║           LavBench Setup                       ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

# ── Determine mode: server or worker ────────────────────────────────
MODE="${1:-server}"
echo "  Mode: $MODE"
echo ""

# ── Prerequisites ──────────────────────────────────────────────────
echo "  [1/5] Checking prerequisites..."

PREREQ_OK=true

if command -v micromamba &>/dev/null; then
  echo "    ✔ micromamba"
else
  cat <<INSTALL
    ✘ micromamba not found
       Install with (Linux/macOS):
         curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
         mv bin/micromamba ~/.local/bin/
         export PATH=\$HOME/.local/bin:\$PATH
       Or (macOS ARM):
         curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xvj bin/micromamba
       Full docs: https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html
INSTALL
  PREREQ_OK=false
fi

if command -v docker &>/dev/null; then
  echo "    ✔ docker"
  if docker info &>/dev/null; then
    echo "    ✔ docker daemon"
  else
    echo "    ✘ docker daemon not running — start Docker Desktop or: dockerd &"
    PREREQ_OK=false
  fi
else
  cat <<INSTALL
    ✘ docker not found
       Install: https://docs.docker.com/get-docker/
       macOS:   brew install --cask docker
       Ubuntu:  sudo apt-get install docker.io && sudo systemctl enable --now docker
INSTALL
  PREREQ_OK=false
fi

if command -v python3 &>/dev/null; then
  echo "    ✔ python3 ($(python3 --version 2>&1 | head -1))"
else
  echo "    ✘ python3 — install Python 3.12+ from https://python.org"
  PREREQ_OK=false
fi

if [ "$MODE" = "server" ]; then
  if command -v node &>/dev/null; then
    echo "    ✔ node ($(node --version 2>&1 | head -1))"
  else
    cat <<INSTALL
    ✘ node not found
       Install: https://nodejs.org/
       macOS:   brew install node
       Ubuntu:  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs
INSTALL
    PREREQ_OK=false
  fi
fi

if [ "$PREREQ_OK" = false ]; then
  echo ""
  echo "  [ERROR] Install missing prerequisites and re-run: make setup"
  exit 1
fi
echo ""

# ── Micromamba environment (server mode) ────────────────────────────
if [ "$MODE" = "server" ]; then
  echo "  [2/5] Creating Python environment..."

  eval "$(micromamba shell hook --shell bash 2>/dev/null)"

  if ! micromamba env list | grep -q "lavbench_backend"; then
    echo "    → Creating micromamba environment 'lavbench_backend'..."
    micromamba create -n lavbench_backend python=3.12 -y -q
  fi

  micromamba activate lavbench_backend
  echo "    ✔ micromamba env 'lavbench_backend' (Python 3.12)"

  echo "    → Installing pip dependencies..."
  pip install -q -r backend/requirements.txt -r backend/dev-requirements.txt
  echo "    ✔ pip dependencies installed"
  echo ""

  # ── Generate config ─────────────────────────────────────────────────
  echo "  [3/5] Generating configuration..."
  bash scripts/generate-keys.sh
  echo "    ✔ Configuration generated"
  echo ""

  # ── Frontend ────────────────────────────────────────────────────────
  echo "  [4/5] Installing frontend dependencies..."
  cd frontend
  npm ci --silent 2>/dev/null || npm ci
  cd ..
  echo "    ✔ Frontend dependencies installed"
  echo ""

  # ── Complete ────────────────────────────────────────────────────────
  echo "  [5/5] Done!"
  echo ""
  echo "  ──────────────────────────────────────────────────────────────"
  echo "    Next (server):"
  echo "      make dev                  Start all services locally"
  echo "      make deploy-docker        Full Docker Compose deployment"
  echo "      python backend/setup-admin.py   Create admin user"
  echo ""
  echo "    Workers:"
  echo "      scp worker.env user@your-server:~/"
  echo "      On worker: make setup-worker   (one-time prereq check + image build)
      On worker: make worker         (interactive first-run, then start)"
  echo "  ──────────────────────────────────────────────────────────────"
fi

# ── Worker mode ─────────────────────────────────────────────────────
if [ "$MODE" = "worker" ]; then
  echo "  [2/2] Building worker Docker image..."
  docker build -t lavbench-worker -f backend/Dockerfile.worker backend/
  echo ""
  echo "  ──────────────────────────────────────────────────────────────"
  echo "    Worker ready!"
  echo "      make worker           Interactive first-run, then start"
  echo "  ──────────────────────────────────────────────────────────────"
fi
echo ""
