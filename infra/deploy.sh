#!/usr/bin/env bash
# Deploy or update the Orrfin demo on one Ubuntu 24.04 server (BUILD_PLAN §10 F, Step 28).
#
#   sudo bash infra/deploy.sh             # deploy the branch or tag currently checked out
#   sudo bash infra/deploy.sh demo-20261120-1   # deploy (or roll back to) a git tag
#
# First run: installs Docker, adds swap on small machines, writes .env.production with random
# secrets, and gives the site an HTTPS address <public-ip>.sslip.io unless SITE_ADDRESS is set.
# Every run: builds the images, applies migrations, loads the demo data (safe to repeat), starts
# everything, and prints the demo link. Migrations are additive, so rolling back = deploying an
# older tag. Run it from the repository folder (e.g. /opt/orrfin).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env.production"
COMPOSE=(docker compose -f "$REPO_DIR/infra/docker-compose.prod.yml" --env-file "$ENV_FILE")
cd "$REPO_DIR"

say() { printf '\n==> %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash infra/deploy.sh" >&2
  exit 1
fi

# --- 1. Docker ---------------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker (first run only)"
  apt-get update -y
  apt-get install -y docker.io docker-compose-v2 git curl openssl
  systemctl enable --now docker
fi

# --- 2. Swap: building the web app needs more than 2 GB of memory ----------------------------
if [[ ! -f /swapfile ]] && (( $(awk '/MemTotal/ {print $2}' /proc/meminfo) < 6000000 )); then
  say "Adding a 4 GB swap file (first run only)"
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- 3. Which version ---------------------------------------------------------------------------
if [[ $# -ge 1 ]]; then
  say "Checking out $1"
  git fetch --tags --prune origin
  git checkout --quiet "$1"
else
  say "Updating the current branch"
  git pull --ff-only || echo "(not on a branch or no upstream: deploying what is checked out)"
fi
echo "Deploying $(git describe --tags --always) ($(git log -1 --format=%cd --date=short))"

# --- 4. Settings with secrets (first run only; never committed) --------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
  say "Writing .env.production with new random secrets (first run only)"
  if [[ -z "${SITE_ADDRESS:-}" ]]; then
    # AWS tells the server its public address; other clouds (Oracle, Google) don't answer this,
    # so fall back to asking a public "what is my IP" service.
    token=$(curl -fsS -m 3 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
    public_ip=$( [[ -n "$token" ]] && curl -fsS -m 3 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 || true)
    [[ -z "$public_ip" ]] && public_ip=$(curl -fsS -m 10 https://checkip.amazonaws.com | tr -d '[:space:]')
    if [[ ! "$public_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "Could not find this server's public IP. Run again as: SITE_ADDRESS=1-2-3-4.sslip.io bash infra/deploy.sh" >&2
      exit 1
    fi
    SITE_ADDRESS="${public_ip//./-}.sslip.io"
  fi
  db_password=$(openssl rand -hex 24)
  # A Fernet key: 32 random bytes, URL-safe base64 (ADR 0006).
  secret_key=$(openssl rand -base64 32 | tr '+/' '-_')
  demo_password="Demo-$(openssl rand -hex 4)"
  umask 077
  cat > "$ENV_FILE" <<EOF
# Orrfin demo server settings. Written by infra/deploy.sh. Keep this file on the server only.
APP_ENV=production
SITE_ADDRESS=$SITE_ADDRESS
PUBLIC_WEB_URL=https://$SITE_ADDRESS
CORS_ORIGINS=["https://$SITE_ADDRESS"]
SESSION_COOKIE_SECURE=true

POSTGRES_PASSWORD=$db_password
DATABASE_URL=postgresql+pg8000://orrfin:$db_password@postgres:5432/orrfin

# Encrypts ERP credentials saved on the Connectors page. Losing it means re-entering them.
ORRFIN_SECRET_KEY=$secret_key

# Password of the demo users (Riya, Arjun, Neha, Vikram, Anita, Sameer, Kabir).
ORRFIN_DEMO_PASSWORD=$demo_password

# AI (invoice reading, intake agent, assistant). Paste a Gemini key to switch it on.
AI_PROVIDER=gemini
GEMINI_API_KEY=
AWS_PROFILE=
EOF
  chmod 600 "$ENV_FILE"
fi

# --- 5. Build and start --------------------------------------------------------------------------
say "Building the images (the first build takes 5-10 minutes)"
"${COMPOSE[@]}" build

say "Starting the database"
"${COMPOSE[@]}" up -d postgres

say "Applying database migrations"
"${COMPOSE[@]}" run --rm api alembic upgrade head

say "Loading the demo data (safe to repeat)"
"${COMPOSE[@]}" run --rm api python -m app.seed_demo

say "Starting the API, worker, web app and HTTPS"
"${COMPOSE[@]}" up -d --remove-orphans

site=$(grep '^SITE_ADDRESS=' "$ENV_FILE" | cut -d= -f2)
password=$(grep '^ORRFIN_DEMO_PASSWORD=' "$ENV_FILE" | cut -d= -f2)
say "Done"
cat <<EOF
Demo link:      https://$site
Sign in as:     riya.requester@demo.orrfin.ai (or arjun.buyer, neha.approver, vikram.finance, anita.admin)
Password:       $password
The HTTPS certificate is issued on the first visit; if the page does not load, wait a minute and retry.
Logs:           sudo docker compose -f infra/docker-compose.prod.yml --env-file .env.production logs -f api
EOF
