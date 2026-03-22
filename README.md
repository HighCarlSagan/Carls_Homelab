# Carls_Homelab

Personal homelab configuration backup for a Raspberry Pi 4 running a self-hosted stack — Caddy, Authelia, Cloudflare Tunnel, Pi-hole, Home Assistant, Mosquitto, Filebrowser, qBittorrent, and Uptime Kuma — accessible remotely via Tailscale and secured with 2FA.

---

## Infrastructure

| Item | Value |
|---|---|
| Hardware | Raspberry Pi 4 |
| OS | Raspberry Pi OS Lite 64-bit (Bookworm) |
| Hostname | 4pi.local |
| Pi LAN IP | 192.168.0.100 (static via nmcli · ethernet) |
| Pi Tailscale IP | 100.99.184.127 |
| Domain | highcarlsagan.dev (Cloudflare registrar) |
| SSH Port | 2222 (key auth only) |
| Arch PC LAN IP | 192.168.0.194 (static via nmcli · ethernet) |
| Arch PC Tailscale IP | 100.121.91.124 |
| Arch PC MAC | 34:5a:60:a2:91:94 (used for WoL) |
| Gateway | 192.168.0.1 |

---

## Stack

| Service | Method | Port | URL | Auth |
|---|---|---|---|---|
| Caddy | Native (custom build) | 443 / 80 | — | — |
| Authelia | Native binary | 9091 | auth.highcarlsagan.dev | — |
| Cloudflare Tunnel | Native (cloudflared) | outbound | — | — |
| Cloudflare DDNS | Docker | — | — | — |
| Pi-hole | Docker | 8888 / 53 | pihole.highcarlsagan.dev | Authelia 2FA |
| Home Assistant | Docker | 8123 | ha.highcarlsagan.dev | Authelia 2FA |
| Filebrowser | Native binary | 3000 | files.highcarlsagan.dev | Authelia 2FA |
| Passives Tracker | Native (Python) | 8080 | passive.highcarlsagan.dev | Authelia 2FA |
| qBittorrent | Docker | 8081 | torrent.highcarlsagan.dev | Authelia 2FA |
| Uptime Kuma | Docker | 3001 | status.highcarlsagan.dev | Authelia 2FA |
| Mosquitto MQTT | Native (apt) | 1883 | — | — |
| Portfolio | Static file | — | highcarlsagan.dev | Public |
| Resume | Static file | — | resume.highcarlsagan.dev | Public |
| Docs / Reference | Static file | — | docs.highcarlsagan.dev | Authelia 2FA |

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
│   └── configuration.yaml      # HA trusted proxy + shell_command config
├── systemd/
│   └── passives-stock.service  # User systemd service for Passives Tracker
├── passives-stock/             # Passives Tracker app (server.py + HTML)
├── homelab_reference.html      # Full interactive reference doc (hosted at docs.highcarlsagan.dev)
├── homelab-backup.sh           # Daily config backup script
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

### Caddy — trusted_proxies required for Authelia

Without `trusted_proxies static private_ranges` in the global options block, `forward_auth` silently bypasses Authelia. Always include this:

```
{
  servers {
    trusted_proxies static private_ranges
  }
}
```

### Authelia — GitHub Binary (NOT apt)

The Authelia apt repo (`apt.authelia.com`) returned 404 and was removed. Authelia is installed from the GitHub releases binary. Do not attempt `apt install authelia`.

### Pi-hole — Docker (NOT native installer)

The native Pi-hole installer uses hardcoded ncurses dialogs incompatible with Kitty terminal. Always use Docker.

Pi-hole CLI must be run inside the container:
```bash
docker exec pihole pihole status
docker exec pihole pihole allow example.com
```

Pi-hole v6 CLI changes from v5:
- `pihole -w` → `pihole allow`
- `WEB_PORT` env var → `FTLCONF_webserver_port`
- `DNSMASQ_LISTENING` → `FTLCONF_dns_listeningMode`

### Tailscale DNS

