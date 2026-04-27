"""
Carl's Project Tracker
Single-file FastAPI app. SQLite. Minimal deps.

Run: uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Form, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tracker.db"
SEED_PATH = BASE_DIR / "seed.json"

app = FastAPI(title="Carl's Project Tracker")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ---------------------------------------------------------------------------
# Auth - reads X-Remote-User header from Authelia in prod, fallback for local
# ---------------------------------------------------------------------------
ADMIN_MODE = os.environ.get("TRACKER_ADMIN", "true").lower() == "true"


def is_admin(remote_user: Optional[str]) -> bool:
    """In production, Authelia sets X-Remote-User. Locally, we trust env var."""
    if remote_user:
        return True
    return ADMIN_MODE


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color_hex TEXT NOT NULL,
            icon TEXT,
            display_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            status TEXT NOT NULL DEFAULT 'backlog',
            urgency TEXT DEFAULT 'relaxed',
            description_short TEXT,
            description_long TEXT,
            tech_stack TEXT,
            timeline_estimate TEXT,
            started_date TEXT,
            target_date TEXT,
            completed_date TEXT,
            github_url TEXT,
            external_url TEXT,
            image_url TEXT,
            kanban_order INTEGER DEFAULT 0,
            is_public INTEGER DEFAULT 1,
            parent_project_id INTEGER,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            custom_fields TEXT,
            FOREIGN KEY (parent_project_id) REFERENCES projects(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            done INTEGER DEFAULT 0,
            task_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS progress_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            note TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_tags (
            project_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (project_id, tag_id),
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
        CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category);
        """)


