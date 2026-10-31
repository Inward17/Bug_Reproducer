#!/usr/bin/env bash
# =============================================================
# AutoRepro — EC2 setup script
# Run once on a fresh Ubuntu 24.04 instance:  bash setup.sh
#
# Docker commands run through sudo, because group membership added by this
# script only applies to a new login session. Log out and back in afterwards
# to use docker without sudo.
# =============================================================

set -euo pipefail

REPO_URL="${AUTOREPRO_REPO_URL:-https://github.com/Inward17/Bug_Reproducer.git}"
REPO_DIR="${AUTOREPRO_REPO_DIR:-Bug_Reproducer}"

echo
echo "======================================"
echo "  AutoRepro EC2 Setup — Starting..."
echo "======================================"
echo

# --------------------------------------------------------------
# 1. System packages
# --------------------------------------------------------------
echo "[1/7] Updating system packages..."
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo apt-get install -y curl git unzip jq

# --------------------------------------------------------------
# 2. Docker
# --------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  echo "[2/7] Docker already installed, skipping."
else
  echo "[2/7] Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
sudo apt-get install -y docker-compose-plugin
sudo usermod -aG docker "$USER"

# --------------------------------------------------------------
# 3. Repository
# --------------------------------------------------------------
echo "[3/7] Fetching AutoRepro..."
if [ -d "$REPO_DIR/.git" ]; then
  echo "  -> $REPO_DIR exists, pulling latest..."
  git -C "$REPO_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# --------------------------------------------------------------
# 4. Environment file
# --------------------------------------------------------------
echo "[4/7] Setting up environment variables..."
if [ -f ".env.production" ]; then
  echo "  -> .env.production already exists, keeping it."
else
  cp .env.production.template .env.production
  echo
  echo "  ACTION REQUIRED: fill in your API keys."
  echo "    \$ nano $(pwd)/.env.production"
  echo
  echo "  At minimum set LLM_PROVIDER and that provider's key. Before putting this"
  echo "  host on the public internet also set API_KEY and ALLOW_PRIVATE_TARGETS=false."
  echo
  # Read from the terminal, not from stdin: stdin may be a pipe (curl | bash).
  # /dev/tty can exist without being openable (ssh without -t), so try opening it.
  if { : < /dev/tty; } 2>/dev/null; then
    read -r -p "  Press ENTER once .env.production is filled in... " _ < /dev/tty
  else
    echo "  Non-interactive shell: edit .env.production, then re-run this script."
    exit 1
  fi
fi

# --------------------------------------------------------------
# 5. Data directories
# --------------------------------------------------------------
echo "[5/7] Creating data directories..."
mkdir -p data/jobs data/artifacts
chmod 755 data

# Compose reads .env for variable substitution. HOST_DATA_DIR must be an absolute host
# path, and writing it here keeps it correct under sudo, which clears $PWD.
if grep -q '^HOST_DATA_DIR=' .env 2>/dev/null; then
  sed -i "s|^HOST_DATA_DIR=.*|HOST_DATA_DIR=$(pwd)/data|" .env
else
  echo "HOST_DATA_DIR=$(pwd)/data" >> .env
fi

# --------------------------------------------------------------
# 6. Images
# --------------------------------------------------------------
echo "[6/7] Building Docker images (this may take 5-10 minutes)..."
sudo docker compose --profile build-only -f docker-compose.prod.yml build

# --------------------------------------------------------------
# 7. Start
# --------------------------------------------------------------
echo "[7/7] Starting AutoRepro..."
sudo docker compose -f docker-compose.prod.yml up -d

PUBLIC_HOST="$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-hostname || true)"

echo
echo "======================================"
echo "  AutoRepro is running"
echo "======================================"
echo
echo "  Local URL:   http://localhost:8000"
if [ -n "$PUBLIC_HOST" ]; then
  echo "  Public URL:  http://$PUBLIC_HOST:8000"
else
  echo "  Public URL:  run 'curl -s http://169.254.169.254/latest/meta-data/public-hostname'"
fi
echo
echo "  Useful commands:"
echo "  - View logs:   sudo docker compose -f docker-compose.prod.yml logs -f"
echo "  - Stop app:    sudo docker compose -f docker-compose.prod.yml down"
echo "  - Restart app: sudo docker compose -f docker-compose.prod.yml restart"
echo
echo "  Log out and back in to run docker without sudo."
echo
