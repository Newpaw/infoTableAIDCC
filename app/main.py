from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .db import ensure_database, get_db, log_activity, now_iso
from .importer import READINESS_STAGES, import_workbook
from .seed import seed_demo

BASE_DIR = Path(__file__).resolve().parent
APP_TITLE = os.getenv("APP_TITLE", "AIDCC Control Center")
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

app = FastAPI(title=APP_TITLE, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def status_done(value: str | None) -> bool:
    v = (value or "").strip().lower()
    return v in {"done", "completed", "closed", "resolved"}


def status_open(value: str | None) -> bool:
    return not status_done(value)


def health_class(value: str | None) -> str:
    return {"green": "good", "amber": "warn", "red": "bad"}.get((value or "").lower(), "muted")


def status_class(value: str | None) -> str:
    v = (value or "").lower().strip()
    if v in {"done", "completed", "closed", "resolved"}:
        return "good"
    if v in {"issue", "blocked", "blocker"} or "issue" in v:
        return "bad"
    if v in {"in progress", "pilot", "active"}:
        return "warn"
    return "muted"


templates.env.globals.update(
    status_done=status_done,
    health_class=health_class,
    status_class=status_class,
    app_title=APP_TITLE,
)


class OptionalBasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not APP_USERNAME or not APP_PASSWORD:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        import base64

        expected = base64.b64encode(f"{APP_USERNAME}:{APP_PASSWORD}".encode()).decode()
        if auth != f"Basic {expected}":
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="AIDCC"'})
        return await call_next(request)


app.add_middleware(OptionalBasicAuthMiddleware)


@app.on_event("startup")
def startup() -> None:
    ensure_database()
    with get_db() as conn:
        seed_demo(conn)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    today = date.today().isoformat()
    next_14 = (date.today() + timedelta(days=14)).isoformat()
    with get_db() as conn:
        projects = conn.execute(
            """
            SELECT p.*,
                (SELECT COUNT(*) FROM actions a WHERE a.project_id=p.id AND lower(a.status) NOT IN ('done','completed','closed','resolved')) open_actions,
                (SELECT COUNT(*) FROM actions a WHERE a.project_id=p.id AND a.blocks_go_live=1 AND lower(a.status) NOT IN ('done','completed','closed','resolved')) blockers,
                (SELECT COUNT(*) FROM decisions d WHERE d.project_id=p.id AND lower(d.status) NOT IN ('done','closed','resolved','decided')) open_decisions
            FROM projects p
            ORDER BY CASE p.health WHEN 'Red' THEN 1 WHEN 'Amber' THEN 2 ELSE 3 END, p.name
            """
        ).fetchall()
        active = conn.execute("SELECT COUNT(*) FROM projects WHERE status='Active'").fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(DISTINCT project_id) FROM actions WHERE blocks_go_live=1 AND lower(status) NOT IN ('done','completed','closed','resolved')"
        ).fetchone()[0]
        overdue = conn.execute(
            """
            SELECT COUNT(*) FROM actions
            WHERE due_date IS NOT NULL AND due_date < ? AND lower(status) NOT IN ('done','completed','closed','resolved')
            """,
            (today,),
        ).fetchone()[0]
        upcoming = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE launch_date BETWEEN ? AND ?",
            (today, next_14),
        ).fetchone()[0]
        attention = conn.execute(
            """
            SELECT a.*, p.name project_name, p.slug project_slug
            FROM actions a JOIN projects p ON p.id=a.project_id
            WHERE lower(a.status) NOT IN ('done','completed','closed','resolved')
              AND (a.blocks_go_live=1 OR (a.due_date IS NOT NULL AND a.due_date < ?))
            ORDER BY a.blocks_go_live DESC, a.due_date IS NULL, a.due_date
            LIMIT 8
            """,
            (today,),
        ).fetchall()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"projects": projects, "active": active, "blocked": blocked, "overdue": overdue, "upcoming": upcoming, "attention": attention, "today": today},
    )


@app.get("/projects/{slug}", response_class=HTMLResponse)
def project_detail(request: Request, slug: str):
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
        if not project:
            raise HTTPException(404)
        readiness = conn.execute("SELECT * FROM readiness WHERE project_id=? ORDER BY sort_order, id", (project["id"],)).fetchall()
        actions = conn.execute(
            """
            SELECT * FROM actions WHERE project_id=?
            ORDER BY CASE WHEN lower(status) IN ('done','completed','closed','resolved') THEN 1 ELSE 0 END,
                     blocks_go_live DESC, due_date IS NULL, due_date, id DESC
            """,
            (project["id"],),
        ).fetchall()
        decisions = conn.execute(
            "SELECT * FROM decisions WHERE project_id=? ORDER BY CASE WHEN lower(status) IN ('done','closed','resolved','decided') THEN 1 ELSE 0 END, due_date IS NULL, due_date, id DESC",
            (project["id"],),
        ).fetchall()
        activity = conn.execute("SELECT * FROM activity WHERE project_id=? ORDER BY created_at DESC LIMIT 30", (project["id"],)).fetchall()
    return templates.TemplateResponse(
        request,
        "project.html",
        {"project": project, "readiness": readiness, "actions": actions, "decisions": decisions, "activity": activity, "readiness_stages": READINESS_STAGES},
    )


