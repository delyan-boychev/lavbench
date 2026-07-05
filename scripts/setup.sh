#!/usr/bin/env bash
# scripts/setup.sh — First-time environment & config for LavBench server.
# Called by: make setup-server
# Checks prerequisites, creates micromamba env, generates keys/config.
set -euo pipefail

echo ""
echo "  ╔════════════════════════════════════════════════╗"
echo "  ║           LavBench Server Setup               ║"
echo "  ╚════════════════════════════════════════════════╝"
echo ""

echo "  [1/3] Checking prerequisites..."

PREREQ_OK=true

if command -v micromamba &>/dev/null; then
  echo "    ✔ micromamba"
else
  echo "    ✘ micromamba not found"
  echo "       Install: curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba"
  PREREQ_OK=false
fi

if command -v docker &>/dev/null; then
  echo "    ✔ docker"
  if docker info &>/dev/null; then
    echo "    ✔ docker daemon"
  else
    echo "    ✘ docker daemon not running"
    PREREQ_OK=false
  fi
else
  echo "    ✘ docker not found — install from https://docs.docker.com/get-docker/"
  PREREQ_OK=false
fi

if command -v python3 &>/dev/null; then
  echo "    ✔ python3 ($(python3 --version 2>&1 | head -1))"
else
  echo "    ✘ python3 — install Python 3.12+"
  PREREQ_OK=false
fi

if command -v node &>/dev/null; then
  echo "    ✔ node ($(node --version 2>&1 | head -1))"
else
  echo "    ✘ node not found — install from https://nodejs.org/"
  PREREQ_OK=false
fi

if [ "$PREREQ_OK" = false ]; then
  echo ""
  echo "  [ERROR] Install missing prerequisites and re-run: make setup-server"
  exit 1
fi
echo ""

echo "  [2/3] Setting up Python environment..."
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

echo "    → Installing frontend dependencies..."
cd frontend
npm ci --silent 2>/dev/null || npm ci
cd ..
echo "    ✔ Frontend dependencies installed"
echo ""

echo "  [3/3] Generating configuration..."
bash scripts/generate-keys.sh

echo ""
echo "  ──────────────────────────────────────────────────────────────"
echo "    Next:"
echo "      make deploy-server   Deploy with Docker (production)"
echo "      make dev             Run locally (debug mode)"
echo "      make setup-admin     Create admin user"
echo "  ──────────────────────────────────────────────────────────────"
echo ""
