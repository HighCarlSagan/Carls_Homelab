# Project Tracker — Setup Guide

**Goal:** test on Arch PC → deploy to Pi at `tracker.highcarlsagan.dev` → remove from PC.

Everything goes into your existing `Carls_Homelab` repo on the Pi as a `project-tracker/` subfolder.

---

## How security works (read this first)

**Two layers protect the deployed app:**

1. **Cloudflare Tunnel** — your Pi has zero open ports. All traffic comes through the outbound tunnel.
2. **Authelia + TOTP** — Caddy intercepts every request and asks Authelia "is this user logged in?" If not, redirect to `auth.highcarlsagan.dev` for username + 2FA. Only after success does the request reach the app.

**Inside the app:**

```
Authelia approves → adds Remote-User header → Caddy renames to X-Remote-User
                  → app sees header → admin mode (edit forms visible, all APIs work)
                  → no header → public mode (read-only, private projects hidden, write APIs return 403)
```

The check happens in two places — **templates** (skip rendering edit forms) and **API endpoints** (reject writes with 403). Defense in depth.

**On your PC (testing):** there's no Authelia. The app falls back to an env var `TRACKER_ADMIN`. If `true` → admin mode locally. If `false` → simulate a public user.

**On the Pi (production):** the systemd unit sets `TRACKER_ADMIN=false`. The only path to admin is the Authelia header. No env var trick, no localhost trick.

---

## Phase 1 — Test on PC (15 min)

### 1.1 Extract and enter the folder
```bash
cd ~/Downloads
tar -xzf project_tracker.tar.gz
cd project_tracker
```

### 1.2 Set up Python sandbox
A `venv` is a private Python environment so this app's libraries don't conflict with anything else on your Arch system.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.3 Run in admin mode (default)
```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765** — you should see ~67 projects, top-right shows `admin` badge.

### 1.4 Test the admin features
- [ ] Search box: type "oakbridge" — list updates as you type, no submit needed
- [ ] Layout switcher (Kanban / Cards / Compact / Gallery / Table) — pick one, refresh page, it remembers
- [ ] Switch through all 5 themes (top-right dropdown)
- [ ] Filter by category, tag, status — combine with search
- [ ] Click a project → edit a field → save → confirm it persists
- [ ] Tick a task checkbox, add a new task, log a progress note
- [ ] Click "+ New Project", create one, then delete it
- [ ] Set a project to private (uncheck `is_public` in edit form)

Stop with `Ctrl+C`.

### 1.5 Test public mode (simulates what the world sees)
```bash
TRACKER_ADMIN=false uvicorn app:app --host 127.0.0.1 --port 8765
```

Open the same URL. Confirm:
- [ ] Top-right shows `public` badge (not `admin`)
- [ ] No "+ New Project" button
- [ ] No "Edit Project" form on project detail pages
- [ ] Any project you marked private is now invisible
- [ ] Try this in a terminal: `curl -X POST http://127.0.0.1:8765/api/project/1/delete` — should return `403 Forbidden`

Stop with `Ctrl+C`. Then exit the venv:
```bash
deactivate
```

If anything broke, tell me before we deploy.

---

## Phase 2 — Get the code onto the Pi (5 min)

Your homelab repo is hosted on the Pi itself (you SSH in and `git push`/`pull` there directly). So we copy files **straight to the Pi** with `scp`, then commit on the Pi.

### 2.1 Copy the project folder to the Pi
```bash
# from your PC, in ~/Downloads
scp -r project_tracker pi:~/homelab-configs/project-tracker
```

That copies the whole folder. The `pi` SSH alias handles port + user.

### 2.2 SSH in and clean up before committing
```bash
ssh pi
cd ~/homelab-configs/project-tracker
rm -rf .venv tracker.db __pycache__
```

The venv and DB are local-only — they should never go into Git.