@app.post("/projects")
def create_project(
    name: Annotated[str, Form()],
    project_type: Annotated[str, Form()] = "Campaign",
    business_owner: Annotated[str | None, Form()] = None,
    aidcc_spoc: Annotated[str | None, Form()] = None,
    summary: Annotated[str | None, Form()] = None,
    target: Annotated[str | None, Form()] = None,
    launch_date: Annotated[str | None, Form()] = None,
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    with get_db() as conn:
        slug = slugify(name)
        base = slug
        counter = 2
        while conn.execute("SELECT 1 FROM projects WHERE slug=?", (slug,)).fetchone():
            slug = f"{base}-{counter}"
            counter += 1
        now = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO projects(name,slug,project_type,business_owner,aidcc_spoc,status,health,summary,target,launch_date,created_at,updated_at)
            VALUES (?,?,?,?,?,'Active','Amber',?,?,?,?,?)
            """,
            (name, slug, project_type, clean(business_owner), clean(aidcc_spoc), clean(summary), clean(target), clean(launch_date), now, now),
        )
        project_id = int(cursor.lastrowid)
        for idx, stage in enumerate(READINESS_STAGES):
            conn.execute("INSERT INTO readiness(project_id,stage,status,sort_order) VALUES(?,?,'Not started',?)", (project_id, stage, idx))
        log_activity(conn, project_id, "project", project_id, "Project created", name)
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/projects/{project_id}/update")
def update_project(
    project_id: int,
    business_owner: Annotated[str | None, Form()] = None,
    aidcc_spoc: Annotated[str | None, Form()] = None,
    status: Annotated[str, Form()] = "Active",
    health: Annotated[str, Form()] = "Amber",
    summary: Annotated[str | None, Form()] = None,
    target: Annotated[str | None, Form()] = None,
    launch_date: Annotated[str | None, Form()] = None,
):
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404)
        conn.execute(
            """
            UPDATE projects SET business_owner=?, aidcc_spoc=?, status=?, health=?, summary=?, target=?, launch_date=?, updated_at=? WHERE id=?
            """,
            (clean(business_owner), clean(aidcc_spoc), status, health, clean(summary), clean(target), clean(launch_date), now_iso(), project_id),
        )
        log_activity(conn, project_id, "project", project_id, "Project updated", f"Health: {health}, Status: {status}")
        slug = project["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/projects/{project_id}/readiness")
def update_readiness(project_id: int, stage: Annotated[str, Form()], status: Annotated[str, Form()]):
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404)
        existing = conn.execute("SELECT id FROM readiness WHERE project_id=? AND stage=?", (project_id, stage)).fetchone()
        if existing:
            conn.execute("UPDATE readiness SET status=? WHERE id=?", (status, existing["id"]))
        else:
            order = conn.execute("SELECT COALESCE(MAX(sort_order), -1)+1 FROM readiness WHERE project_id=?", (project_id,)).fetchone()[0]
            conn.execute("INSERT INTO readiness(project_id, stage, status, sort_order) VALUES(?,?,?,?)", (project_id, stage, status, order))
        log_activity(conn, project_id, "readiness", None, "Readiness changed", f"{stage}: {status}")
        slug = project["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/projects/{project_id}/actions")
def create_action(
    project_id: int,
    title: Annotated[str, Form()],
    area: Annotated[str | None, Form()] = None,
    detail: Annotated[str | None, Form()] = None,
    status: Annotated[str, Form()] = "To Do",
    blocks_go_live: Annotated[str | None, Form()] = None,
    owner: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    next_action: Annotated[str | None, Form()] = None,
    comment: Annotated[str | None, Form()] = None,
    priority: Annotated[str, Form()] = "Normal",
):
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404)
        now = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO actions(project_id,area,title,detail,status,blocks_go_live,owner,due_date,next_action,comment,priority,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (project_id, clean(area), title.strip(), clean(detail), status, 1 if blocks_go_live else 0, clean(owner), clean(due_date), clean(next_action), clean(comment), priority, now, now),
        )
        log_activity(conn, project_id, "action", int(cursor.lastrowid), "Action created", title.strip())
        slug = project["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/actions/{action_id}/status")
def update_action_status(action_id: int, status: Annotated[str, Form()]):
    with get_db() as conn:
        action = conn.execute("SELECT a.*, p.slug FROM actions a JOIN projects p ON p.id=a.project_id WHERE a.id=?", (action_id,)).fetchone()
        if not action:
            raise HTTPException(404)
        conn.execute("UPDATE actions SET status=?, updated_at=? WHERE id=?", (status, now_iso(), action_id))
        log_activity(conn, action["project_id"], "action", action_id, "Action status changed", f"{action['title']}: {status}")
        slug = action["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/projects/{project_id}/decisions")
def create_decision(
    project_id: int,
    title: Annotated[str, Form()],
    context: Annotated[str | None, Form()] = None,
    recommendation: Annotated[str | None, Form()] = None,
    owner: Annotated[str | None, Form()] = None,
    status: Annotated[str, Form()] = "Open",
    due_date: Annotated[str | None, Form()] = None,
):
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404)
        now = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO decisions(project_id,title,context,recommendation,owner,status,due_date,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (project_id, title.strip(), clean(context), clean(recommendation), clean(owner), status, clean(due_date), now, now),
        )
        log_activity(conn, project_id, "decision", int(cursor.lastrowid), "Decision created", title.strip())
        slug = project["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.post("/decisions/{decision_id}/resolve")
def resolve_decision(decision_id: int, decision: Annotated[str, Form()]):
    with get_db() as conn:
        row = conn.execute("SELECT d.*, p.slug FROM decisions d JOIN projects p ON p.id=d.project_id WHERE d.id=?", (decision_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        conn.execute("UPDATE decisions SET status='Decided', decision=?, updated_at=? WHERE id=?", (decision.strip(), now_iso(), decision_id))
        log_activity(conn, row["project_id"], "decision", decision_id, "Decision resolved", decision.strip())
        slug = row["slug"]
    return RedirectResponse(f"/projects/{slug}", status_code=303)


@app.get("/attention", response_class=HTMLResponse)
def attention(request: Request):
    today = date.today().isoformat()
    with get_db() as conn:
        items = conn.execute(
            """
            SELECT a.*, p.name project_name, p.slug project_slug
            FROM actions a JOIN projects p ON p.id=a.project_id
            WHERE lower(a.status) NOT IN ('done','completed','closed','resolved')
              AND (a.blocks_go_live=1 OR (a.due_date IS NOT NULL AND a.due_date < ?))
            ORDER BY a.blocks_go_live DESC, a.due_date IS NULL, a.due_date
            """,
            (today,),
        ).fetchall()
        decisions = conn.execute(
            """
            SELECT d.*, p.name project_name, p.slug project_slug
            FROM decisions d JOIN projects p ON p.id=d.project_id
            WHERE lower(d.status) NOT IN ('done','closed','resolved','decided')
            ORDER BY d.due_date IS NULL, d.due_date
            """
        ).fetchall()
    return templates.TemplateResponse(request, "attention.html", {"items": items, "decisions": decisions, "today": today})


@app.get("/weekly", response_class=HTMLResponse)
def weekly(request: Request):
    with get_db() as conn:
        projects = conn.execute("SELECT * FROM projects WHERE status='Active' ORDER BY project_type, name").fetchall()
        blocks = conn.execute(
            """
            SELECT a.*, p.name project_name FROM actions a JOIN projects p ON p.id=a.project_id
            WHERE a.blocks_go_live=1 AND lower(a.status) NOT IN ('done','completed','closed','resolved') ORDER BY p.name, a.due_date
            """
        ).fetchall()
        decisions = conn.execute(
            """
            SELECT d.*, p.name project_name FROM decisions d JOIN projects p ON p.id=d.project_id
            WHERE lower(d.status) NOT IN ('done','closed','resolved','decided') ORDER BY p.name, d.due_date
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT ac.*, p.name project_name FROM activity ac LEFT JOIN projects p ON p.id=ac.project_id
            WHERE ac.created_at >= ? ORDER BY ac.created_at DESC LIMIT 50
            """,
            ((datetime.now() - timedelta(days=7)).replace(microsecond=0).isoformat(),),
        ).fetchall()

    lines = [f"# {APP_TITLE} — weekly update", "", f"Generated: {date.today().isoformat()}", "", "## Portfolio"]
    for p in projects:
        lines.append(f"- **{p['name']}** — {p['health']} / {p['status']}. {p['summary'] or ''}".rstrip())
    if blocks:
        lines += ["", "## Blockers"]
        for a in blocks:
            due = f" (due {a['due_date']})" if a["due_date"] else ""
            lines.append(f"- **{a['project_name']}** — {a['title']}{due}. Next: {a['next_action'] or 'TBD'}")
    if decisions:
        lines += ["", "## Decisions needed"]
        for d in decisions:
            due = f" (due {d['due_date']})" if d["due_date"] else ""
            lines.append(f"- **{d['project_name']}** — {d['title']}{due}. Owner: {d['owner'] or 'TBD'}")
    if recent:
        lines += ["", "## Last 7 days"]
        for a in recent[:12]:
            lines.append(f"- {a['project_name'] or 'Global'}: {a['action']}{' — ' + a['detail'] if a['detail'] else ''}")
    markdown = "\n".join(lines)
    return templates.TemplateResponse(request, "weekly.html", {"markdown": markdown})


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {})


@app.post("/import")
async def import_excel(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload an .xlsx file")
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "File is too large")
    with get_db() as conn:
        stats = import_workbook(conn, raw)
    return RedirectResponse(f"/?imported={stats['projects']}&actions={stats['actions']}", status_code=303)