def seed_if_empty():
    with get_db() as db:
        count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count > 0:
            return

    if not SEED_PATH.exists():
        return

    with open(SEED_PATH) as f:
        seed = json.load(f)

    with get_db() as db:
        # categories
        for c in seed.get("categories", []):
            db.execute(
                "INSERT OR IGNORE INTO categories (name, color_hex, icon, display_order) VALUES (?, ?, ?, ?)",
                (c["name"], c["color_hex"], c.get("icon", ""), c.get("display_order", 0)),
            )

        # tags
        for t in seed.get("tags", []):
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t,))

        # projects
        for p in seed.get("projects", []):
            db.execute(
                """INSERT INTO projects
                (slug, title, category, subcategory, status, urgency,
                 description_short, description_long, tech_stack, timeline_estimate,
                 started_date, target_date, completed_date,
                 github_url, external_url, image_url,
                 kanban_order, is_public)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["slug"], p["title"], p["category"], p.get("subcategory"),
                    p["status"], p.get("urgency", "relaxed"),
                    p.get("description_short", ""), p.get("description_long", ""),
                    p.get("tech_stack", ""), p.get("timeline_estimate", ""),
                    p.get("started_date"), p.get("target_date"), p.get("completed_date"),
                    p.get("github_url"), p.get("external_url"), p.get("image_url"),
                    p.get("kanban_order", 0), 1 if p.get("is_public", True) else 0,
                ),
            )

            # tags for this project
            project_id = db.execute("SELECT id FROM projects WHERE slug = ?", (p["slug"],)).fetchone()[0]
            for tag_name in p.get("tags", []):
                tag_row = db.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
                if tag_row:
                    db.execute(
                        "INSERT OR IGNORE INTO project_tags (project_id, tag_id) VALUES (?, ?)",
                        (project_id, tag_row[0]),
                    )

            # tasks
            for i, task in enumerate(p.get("tasks", [])):
                db.execute(
                    "INSERT INTO tasks (project_id, title, done, task_order) VALUES (?, ?, ?, ?)",
                    (project_id, task["title"], 1 if task.get("done") else 0, i),
                )


# ---------------------------------------------------------------------------
# Routes - Pages
# ---------------------------------------------------------------------------
@app.on_event("startup")
def startup():
    init_db()
    seed_if_empty()


def get_projects_filtered(
    db,
    status: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    public_only: bool = False,
):
    sql = "SELECT * FROM projects WHERE 1=1"
    params = []
    if public_only:
        sql += " AND is_public = 1"
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if category and category != "all":
        sql += " AND category = ?"
        params.append(category)
    if search:
        sql += " AND (title LIKE ? OR description_short LIKE ? OR tech_stack LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    if tag and tag != "all":
        sql += " AND id IN (SELECT project_id FROM project_tags pt JOIN tags t ON t.id = pt.tag_id WHERE t.name = ?)"
        params.append(tag)
    sql += " ORDER BY kanban_order, id"
    rows = db.execute(sql, params).fetchall()
    projects = []
    for r in rows:
        proj = dict(r)
        # attach tags
        tag_rows = db.execute(
            "SELECT t.name FROM tags t JOIN project_tags pt ON pt.tag_id = t.id WHERE pt.project_id = ?",
            (proj["id"],),
        ).fetchall()
        proj["tags"] = [t["name"] for t in tag_rows]
        # attach task progress
        task_rows = db.execute(
            "SELECT done FROM tasks WHERE project_id = ?", (proj["id"],)
        ).fetchall()
        proj["task_total"] = len(task_rows)
        proj["task_done"] = sum(1 for t in task_rows if t["done"])
        projects.append(proj)
    return projects


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    view: str = "kanban",
    x_remote_user: Optional[str] = Header(None),
):
    admin = is_admin(x_remote_user)
    with get_db() as db:
        projects = get_projects_filtered(
            db,
            status=status,
            category=category,
            tag=tag,
            search=search,
            public_only=not admin,
        )
        categories = db.execute(
            "SELECT * FROM categories ORDER BY display_order, name"
        ).fetchall()
        tags = db.execute("SELECT name FROM tags ORDER BY name").fetchall()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "projects": projects,
            "categories": [dict(c) for c in categories],
            "tags": [t["name"] for t in tags],
            "admin": admin,
            "filters": {"status": status, "category": category, "tag": tag, "search": search},
            "view": view,
            "statuses": ["done", "in-progress", "next", "backlog", "long-term"],
        },
    )


@app.get("/project/{slug}", response_class=HTMLResponse)
def project_detail(slug: str, request: Request, x_remote_user: Optional[str] = Header(None)):
    admin = is_admin(x_remote_user)
    with get_db() as db:
        row = db.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        proj = dict(row)
        if not admin and not proj["is_public"]:
            raise HTTPException(404, "Project not found")
        proj["tasks"] = [
            dict(t)
            for t in db.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY task_order, id", (proj["id"],)
            ).fetchall()
        ]
        proj["notes"] = [
            dict(n)
            for n in db.execute(
                "SELECT * FROM progress_notes WHERE project_id = ? ORDER BY created_at DESC",
                (proj["id"],),
            ).fetchall()
        ]
        tag_rows = db.execute(
            "SELECT t.name FROM tags t JOIN project_tags pt ON pt.tag_id = t.id WHERE pt.project_id = ?",
            (proj["id"],),
        ).fetchall()
        proj["tags"] = [t["name"] for t in tag_rows]
        all_tags = [t["name"] for t in db.execute("SELECT name FROM tags ORDER BY name").fetchall()]
        all_categories = [
            dict(c) for c in db.execute("SELECT * FROM categories ORDER BY display_order, name").fetchall()
        ]

    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "p": proj,
            "admin": admin,
            "all_tags": all_tags,
            "all_categories": all_categories,
            "statuses": ["done", "in-progress", "next", "backlog", "long-term"],
            "urgencies": ["critical", "semi-critical", "relaxed", "take-it-easy"],
        },
    )


# ---------------------------------------------------------------------------
# Routes - API (admin only for writes)
# ---------------------------------------------------------------------------
def require_admin(x_remote_user: Optional[str]):
    if not is_admin(x_remote_user):
        raise HTTPException(403, "Admin only")


@app.post("/api/project/{project_id}/status")
def update_status(
    project_id: int,
    status: str = Form(...),
    x_remote_user: Optional[str] = Header(None),
):
    require_admin(x_remote_user)
    with get_db() as db:
        db.execute(
            "UPDATE projects SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
            (status, project_id),
        )
    return {"ok": True}


@app.post("/api/project/{project_id}/edit")
def edit_project(
    project_id: int,
    title: str = Form(...),
    category: str = Form(...),
    subcategory: str = Form(""),
    status: str = Form(...),
    urgency: str = Form("relaxed"),
    description_short: str = Form(""),
    description_long: str = Form(""),
    tech_stack: str = Form(""),
    timeline_estimate: str = Form(""),
    github_url: str = Form(""),
    external_url: str = Form(""),
    is_public: str = Form("1"),
    tags: str = Form(""),  # comma-separated
    x_remote_user: Optional[str] = Header(None),
):
    require_admin(x_remote_user)
    with get_db() as db:
        db.execute(
            """UPDATE projects SET
            title=?, category=?, subcategory=?, status=?, urgency=?,
            description_short=?, description_long=?, tech_stack=?,
            timeline_estimate=?, github_url=?, external_url=?, is_public=?,
            last_updated=CURRENT_TIMESTAMP
            WHERE id=?""",
            (
                title, category, subcategory or None, status, urgency,
                description_short, description_long, tech_stack, timeline_estimate,
                github_url or None, external_url or None,
                1 if is_public in ("1", "true", "on") else 0,
                project_id,
            ),
        )
        # tags
        db.execute("DELETE FROM project_tags WHERE project_id = ?", (project_id,))
        for tag_name in [t.strip() for t in tags.split(",") if t.strip()]:
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
            tag_id = db.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()[0]
            db.execute(
                "INSERT OR IGNORE INTO project_tags (project_id, tag_id) VALUES (?, ?)",
                (project_id, tag_id),
            )
        slug = db.execute("SELECT slug FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.post("/api/project/new")
def new_project(
    title: str = Form(...),
    category: str = Form(...),
    status: str = Form("backlog"),
    description_short: str = Form(""),
    timeline_estimate: str = Form(""),
    x_remote_user: Optional[str] = Header(None),
):
    require_admin(x_remote_user)
    slug = (
        title.lower()
        .replace(" ", "-")
        .replace("/", "-")
        .replace("(", "")
        .replace(")", "")
    )
    with get_db() as db:
        db.execute(
            """INSERT INTO projects (slug, title, category, status, description_short, timeline_estimate)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (slug, title, category, status, description_short, timeline_estimate),
        )
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.post("/api/project/{project_id}/delete")
def delete_project(project_id: int, x_remote_user: Optional[str] = Header(None)):
    require_admin(x_remote_user)
    with get_db() as db:
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return RedirectResponse("/", status_code=303)


