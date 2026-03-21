# Carls_Homelab

Personal homelab configuration backup for a Raspberry Pi 4 running a self-hosted stack — Caddy, Authelia, Cloudflare Tunnel, Pi-hole, Home Assistant, Mosquitto, and Filebrowser — accessible remotely via Tailscale and secured with 2FA.

---

## Infrastructure

| Item | Value |
|---|---|
| Hardware | Raspberry Pi 4 |
| OS | Raspberry Pi OS Lite 64-bit (Bookworm) |
| Hostname | 4pi.local |
| LAN IP | 192.168.0.100 (static via nmcli) |
| Tailscale IP | 100.99.184.127 |
| Domain | highcarlsagan.dev (Cloudflare registrar) |
| SSH Port | 2222 (key auth only) |

---

## Stack

| Service | Method | Port | URL |
|---|---|---|---|
| Caddy | Native (custom build) | 443 / 80 | — |
| Authelia | Native binary | 9091 | auth.highcarlsagan.dev |
| Cloudflare Tunnel | Native (cloudflared) | outbound | — |
| Cloudflare DDNS | Docker | — | — |
| Pi-hole | Docker | 8888 / 53 | pihole.highcarlsagan.dev |
| Home Assistant | Docker | 8123 | ha.highcarlsagan.dev |
| Mosquitto MQTT | Native (apt) | 1883 | — |
| Filebrowser | Native binary | 3000 | files.highcarlsagan.dev |
| Passives Tracker | Native (Python) | 8080 | passive.highcarlsagan.dev |

### Traffic Flow

```
Browser → Cloudflare CDN → Cloudflare Tunnel → cloudflared (Pi)
       → Caddy (TLS termination) → Authelia (2FA check)
       → Backend service
```

---

## Repository Structure

```
Carls_Homelab/
├── caddy/
│   └── Caddyfile               # Reverse proxy + Authelia forward_auth config
├── authelia/
│   └── configuration.yml       # Authelia config (users.yml excluded — contains password hashes)
├── cloudflared/
│   └── config.yml              # Tunnel ingress rules
├── mosquitto/
│   └── mosquitto.conf          # MQTT broker config
├── homeassistant/
│   └── configuration.yaml      # HA trusted proxy config
├── filebrowser/                # Filebrowser binary config (db excluded)
├── systemd/
│   └── passives-stock.service  # User systemd service for Passives Tracker
├── passives-stock/             # Passives Tracker app (server.py + HTML)
├── restore.sh                  # Full Pi restore script
└── README.md
```

---

## Critical Notes

### Caddy — Custom Build (DO NOT reinstall from apt)
Caddy is built with a **patched** `caddy-dns/cloudflare` module. The upstream regex `{35,50}` rejects Cloudflare's newer `cfut_` API tokens (52 chars). The patch changes it to `{35,100}`.

- Patched source: `~/caddy-cloudflare-patched/`
- xcaddy binary: `~/go/bin/xcaddy`
- To rebuild after a Pi rebuild:
```bash
cd ~/caddy-cloudflare-patched
~/go/bin/xcaddy build --with github.com/caddy-dns/cloudflare=.
sudo mv caddy /usr/bin/caddy
```

### Authelia — GitHub Binary (NOT apt)
The Authelia apt repo (`apt.authelia.com`) returned 404 and was removed. Authelia is installed from the GitHub releases binary. Do not attempt `apt install authelia`.

### Pi-hole — Docker (NOT native installer)
The native Pi-hole installer uses hardcoded ncurses dialogs that cannot be suppressed with `--unattended` and are incompatible with Kitty terminal. Always use Docker for installs/reinstalls.

Pi-hole v6 CLI changes from v5:
- `pihole -w` → `pihole allow`
- `pihole -a adlist add` → web UI or SQLite
- `WEB_PORT` env var → `FTLCONF_webserver_port`
- `DNSMASQ_LISTENING` → `FTLCONF_dns_listeningMode`

### Mosquitto — passwd file ownership
After creating/recreating the passwd file with `mosquitto_passwd`, always fix ownership:
```bash
sudo chown mosquitto:mosquitto /etc/mosquitto/passwd
```

### Home Assistant — Reverse Proxy Config
HA requires trusted proxy config or returns 400 Bad Request. Must be at **root level** of `configuration.yaml`, not nested under `homeassistant:`:
```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
    - ::1
```

### Terminal on Pi
Never use `nano` on the Pi — `TERM=xterm-kitty` causes "Error opening terminal". Always use `sed` for config edits. For TUI-based tools, SSH from `xterm` or `alacritty` with `TERM=xterm-256color`.

---

## Secrets (NOT in this repo)

The following files contain secrets and are excluded via `.gitignore`:

| File | Location | Contains |
|---|---|---|
| users.yml | /etc/authelia/users.yml | Password hash, TOTP secret |
| Cloudflare API token | /etc/caddy/env or systemd | cfut_ token (52 chars) |
| Tunnel credentials | /home/pi/.cloudflared/*.json | Tunnel secret |
| Authelia secrets | configuration.yml | jwt_secret, session secret, storage key |
| MQTT password | /etc/mosquitto/passwd | mqttuser password hash |
| Pi-hole password | Docker env | Admin password hash |

Back these up separately in a password manager (Bitwarden recommended).

---

## Restore Procedure

See `restore.sh` for a full automated restore. High-level steps:

1. Flash Pi OS Lite 64-bit
2. Run `restore.sh` — installs all dependencies, copies configs, starts services
3. Manually restore secrets from password manager
4. Re-register TOTP in Google Authenticator (scan new QR from Authelia)
5. Re-enable Tailscale DNS override in admin console

---

## Pending (as of 2026-03-21)

- [ ] Section 09 — Arch PC ethernet static IP + WoL (ethernet cable pending)
- [ ] Section 09 — Fallback DNS on Arch PC
- [ ] Section 10 — SD card backup strategy
- [ ] Section 11 — qBittorrent + Uptime Kuma
- [ ] HA — Wake-on-LAN switch for Arch PC
- [ ] HA — Arch PC update notifications via MQTT
- [ ] Pi-hole — Extra blocklists via web UI (blocklistproject ads/tracking, anudeepND)

---

## Updating This Repo

After any config change on the Pi:
```bash
cd ~/homelab-configs
sudo cp /etc/caddy/Caddyfile caddy/
sudo cp /etc/authelia/configuration.yml authelia/
sudo cp /etc/cloudflared/config.yml cloudflared/
# ... copy whichever file changed
git add -A
git commit -m "update: describe what changed"
git push
```
