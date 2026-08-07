from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/data/aidcc.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    project_type TEXT NOT NULL DEFAULT 'Campaign',
    business_owner TEXT,
    aidcc_spoc TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    health TEXT NOT NULL DEFAULT 'Green',
    summary TEXT,
    target TEXT,
    launch_date TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readiness (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not started',
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, stage)
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    area TEXT,
    title TEXT NOT NULL,
    detail TEXT,
    status TEXT NOT NULL DEFAULT 'To Do',
    blocks_go_live INTEGER NOT NULL DEFAULT 0,
    owner TEXT,
    due_date TEXT,
    next_action TEXT,
    comment TEXT,
    priority TEXT NOT NULL DEFAULT 'Normal',
    source_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    context TEXT,
    recommendation TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    due_date TEXT,
    decision TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project_id);
CREATE INDEX IF NOT EXISTS idx_actions_due ON actions(due_date);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_project ON activity(project_id, created_at DESC);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def ensure_database() -> None:
    path = Path(DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_activity(
    conn: sqlite3.Connection,
    project_id: int | None,
    entity_type: str,
    entity_id: int | None,
    action: str,
    detail: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO activity(project_id, entity_type, entity_id, action, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, entity_type, entity_id, action, detail, now_iso()),
    )