@app.post("/api/task/new")
def new_task(
    project_id: int = Form(...),
    title: str = Form(...),
    x_remote_user: Optional[str] = Header(None),
):
    require_admin(x_remote_user)
    with get_db() as db:
        max_order = db.execute(
            "SELECT COALESCE(MAX(task_order), -1) FROM tasks WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO tasks (project_id, title, task_order) VALUES (?, ?, ?)",
            (project_id, title, max_order + 1),
        )
        slug = db.execute("SELECT slug FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.post("/api/task/{task_id}/toggle")
def toggle_task(task_id: int, x_remote_user: Optional[str] = Header(None)):
    require_admin(x_remote_user)
    with get_db() as db:
        db.execute("UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,))
        row = db.execute(
            "SELECT p.slug FROM projects p JOIN tasks t ON t.project_id = p.id WHERE t.id = ?",
            (task_id,),
        ).fetchone()
    return RedirectResponse(f"/project/{row['slug']}", status_code=303)


@app.post("/api/task/{task_id}/delete")
def delete_task(task_id: int, x_remote_user: Optional[str] = Header(None)):
    require_admin(x_remote_user)
    with get_db() as db:
        row = db.execute(
            "SELECT p.slug FROM projects p JOIN tasks t ON t.project_id = p.id WHERE t.id = ?",
            (task_id,),
        ).fetchone()
        slug = row["slug"]
        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.post("/api/note/new")
def new_note(
    project_id: int = Form(...),
    note: str = Form(...),
    x_remote_user: Optional[str] = Header(None),
):
    require_admin(x_remote_user)
    with get_db() as db:
        db.execute("INSERT INTO progress_notes (project_id, note) VALUES (?, ?)", (project_id, note))
        db.execute(
            "UPDATE projects SET last_updated = CURRENT_TIMESTAMP WHERE id = ?", (project_id,)
        )
        slug = db.execute("SELECT slug FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    return RedirectResponse(f"/project/{slug}", status_code=303)


@app.get("/api/projects.json")
def projects_json(x_remote_user: Optional[str] = Header(None)):
    admin = is_admin(x_remote_user)
    with get_db() as db:
        projects = get_projects_filtered(db, public_only=not admin)
    return JSONResponse(projects)


@app.get("/api/search")
def api_search(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    view: str = "kanban",
    x_remote_user: Optional[str] = Header(None),
):
    """Returns just the kanban/cards/table block. Used by live search on the dashboard."""
    admin = is_admin(x_remote_user)
    with get_db() as db:
        projects = get_projects_filtered(
            db,
            status=status, category=category, tag=tag, search=search,
            public_only=not admin,
        )
    return templates.TemplateResponse(
        "partials/results.html",
        {
            "request": request,
            "projects": projects,
            "admin": admin,
            "view": view,
            "statuses": ["done", "in-progress", "next", "backlog", "long-term"],
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}