### 2.3 Add a systemd service file (matches your `passives-stock` pattern)
```bash
cat > ~/homelab-configs/systemd/project-tracker.service <<'EOF'
[Unit]
Description=Project Tracker (FastAPI)
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/homelab-configs/project-tracker
Environment="TRACKER_ADMIN=false"
ExecStart=/home/pi/homelab-configs/project-tracker/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

### 2.4 Update `.gitignore` so venv + DB stay out of Git
```bash
cd ~/homelab-configs
cat >> .gitignore <<'EOF'

# Project Tracker
project-tracker/.venv/
project-tracker/tracker.db
project-tracker/__pycache__/
EOF
```

### 2.5 Commit and push from the Pi
```bash
cd ~/homelab-configs
git add project-tracker/ systemd/project-tracker.service .gitignore
git commit -m "Add project tracker service"
git push
```

---

## Phase 3 — Run it on the Pi (10 min)

You're still SSH'd in.

### 3.1 Create the venv and install dependencies
```bash
cd ~/homelab-configs/project-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate
```

### 3.2 Smoke test it manually first
```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
```

In another terminal (`ssh pi` again):
```bash
curl http://127.0.0.1:8765/health
# Expected: {"status":"ok"}
```

If you got `ok`, kill the manual run with `Ctrl+C`.

### 3.3 Install and start the systemd service
```bash
sudo cp ~/homelab-configs/systemd/project-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now project-tracker.service
sudo systemctl status project-tracker
# Expected: active (running)
```

If it failed: `journalctl -u project-tracker -n 50`

### 3.4 Confirm it's still reachable
```bash
curl http://127.0.0.1:8765/health
```

Now it survives reboots.

---

## Phase 4 — Caddy + Authelia + Cloudflare (10 min)

### 4.1 Add the Caddy site block
Edit `/etc/caddy/Caddyfile`. Use `sed` to append (per your homelab note about not using nano):

```bash
sudo tee -a /etc/caddy/Caddyfile <<'EOF'

tracker.highcarlsagan.dev {
    forward_auth 127.0.0.1:9091 {
        uri /api/verify?rd=https://auth.highcarlsagan.dev
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }
    reverse_proxy 127.0.0.1:8765 {
        header_up X-Remote-User {http.request.header.Remote-User}
    }
    encode gzip zstd
}
EOF

# Validate and reload
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

### 4.2 Add Authelia access rule
Edit `/etc/authelia/configuration.yml` — add under `access_control.rules`:

```yaml
    - domain: tracker.highcarlsagan.dev
      policy: two_factor
```

```bash
sudo systemctl restart authelia
```

### 4.3 Add Cloudflare Tunnel ingress
Edit `~/.cloudflared/config.yml` (or wherever your tunnel config lives). Add **above** the catch-all `service: http_status:404`:

```yaml
  - hostname: tracker.highcarlsagan.dev
    service: https://localhost:443
    originRequest:
      noTLSVerify: true
```

```bash
sudo systemctl restart cloudflared
```

### 4.4 Add the Cloudflare DNS record
In the Cloudflare dashboard for `highcarlsagan.dev`:
1. DNS → Records → Add record
2. Type `CNAME`, Name `tracker`, Target `<your-tunnel-id>.cfargotunnel.com` (same target as `auth`, `ha`, `passive`)
3. Proxy: **Proxied** (orange cloud on)

### 4.5 Update the Caddyfile in your repo too (so Git stays in sync)
```bash
sudo cp /etc/caddy/Caddyfile ~/homelab-configs/caddy/
sudo cp /etc/authelia/configuration.yml ~/homelab-configs/authelia/
sudo cp ~/.cloudflared/config.yml ~/homelab-configs/cloudflared/
sudo chown pi:pi ~/homelab-configs/caddy/Caddyfile ~/homelab-configs/authelia/configuration.yml ~/homelab-configs/cloudflared/config.yml

cd ~/homelab-configs
git add caddy/ authelia/ cloudflared/
git commit -m "Add tracker.highcarlsagan.dev routing"
git push
```

### 4.6 Test from your phone on cellular
1. Disable WiFi on your phone
2. Open `https://tracker.highcarlsagan.dev`
3. Authelia login → TOTP → tracker loads with admin badge

Done.

---

