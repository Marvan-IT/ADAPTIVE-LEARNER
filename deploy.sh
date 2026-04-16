#!/usr/bin/env bash
set -euo pipefail

# ── ADA EC2 Deploy Script ───────────────────────────────────────────────────
# Run this on a fresh EC2 instance (Ubuntu 22.04/24.04 LTS).
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh <your-domain.com> <your-email@example.com>
#
# Prerequisites (on your machine):
#   - EC2 instance running with ports 22, 80, 443 open
#   - SSH access configured
#   - Domain DNS A record pointing to the EC2 public IP

DOMAIN="${1:?Usage: ./deploy.sh <domain> <email>}"
EMAIL="${2:?Usage: ./deploy.sh <domain> <email>}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Deploying ADA to ${DOMAIN}"

# ── 1. Install Docker if not present ────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "==> Installing Docker..."
    sudo apt-get update -y
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "==> Docker installed. You may need to re-login for group changes."
fi

# ── 2. Validate .env files exist ────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: $APP_DIR/.env not found. Copy .env.example and fill in values."
    exit 1
fi
if [ ! -f "$APP_DIR/backend/.env" ]; then
    echo "ERROR: $APP_DIR/backend/.env not found. Copy backend/.env.example and fill in values."
    exit 1
fi

# ── 3. Generate nginx.conf from template with actual domain ─────────────────
echo "==> Generating frontend/nginx.conf for domain ${DOMAIN}"
export DOMAIN
envsubst '${DOMAIN}' < "$APP_DIR/frontend/nginx.conf.template" > "$APP_DIR/frontend/nginx.conf"

# ── 4. Create certbot directories ───────────────────────────────────────────
mkdir -p "$APP_DIR/certbot/conf" "$APP_DIR/certbot/www"

# ── 5. Bootstrap SSL — get initial certificate ──────────────────────────────
# First, start nginx with a self-signed cert so Certbot can complete the HTTP challenge.
echo "==> Creating temporary self-signed certificate..."
mkdir -p "$APP_DIR/certbot/conf/live/${DOMAIN}"
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "$APP_DIR/certbot/conf/live/${DOMAIN}/privkey.pem" \
    -out "$APP_DIR/certbot/conf/live/${DOMAIN}/fullchain.pem" \
    -subj "/CN=${DOMAIN}" 2>/dev/null

# Start only frontend (nginx) so port 80 is available for ACME challenge
echo "==> Starting nginx for ACME challenge..."
docker compose -f "$APP_DIR/docker-compose.yml" up -d frontend

# Wait for nginx to be ready
sleep 3

# Request real certificate
echo "==> Requesting Let's Encrypt certificate for ${DOMAIN}..."
docker run --rm \
    -v "$APP_DIR/certbot/conf:/etc/letsencrypt" \
    -v "$APP_DIR/certbot/www:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Stop the temporary nginx
docker compose -f "$APP_DIR/docker-compose.yml" down

# ── 6. Start the full stack ─────────────────────────────────────────────────
echo "==> Building and starting all services..."
docker compose -f "$APP_DIR/docker-compose.yml" up --build -d

# ── 7. Wait for DB and run migrations ───────────────────────────────────────
echo "==> Waiting for database..."
sleep 5
echo "==> Running Alembic migrations..."
docker compose -f "$APP_DIR/docker-compose.yml" exec backend python -m alembic upgrade head

# ── 8. Verify ────────────────────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  ADA deployed successfully!"
echo "  https://${DOMAIN}"
echo "========================================="
echo ""
echo "Useful commands:"
echo "  docker compose logs -f           # tail all logs"
echo "  docker compose logs -f backend   # tail backend only"
echo "  docker compose exec backend python -m alembic upgrade head  # run migrations"
echo "  docker compose down              # stop (keeps data)"
echo "  docker compose up --build -d     # rebuild and restart"
