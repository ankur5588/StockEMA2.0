#!/usr/bin/env bash
# ChartinkTrade — One-command production bootstrap for Ubuntu 22.04 VPS.
#
# Usage:
#   sudo ./deploy.sh yourdomain.com you@example.com
#
# What it does (all idempotent — safe to re-run):
#   1. Installs Python 3.11, Node 18, Yarn, MongoDB 7, Nginx, Certbot, UFW
#   2. Creates /opt/chartink-trade with a dedicated `chartink` system user
#   3. Pulls the latest repo (if already cloned) or asks you to clone first
#   4. Generates a FERNET_KEY (saves a backup to /root/FERNET_KEY.backup)
#   5. Creates secure MongoDB users and enables auth
#   6. Writes backend/.env with the correct values
#   7. Builds Python venv, installs requirements + Kotak/Dhan/Alice SDKs + yfinance
#   8. Builds React frontend pointing at https://<domain>
#   9. Installs systemd service `chartink-backend` (--workers 1 for session safety)
#  10. Installs Nginx reverse proxy + enables HTTPS via Let's Encrypt
#  11. Configures UFW firewall (22 / 80 / 443 only)
#  12. Prints verification commands + broker whitelist reminder
#
# Prerequisites:
#   * Fresh Ubuntu 22.04 LTS VPS with a RESERVED STATIC IP
#   * DNS A record for <domain> pointing to the VPS IP
#   * You've run:  git clone <your-fork-url> /opt/chartink-trade
#     (or the script will prompt you to do so)
set -euo pipefail

# ---------- args ----------
DOMAIN="${1:-}"
CONTACT_EMAIL="${2:-}"
STATIC_IP="$(curl -s https://api.ipify.org)"
if [[ -z "$DOMAIN" ]]; then
    DOMAIN="${STATIC_IP}.nip.io"
    CONTACT_EMAIL="${CONTACT_EMAIL:-admin@${DOMAIN}}"
    warn "No domain provided — using nip.io temp URL: http://${DOMAIN}"
elif [[ -z "$CONTACT_EMAIL" ]]; then
    CONTACT_EMAIL="admin@${DOMAIN}"
fi
if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run as root: sudo $0 ..."
    exit 1
fi

APP_DIR="/opt/chartink-trade"
APP_USER="chartink"
VENV_DIR="$APP_DIR/backend/.venv"
DB_NAME="chartink_trade_prod"
STATE_FILE="/root/.chartink-deploy-state"

log()  { echo -e "\n\033[1;34m[deploy]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ok]\033[0m $*"; }

# ---------- 0. sanity ----------
log "0/12 Sanity checks"
if ! grep -qiE "ubuntu (22|24)" /etc/os-release; then
    warn "This script is tested on Ubuntu 22.04/24.04. Continue at your own risk."
fi
if [[ ! -d "$APP_DIR" ]]; then
    warn "Expected repo at $APP_DIR. Clone it first:"
    echo "    git clone <your-github-repo-url> $APP_DIR"
    exit 1
fi
STATIC_IP="$(curl -s https://api.ipify.org)"
log "Detected outbound IP: $STATIC_IP"

# ---------- 1. apt packages ----------
log "1/12 Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -yq software-properties-common gnupg curl ca-certificates ufw git build-essential
# Python
PY_CMD="python3"
if command -v python3.12 &>/dev/null; then
    PY_CMD="python3.12"
elif command -v $PY_CMD &>/dev/null; then
    PY_CMD=python3
fi
add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
apt-get update -qq
apt-get install -yq $PY_CMD $PY_CMD-venv $PY_CMD-dev
# Node 18 + Yarn
if ! command -v node >/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - >/dev/null
    apt-get install -yq nodejs
fi
npm install -g yarn >/dev/null 2>&1 || true
# MongoDB 7
if ! command -v mongod >/dev/null; then
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
    echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
        > /etc/apt/sources.list.d/mongodb-org-7.0.list
    apt-get update -qq
    apt-get install -yq mongodb-org
    systemctl enable --now mongod
fi
# Nginx + Certbot
apt-get install -yq nginx certbot python3-certbot-nginx
ok "System packages ready"

# ---------- 2. app user ----------
log "2/12 Creating $APP_USER user"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd -r -m -d "/home/$APP_USER" -s /bin/bash "$APP_USER"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ---------- 3. git pull latest ----------
if [[ "${CI:-}" != "true" ]]; then
    log "3/12 Pulling latest code"
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only || warn "git pull failed — continuing with current checkout"
else
    log "3/12 Skipping git pull (CI/CD deployment — files already synced)"
fi

