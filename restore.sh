#!/usr/bin/env bash
# restore.sh — Carls_Homelab
# Rebuilds the Pi homelab stack from scratch.
# Run as the pi user (uses sudo internally where needed).
# Usage: bash restore.sh
# Prerequisites: fresh Pi OS Lite 64-bit, internet connection, this repo cloned.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_USER="${USER:-pi}"

echo "============================================================"
echo "  Carls_Homelab — Restore Script"
echo "  Repo: $REPO_DIR"
echo "  User: $PI_USER"
echo "============================================================"
echo ""

# ── 1. System update ───────────────────────────────────────────────
echo "[1/10] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# ── 2. Install base dependencies ───────────────────────────────────
echo "[2/10] Installing dependencies..."
sudo apt install -y   curl git fail2ban avahi-daemon unattended-upgrades   mosquitto mosquitto-clients   python3

# ── 3. Docker ──────────────────────────────────────────────────────
echo "[3/10] Installing Docker..."
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$PI_USER"
sudo systemctl enable docker

# ── 4. Tailscale ───────────────────────────────────────────────────
echo "[4/10] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
echo "  --> Run: sudo tailscale up"
echo "  --> Then disable key expiry in Tailscale admin console"

# ── 5. Cloudflare tunnel ───────────────────────────────────────────
echo "[5/10] Installing cloudflared..."
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install -y cloudflared
echo "  --> Run: cloudflared tunnel login"
echo "  --> Then: cloudflared tunnel create homelab"
echo "  --> Copy tunnel credentials JSON to /home/$PI_USER/.cloudflared/"

# ── 6. Caddy (custom patched build) ────────────────────────────────
echo "[6/10] Building patched Caddy..."
# Install Go
curl -fsSL https://go.dev/dl/go1.22.0.linux-arm64.tar.gz -o /tmp/go.tar.gz
sudo tar -C /usr/local -xzf /tmp/go.tar.gz
export PATH=$PATH:/usr/local/go/bin
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc

# Install xcaddy
go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest

# Clone patched cloudflare module
mkdir -p ~/caddy-cloudflare-patched
cd ~/caddy-cloudflare-patched
git clone https://github.com/caddy-dns/cloudflare . 2>/dev/null || true
# Patch: extend token regex from {35,50} to {35,100}
sed -i 's/{35,50}/{35,100}/g' cloudflare.go 2>/dev/null || true

# Build
~/go/bin/xcaddy build --with github.com/caddy-dns/cloudflare=.
sudo mv caddy /usr/bin/caddy
sudo setcap cap_net_bind_service=+ep /usr/bin/caddy
cd ~

# ── 7. Authelia ────────────────────────────────────────────────────
echo "[7/10] Installing Authelia..."
AUTHELIA_VERSION="4.39.16"
curl -fsSL "https://github.com/authelia/authelia/releases/download/v${AUTHELIA_VERSION}/authelia-linux-arm64.tar.gz" \
  -o /tmp/authelia.tar.gz
tar -xzf /tmp/authelia.tar.gz -C /tmp
sudo mv /tmp/authelia-linux-arm64 /usr/local/bin/authelia
sudo chmod +x /usr/local/bin/authelia

# Restore configs
sudo mkdir -p /etc/authelia
sudo cp "$REPO_DIR/authelia/configuration.yml" /etc/authelia/
echo "  --> Manually restore /etc/authelia/users.yml from password manager"
echo "  --> Re-register TOTP in Google Authenticator after first login"

# Create systemd service
sudo tee /etc/systemd/system/authelia.service > /dev/null << 'SVCEOF'
[Unit]
Description=Authelia authentication service
After=network.target

[Service]
User=root
ExecStart=/usr/local/bin/authelia --config /etc/authelia/configuration.yml
Restart=on-failure

[Install]
WantedBy=multi-user.target
SVCEOF
sudo systemctl daemon-reload
sudo systemctl enable authelia

# ── 8. Restore service configs ─────────────────────────────────────
echo "[8/10] Restoring service configs..."

