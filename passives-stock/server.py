#!/usr/bin/env python3
"""
passives-stock server
---------------------
Serves the tracker HTML and persists state to state.json.
No external dependencies — stdlib only.

Usage:
    python server.py [--host 0.0.0.0] [--port 8080]

Moving to Raspberry Pi:
    Copy this directory to the Pi, install nothing, run the same command.
    Update the systemd service ExecStart path accordingly.
"""

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from datetime import datetime

# ── paths ──────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.resolve()
HTML_FILE  = BASE_DIR / "passives_tracker_v2.html"
STATE_FILE = BASE_DIR / "state.json"
BACKUP_DIR = BASE_DIR / "backups"


# ── helpers ────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[WARN] state.json corrupt: {e} — returning empty state")
    return {}


def save_state(data: dict) -> None:
    """Atomic write: write to temp file then rename so a crash mid-write
    never produces a corrupt state.json."""
    BACKUP_DIR.mkdir(exist_ok=True)

    # rotate backup once per day (keeps last 7)
    today = datetime.now().strftime("%Y-%m-%d")
    backup = BACKUP_DIR / f"state_{today}.json"
    if not backup.exists() and STATE_FILE.exists():
        shutil.copy2(STATE_FILE, backup)
        _prune_backups()

    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _prune_backups(keep: int = 7) -> None:
    backups = sorted(BACKUP_DIR.glob("state_*.json"))
    for old in backups[:-keep]:
        old.unlink(missing_ok=True)


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ── request handler ────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # compact log: timestamp + method + path + status
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # allow requests from any origin on LAN (useful if you ever
        # open from a different port or a local file)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # preflight for CORS
        self._send(204, "text/plain", b"")

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            if not HTML_FILE.exists():
                self._send(404, "text/plain", b"passives_tracker_v2.html not found next to server.py")
                return
            body = HTML_FILE.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)

        elif path == "/api/state":
            body = json.dumps(load_state(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)

        elif path == "/api/backup/list":
            BACKUP_DIR.mkdir(exist_ok=True)
            files = sorted(f.name for f in BACKUP_DIR.glob("state_*.json"))
            body = json.dumps(files).encode("utf-8")
            self._send(200, "application/json", body)

        elif path == "/health":
            body = json.dumps({"status": "ok", "state_file": str(STATE_FILE)}).encode()
            self._send(200, "application/json", body)

        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/state":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                self._send(400, "application/json",
                           json.dumps({"error": str(e)}).encode())
                return
            save_state(data)
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"Not found")


# ── entry point ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Passives Stock Server")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default 0.0.0.0 = all interfaces)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port (default 8080)")
    args = parser.parse_args()

    if not HTML_FILE.exists():
        print(f"[ERROR] {HTML_FILE} not found.")
        print("        Place passives_tracker_v2.html in the same directory as server.py")
        sys.exit(1)

    local_ip = get_local_ip()
    httpd = HTTPServer((args.host, args.port), Handler)

    print("=" * 56)
    print("  PASSIVES.STOCK — server running")
    print("=" * 56)
    print(f"  Local:    http://localhost:{args.port}")
    print(f"  Network:  http://{local_ip}:{args.port}")
    print(f"  State:    {STATE_FILE}")
    print(f"  Backups:  {BACKUP_DIR}  (daily, 7 kept)")
    print("  Ctrl+C to stop")
    print("=" * 56)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down.")
        httpd.server_close()


if __name__ == "__main__":
    main()