# ---------- 4. FERNET_KEY ----------
log "4/12 Ensuring FERNET_KEY exists"
FERNET_KEY_FILE="/root/.chartink_fernet_key"
if [[ ! -f "$FERNET_KEY_FILE" ]]; then
    $PY_CMD -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > "$FERNET_KEY_FILE" 2>/dev/null || \
        python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" > "$FERNET_KEY_FILE"
    chmod 600 "$FERNET_KEY_FILE"
    cp "$FERNET_KEY_FILE" "/root/FERNET_KEY.backup"
    warn "!!!  FERNET_KEY generated and backed up to /root/FERNET_KEY.backup"
    warn "!!!  COPY THIS SOMEWHERE SAFE. Losing it = losing all saved broker credentials."
fi
FERNET_KEY="$(cat "$FERNET_KEY_FILE")"

# ---------- 4b. JWT_SECRET ----------
log "4b/12 Ensuring JWT_SECRET exists"
JWT_SECRET_FILE="/root/.chartink_jwt_secret"
if [[ ! -f "$JWT_SECRET_FILE" ]]; then
    openssl rand -base64 32 | tr -d '\n' > "$JWT_SECRET_FILE"
    chmod 600 "$JWT_SECRET_FILE"
    warn "JWT_SECRET generated and saved to $JWT_SECRET_FILE"
fi
JWT_SECRET="$(cat "$JWT_SECRET_FILE")"

# ---------- 5. MongoDB auth ----------
log "5/12 Configuring MongoDB authentication"
MONGO_APP_PWD_FILE="/root/.chartink_mongo_app_pwd"
MONGO_ROOT_PWD_FILE="/root/.chartink_mongo_root_pwd"
if [[ ! -f "$MONGO_APP_PWD_FILE" ]]; then
    openssl rand -base64 24 | tr -d '\n' > "$MONGO_APP_PWD_FILE"
    chmod 600 "$MONGO_APP_PWD_FILE"
fi
if [[ ! -f "$MONGO_ROOT_PWD_FILE" ]]; then
    openssl rand -base64 24 | tr -d '\n' > "$MONGO_ROOT_PWD_FILE"
    chmod 600 "$MONGO_ROOT_PWD_FILE"
fi
MONGO_APP_PWD="$(cat "$MONGO_APP_PWD_FILE")"
MONGO_ROOT_PWD="$(cat "$MONGO_ROOT_PWD_FILE")"

if ! grep -q "authorization: enabled" /etc/mongod.conf; then
    mongosh --quiet --eval "
        db = db.getSiblingDB('admin');
        if (!db.getUser('admin')) {
            db.createUser({user:'admin', pwd:'$MONGO_ROOT_PWD', roles:['root']});
        }
        db = db.getSiblingDB('$DB_NAME');
        if (!db.getUser('chartink')) {
            db.createUser({user:'chartink', pwd:'$MONGO_APP_PWD', roles:[{role:'readWrite', db:'$DB_NAME'}]});
        }
    " >/dev/null
    echo "security:
  authorization: enabled" >> /etc/mongod.conf
    systemctl restart mongod
    sleep 3
fi
ok "MongoDB auth enabled. Passwords in $MONGO_APP_PWD_FILE and $MONGO_ROOT_PWD_FILE"

# ---------- 6. backend .env ----------
log "6/12 Writing backend/.env"
ENV_FILE="$APP_DIR/backend/.env"
MONGO_APP_PWD_ENC=$($PY_CMD -c "import urllib.parse, sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$MONGO_APP_PWD")
if [[ "$DOMAIN" == *".nip.io" ]]; then
    PROTO="http"
else
    PROTO="https"
fi
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@chartink.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123}"
cat > "$ENV_FILE" <<EOF
MONGO_URL=mongodb://chartink:${MONGO_APP_PWD_ENC}@127.0.0.1:27017/${DB_NAME}?authSource=${DB_NAME}
DB_NAME=${DB_NAME}
CORS_ORIGINS=${PROTO}://${DOMAIN},${PROTO}://www.${DOMAIN}
FERNET_KEY=${FERNET_KEY}
JWT_SECRET=${JWT_SECRET}
STATIC_IP_DEPLOYMENT=true
DEPLOYMENT_NAME=${DOMAIN}
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
EOF
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ---------- 7. Python venv + deps ----------
log "7/12 Installing Python dependencies"
if [[ ! -d "$VENV_DIR" ]]; then
    sudo -u "$APP_USER" $PY_CMD -m venv "$VENV_DIR"