# Caddy
sudo mkdir -p /etc/caddy
sudo cp "$REPO_DIR/caddy/Caddyfile" /etc/caddy/
echo "  --> Add CLOUDFLARE_API_TOKEN to Caddy environment"

# cloudflared
sudo mkdir -p /etc/cloudflared
sudo cp "$REPO_DIR/cloudflared/config.yml" /etc/cloudflared/
echo "  --> Restore tunnel credentials JSON to /home/$PI_USER/.cloudflared/"

# Mosquitto
sudo cp "$REPO_DIR/mosquitto/mosquitto.conf" /etc/mosquitto/
echo "  --> Run: sudo mosquitto_passwd -c /etc/mosquitto/passwd mqttuser"
echo "  --> Run: sudo chown mosquitto:mosquitto /etc/mosquitto/passwd"

# Home Assistant config
sudo mkdir -p /etc/homeassistant
sudo cp "$REPO_DIR/homeassistant/configuration.yaml" /etc/homeassistant/

# Filebrowser
sudo mkdir -p /etc/filebrowser /srv/filebrowser
curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
echo "  --> Re-run filebrowser config init and users add after restore"

# Passives Tracker
mkdir -p ~/passives-stock
cp "$REPO_DIR/passives-stock/"* ~/passives-stock/ 2>/dev/null || true
mkdir -p ~/.config/systemd/user/
cp "$REPO_DIR/systemd/passives-stock.service" ~/.config/systemd/user/
sudo loginctl enable-linger "$PI_USER"

# ── 9. Start Docker services ───────────────────────────────────────
echo "[9/10] Starting Docker services..."

# Cloudflare DDNS
sudo docker run -d \
  --name cloudflare-ddns \
  --restart unless-stopped \
  -e CF_API_TOKEN="${CF_API_TOKEN:-REPLACE_ME}" \
  -e DOMAINS="highcarlsagan.dev" \
  -e PROXIED=false \
  favonia/cloudflare-ddns:1

# Pi-hole
sudo docker run -d \
  --name pihole \
  --network host \
  --restart unless-stopped \
  -e TZ="Asia/Kolkata" \
  -e FTLCONF_webserver_port="8888" \
  -e FTLCONF_dns_listeningMode="all" \
  -e WEBPASSWORD="${PIHOLE_PASSWORD:-changeme}" \
  -v /etc/pihole:/etc/pihole \
  -v /etc/dnsmasq.d:/etc/dnsmasq.d \
  pihole/pihole:latest

# Home Assistant
sudo docker run -d \
  --name homeassistant \
  --privileged \
  --network host \
  --restart unless-stopped \
  -e TZ="Asia/Kolkata" \
  -v /etc/homeassistant:/config \
  -v /run/dbus:/run/dbus:ro \
  ghcr.io/home-assistant/home-assistant:stable

# ── 10. Start all services ─────────────────────────────────────────
echo "[10/10] Enabling and starting services..."
sudo systemctl enable --now fail2ban
sudo systemctl enable --now avahi-daemon
sudo systemctl enable --now mosquitto
sudo systemctl enable --now authelia
sudo systemctl enable --now caddy
sudo systemctl enable --now cloudflared
systemctl --user daemon-reload
systemctl --user enable --now passives-stock.service

echo ""
echo "============================================================"
echo "  Restore complete — manual steps remaining:"
echo ""
echo "  1. sudo tailscale up (authenticate Tailscale)"
echo "  2. Restore /etc/authelia/users.yml from password manager"
echo "  3. Add CLOUDFLARE_API_TOKEN to Caddy environment"
echo "  4. Restore tunnel credentials JSON"
echo "  5. sudo mosquitto_passwd -c /etc/mosquitto/passwd mqttuser"
echo "     sudo chown mosquitto:mosquitto /etc/mosquitto/passwd"
echo "  6. Re-run filebrowser config init + users add"
echo "  7. Re-register TOTP in Google Authenticator"
echo "  8. Enable Tailscale DNS override in admin console"
echo "  9. Rebuild Caddy patch if token regex breaks again"
echo "============================================================"
