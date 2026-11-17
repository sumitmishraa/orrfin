#!/usr/bin/env bash
# Run the whole Orrfin demo on a Mac or Linux laptop with Docker Desktop (Step 28 package, local use).
#
#   ./scripts/demo-local.sh          # build (first time 5-10 min), load the demo company, start
#   ./scripts/demo-local.sh --stop   # stop everything; the data is kept
#   ./scripts/demo-local.sh --reset  # stop and delete the demo data (the next start loads it fresh)
#
# It runs the same containers as the AWS server (infra/docker-compose.prod.yml): database, API,
# worker, web app and Caddy, which serves https://localhost with a certificate the browser does not
# know yet (one "Proceed" click the first time). Windows users run scripts/dev.ps1 instead.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env.production"
COMPOSE=(docker compose -f "$REPO_DIR/infra/docker-compose.prod.yml" --env-file "$ENV_FILE")
cd "$REPO_DIR"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Open Docker Desktop, wait until it says 'Engine running', then run this again." >&2
  exit 1
fi

case "${1:-}" in
  --stop)  "${COMPOSE[@]}" down; echo "Stopped. Your demo data is kept."; exit 0 ;;
  --reset) "${COMPOSE[@]}" down -v; echo "Stopped and deleted the demo data."; exit 0 ;;
  "") ;;
  *) echo "Unknown option $1. Use --stop or --reset, or nothing to start." >&2; exit 1 ;;
esac

if [[ -f "$ENV_FILE" ]] && ! grep -q '^SITE_ADDRESS=localhost$' "$ENV_FILE"; then
  echo ".env.production here belongs to a server (SITE_ADDRESS is not localhost). Not touching it." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "==> Writing local settings (.env.production, never committed)"
  db_password=$(openssl rand -hex 24)
  secret_key=$(openssl rand -base64 32 | tr '+/' '-_')
  umask 077
  cat > "$ENV_FILE" <<EOF
# Local demo settings for scripts/demo-local.sh. Synthetic data only.
APP_ENV=production
SITE_ADDRESS=localhost
PUBLIC_WEB_URL=https://localhost
CORS_ORIGINS=["https://localhost"]
SESSION_COOKIE_SECURE=true
POSTGRES_PASSWORD=$db_password
DATABASE_URL=postgresql+pg8000://orrfin:$db_password@postgres:5432/orrfin
ORRFIN_SECRET_KEY=$secret_key
# The README password, because this copy runs only on your own laptop.
ORRFIN_DEMO_PASSWORD=Orrfin@Demo2026
# Paste a Gemini key here to switch on AI reading and the assistant (optional).
AI_PROVIDER=gemini
GEMINI_API_KEY=
AWS_PROFILE=
EOF
fi

echo "==> Building (the first time takes 5-10 minutes)"
"${COMPOSE[@]}" build
echo "==> Starting the database"
"${COMPOSE[@]}" up -d postgres
echo "==> Setting up the database"
"${COMPOSE[@]}" run --rm api alembic upgrade head
echo "==> Loading the demo company (safe to repeat)"
"${COMPOSE[@]}" run --rm api python -m app.seed_demo
echo "==> Starting the app"
"${COMPOSE[@]}" up -d --remove-orphans

cat <<EOF

Orrfin is running:  https://localhost
Sign in as:         riya.requester@demo.orrfin.ai  (or arjun.buyer, neha.approver, vikram.finance, anita.admin)
Password:           Orrfin@Demo2026
First visit: the browser warns about the certificate. Chrome: Advanced -> Proceed to localhost.
Safari: Show Details -> visit this website. It is your own laptop, so this is safe.
Stop with:          ./scripts/demo-local.sh --stop
EOF