fi
sudo -u "$APP_USER" bash -lc "
    source '$VENV_DIR/bin/activate'
    pip install --upgrade pip wheel
    pip install -r '$APP_DIR/backend/requirements.txt'
    # SDKs not in requirements.txt (version pin conflicts)
    pip install 'git+https://github.com/Kotak-Neo/kotak-neo-api.git'
    pip install dhanhq pya3 yfinance delta-rest-client
"
ok "Python deps installed"

# ---------- 8. frontend build ----------
log "8/12 Building frontend for $DOMAIN"
# Use empty REACT_APP_BACKEND_URL so API calls go to same origin (nginx proxies /api/)
cat > "$APP_DIR/frontend/.env" <<EOF
REACT_APP_BACKEND_URL=
EOF
chown "$APP_USER:$APP_USER" "$APP_DIR/frontend/.env"
sudo -u "$APP_USER" bash -lc "
    cd '$APP_DIR/frontend'
    yarn install --frozen-lockfile 2>/dev/null || yarn install
    yarn build
"
ok "Frontend built → $APP_DIR/frontend/build"

# ---------- 9. systemd service ----------
log "9/12 Installing systemd service"
cat > /etc/systemd/system/chartink-backend.service <<EOF
[Unit]
Description=ChartinkTrade FastAPI backend
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$VENV_DIR/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 1
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/chartink-backend.log
StandardError=append:/var/log/chartink-backend.err.log

[Install]
WantedBy=multi-user.target
EOF

touch /var/log/chartink-backend.log /var/log/chartink-backend.err.log
chown "$APP_USER:$APP_USER" /var/log/chartink-backend.*

systemctl daemon-reload
systemctl enable chartink-backend
systemctl restart chartink-backend
sleep 3
systemctl is-active chartink-backend >/dev/null || {
    warn "Backend service not active. Last 20 log lines:"
    tail -n 20 /var/log/chartink-backend.err.log
    exit 1
}
ok "chartink-backend service running on 127.0.0.1:8001"

# ---------- 10. nginx ----------
log "10/12 Configuring Nginx"
NGX_FILE="/etc/nginx/sites-available/chartink"
cat > "$NGX_FILE" <<EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

    # Serve React build
    root $APP_DIR/frontend/build;
    index index.html;

    location / {
        try_files \$uri /index.html;
    }

    # API + webhook proxy
    location /api/ {
        proxy_pass         http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_set_header   X-Forwarded-Host  \$host;
        proxy_read_timeout 30s;
    }

    client_max_body_size 2M;
}
EOF
ln -sf "$NGX_FILE" /etc/nginx/sites-enabled/chartink
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
ok "Nginx HTTP config active"

# ---------- 11. HTTPS via certbot ----------
log "11/12 Checking Let's Encrypt certificate"
if [[ "$DOMAIN" != *".nip.io" ]]; then
    if ! certbot certificates 2>/dev/null | grep -q "$DOMAIN"; then
        certbot --nginx --non-interactive --agree-tos --redirect \
            -m "$CONTACT_EMAIL" -d "$DOMAIN" -d "www.$DOMAIN"
    else
        ok "Certificate already exists for $DOMAIN"
    fi
else
    ok "Skipping certbot for nip.io domain"
fi
systemctl reload nginx

# ---------- 12. firewall ----------
log "12/12 Firewall (UFW)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ok "Firewall active (22, 80, 443 only)"

# ---------- final report ----------
echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  App URL:         https://${DOMAIN}"
echo "  Backend API:     https://${DOMAIN}/api/health"
echo "  Compliance:      https://${DOMAIN}/api/deployment/info"
echo "  Outbound IP:     ${STATIC_IP}"
echo ""
echo "  Secrets (keep safe):"
echo "    FERNET_KEY       $FERNET_KEY_FILE   (also /root/FERNET_KEY.backup)"
echo "    Mongo app pwd    $MONGO_APP_PWD_FILE"
echo "    Mongo root pwd   $MONGO_ROOT_PWD_FILE"
echo ""
echo "  Logs:"
echo "    journalctl -u chartink-backend -f"
echo "    tail -f /var/log/chartink-backend.err.log"
echo ""
echo "  Next — whitelist THIS IP with your brokers:"
echo "    • Dhan        web.dhan.co → Profile → Access DhanHQ APIs → add ${STATIC_IP}"
echo "    • Kotak Neo   Neo app → Profile → Trade API → API Dashboard → add ${STATIC_IP}"
echo "    • Alice Blue  ant.aliceblueonline.com → Apps → add ${STATIC_IP}"
echo ""
echo "  Verify compliance card is GREEN after login:"
echo "    curl -s https://${DOMAIN}/api/deployment/info | jq"
echo ""

date -u +"%FT%TZ deployment complete" >> "$STATE_FILE"