DNS nameserver set to `100.99.184.127` (Pi Tailscale IP) with **Override local DNS enabled** — all Tailscale devices use Pi-hole for DNS.

### Home Assistant — Reverse Proxy Config

HA requires trusted proxy config or returns 400 Bad Request. Must be at **root level** of `configuration.yaml`, not nested under `homeassistant:`:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
    - ::1
```

### Home Assistant — Arch PC shell_command

HA controls the Arch PC via SSH shell commands. The SSH key (`id_pi_to_arch`) must be present at `/etc/homeassistant/id_pi_to_arch` with `chmod 600`. This file is **not** in the repo — restore manually (see Restore Procedure).

```yaml
shell_command:
  shutdown_arch: "ssh -i /config/id_pi_to_arch -p 2222 -o StrictHostKeyChecking=no carl@192.168.0.194 sudo systemctl poweroff"
  wakeup_arch: "wakeonlan 34:5a:60:a2:91:94"
```

### Arch PC — Wake-on-LAN

WoL is managed by `wol.service` (in `systemd/`) which runs `ethtool -s enp8s0 wol g` on every boot. The `wakearch` alias on the Pi sends the magic packet:

```bash
# On Pi
alias wakearch='wakeonlan 34:5a:60:a2:91:94'

# From Termux (Pixel 8) — SSHes into Pi then wakes Arch
alias wakearch='ssh -p 2222 -i ~/.ssh/id_pi pi@100.99.184.127 wakeonlan 34:5a:60:a2:91:94'
```

Arch PC requires passwordless sudo for shutdown:
```bash
# /etc/sudoers.d/poweroff on Arch
carl ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff
```

### Mosquitto — passwd file ownership

After creating/recreating the passwd file with `mosquitto_passwd`, always fix ownership:

```bash
sudo chown mosquitto:mosquitto /etc/mosquitto/passwd
```

### Terminal on Pi

Never use `nano` on the Pi — `TERM=xterm-kitty` causes "Error opening terminal". Always use `sed` for config edits.

---

## Secrets (NOT in this repo)

| File | Location | Contains |
|---|---|---|
| users.yml | /etc/authelia/users.yml | Password hash, TOTP secret |
| Cloudflare API token | /etc/caddy/env or systemd | cfut_ token (52 chars) |
| Tunnel credentials | /home/pi/.cloudflared/*.json | Tunnel secret |
| Authelia secrets | /etc/authelia/secrets/ | jwt_secret, session_secret, storage_key |
| MQTT password | /etc/mosquitto/passwd | mqttuser password hash |
| Pi-hole password | Docker env | Admin password hash |
| HA SSH key | /etc/homeassistant/id_pi_to_arch | Pi→Arch SSH private key |

Back these up separately in a password manager (Bitwarden recommended).

---

## Restore Procedure

See `restore.sh` for a full automated restore. High-level steps:

1. Flash Pi OS Lite 64-bit
2. Run `restore.sh` — installs all dependencies, copies configs, starts services
3. Manually restore secrets from password manager
4. Re-register TOTP in Google Authenticator (scan new QR from Authelia)
5. Re-enable Tailscale DNS override in admin console
6. Restore HA SSH key for Arch PC shell_command:
   ```bash
   cp ~/.ssh/id_pi_to_arch /etc/homeassistant/id_pi_to_arch
   chmod 600 /etc/homeassistant/id_pi_to_arch
   docker restart homeassistant
   ```
7. Re-add `wakearch` alias to `~/.bashrc` on Pi

---

## Updating This Repo

After any config change on the Pi:

```bash
cd ~/homelab-configs
sudo cp /etc/caddy/Caddyfile caddy/
sudo cp /etc/authelia/configuration.yml authelia/
sudo cp /etc/cloudflared/config.yml cloudflared/
sudo cp /etc/homeassistant/configuration.yaml homeassistant/
# ... copy whichever file changed
git add -A
git commit -m "update: describe what changed"
git push
```

---

*Last updated: 2026-03-22*
