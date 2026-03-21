#!/usr/bin/env bash
# homelab-backup.sh — daily config backup
# Backs up all critical configs to /srv/filebrowser/backups/
# Keeps last 7 backups

set -euo pipefail

BACKUP_DIR="/srv/filebrowser/backups"
DATE=$(date +%Y-%m-%d)
ARCHIVE="$BACKUP_DIR/homelab-configs-$DATE.tar.gz"

mkdir -p "$BACKUP_DIR"

tar -czf "$ARCHIVE" \
  /etc/caddy/Caddyfile \
  /etc/authelia/configuration.yml \
  /etc/authelia/users.yml \
  /etc/cloudflared/config.yml \
  /etc/mosquitto/mosquitto.conf \
  /etc/homeassistant/configuration.yaml \
  /etc/filebrowser/filebrowser.db \
  /etc/pihole \
  /home/pi/.cloudflared \
  /home/pi/passives-stock \
  /home/pi/homelab-configs \
  2>/dev/null || true

# Keep last 7 backups
ls -t "$BACKUP_DIR"/homelab-configs-*.tar.gz | tail -n +8 | xargs rm -f 2>/dev/null || true

echo "[$(date)] Backup complete: $ARCHIVE ($(du -sh $ARCHIVE | cut -f1))"