## Phase 5 — Clean up your PC (1 min)

```bash
rm -rf ~/Downloads/project_tracker
rm -f ~/Downloads/project_tracker.tar.gz
```

The canonical copy now lives in `~/homelab-configs/project-tracker/` on your Pi (and on GitHub).

---

## Adding a public read-only view later (optional)

When you want to show projects to others without making them log in, add a second subdomain that **bypasses Authelia**:

```caddyfile
projects.highcarlsagan.dev {
    reverse_proxy 127.0.0.1:8765 {
        header_up -X-Remote-User
    }
    encode gzip zstd
}
```

The `header_up -X-Remote-User` line **strips** any incoming admin header, guaranteeing public mode. Add an Authelia rule:

```yaml
    - domain: projects.highcarlsagan.dev
      policy: bypass
```

Plus matching Cloudflare DNS + tunnel ingress entry. Tell me when you want this and I'll write the exact diffs.

---

## Day-to-day workflow

### Editing code
You'll edit code on your PC where the IDE is comfortable. You don't need to install Python or run anything on the PC for this — the Pi runs the actual app.

```bash
# On PC: pull latest, edit, push
cd ~/Carls_Homelab     # if you cloned it locally
git pull
# ... edit files ...
git add -A
git commit -m "tracker: describe change"
git push
```

> If you don't have the repo cloned on your PC: `git clone <pi-or-github-url> ~/Carls_Homelab` first. Note: since your Git is hosted on the Pi, your remote is the Pi (or GitHub if you push there too).

### Pulling on Pi and restarting
```bash
ssh pi
cd ~/homelab-configs
git pull
sudo systemctl restart project-tracker
```

Refresh the browser — changes are live.

### Editing directly on the Pi (for small fixes)
```bash
ssh pi
cd ~/homelab-configs/project-tracker
# edit files (use vim/sed since you can't use nano on Pi)
sudo systemctl restart project-tracker

# Then commit
cd ~/homelab-configs
git add project-tracker/
git commit -m "tracker: hotfix"
git push
```

---

## Backup

Add to your existing `homelab-backup.sh` on the Pi:

```bash
# Backup project tracker DB
cp /home/pi/homelab-configs/project-tracker/tracker.db \
   /path/to/backup/tracker-$(date +%F).db
```

The DB is the only stateful thing — code is in Git, config is in Git.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `502 Bad Gateway` in browser | `sudo systemctl status project-tracker` — service down? `journalctl -u project-tracker -n 50` |
| Authelia challenge loops | `trusted_proxies` issue (you flagged this in homelab notes) — check Caddy IP is in Authelia's trusted list |
| Page loads but no edit forms | `X-Remote-User` not arriving. `journalctl -u project-tracker -f`, refresh page, look at incoming request |
| `git push` says "nothing to commit" | You ran `git add` from the wrong folder. `cd ~/homelab-configs` first |
| `git pull` fails with conflicts | You edited the same file in two places. `git status` to see, resolve, then commit |
| Want to wipe all projects | Stop service, `rm tracker.db`, restart — re-imports from `seed.json` |
| Want to add a project before first launch | Edit `seed.json` before first run |

---

## Quick reference

| File | What it does |
|---|---|
| `app.py` | Backend: routes, DB, auth |
| `seed.json` | Initial 67 projects (loaded once on first DB creation) |
| `templates/index.html` | Dashboard page (search, filters, layout switcher) |
| `templates/project.html` | Single-project detail page |
| `templates/partials/results.html` | The chunk that swaps in during live search |
| `templates/partials/project_card*.html` | Card variants — default, compact, gallery |
| `static/style.css` | All styling, all 5 themes |
| `requirements.txt` | Python deps (4 of them) |

| Layout | Best for |
|---|---|
| Kanban | Daily view — see what's where |
| Cards | Browse / portfolio mode |
| Compact | Long lists, dense scanning |
| Gallery | Visual mode, after you add project images |
| Table | Bulk overview, sort by date |

Layout choice persists per-browser (localStorage).

Theme choice persists per-browser (localStorage).
