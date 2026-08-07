from __future__ import annotations

import sqlite3

from .db import log_activity, now_iso


def seed_demo(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] > 0:
        return

    now = now_iso()
    demo_projects = [
        (
            "Outbound Campaign Alpha",
            "outbound-campaign-alpha",
            "Campaign",
            "Business Owner",
            "AIDCC SPOC",
            "Active",
            "Green",
            "Stable outbound campaign already in production.",
            "Validate business impact and gradually increase daily volume.",
            None,
        ),
        (
            "Outbound Campaign Beta",
            "outbound-campaign-beta",
            "Campaign",
            "Business Owner",
            "AIDCC SPOC",
            "Active",
            "Red",
            "Campaign waiting for one business decision before go-live.",
            "Launch MVP and validate lead quality.",
            None,
        ),
        (
            "E2E Monitoring",
            "e2e-monitoring",
            "Enabler",
            "Platform Owner",
            "AIDCC Architect",
            "Active",
            "Amber",
            "Cross-cutting monitoring for the AIDCC delivery chain.",
            "Detect failures before business owners report them.",
            None,
        ),
    ]
    for row in demo_projects:
        cursor = conn.execute(
            """
            INSERT INTO projects(name, slug, project_type, business_owner, aidcc_spoc, status, health, summary, target, launch_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*row, now, now),
        )
        project_id = int(cursor.lastrowid)
        stages = [
            ("Business zadání", "Done"),
            ("Příprava promptu", "Done"),
            ("Externí dependance", "Done" if project_id == 1 else "Issue" if project_id == 2 else "In progress"),
            ("Test (lokální)", "Done" if project_id == 1 else "In progress"),
            ("E2E test", "Done" if project_id == 1 else "Not started"),
            ("Pilot", "Done" if project_id == 1 else "Not started"),
            ("Business roll-out", "Done" if project_id == 1 else "Not started"),
        ]
        for idx, (stage, status) in enumerate(stages):
            conn.execute(
                "INSERT INTO readiness(project_id, stage, status, sort_order) VALUES (?, ?, ?, ?)",
                (project_id, stage, status, idx),
            )
        log_activity(conn, project_id, "project", project_id, "Project created", "Demo seed")

    conn.execute(
        """
        INSERT INTO actions(project_id, area, title, detail, status, blocks_go_live, owner, due_date, next_action, priority, created_at, updated_at)
        VALUES (2, 'Decision', 'Confirm lead priority flow', 'Business must select the final process variant.', 'In progress', 1, 'Business Owner', date('now','+2 day'), 'Confirm preferred variant and unblock launch.', 'Critical', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO actions(project_id, area, title, detail, status, blocks_go_live, owner, due_date, next_action, priority, created_at, updated_at)
        VALUES (3, 'Monitoring', 'Define minimum alert set', 'HTTP failures, flow failures and lead-volume anomalies.', 'In progress', 0, 'AIDCC Architect', date('now','+7 day'), 'Agree MVP metrics with operations.', 'High', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO decisions(project_id, title, context, recommendation, owner, status, due_date, created_at, updated_at)
        VALUES (2, 'Lead priority handling', 'A new lead can arrive while an earlier lead is already being processed.', 'Use the BAU path for MVP and avoid new development.', 'Business Owner', 'Open', date('now','+2 day'), ?, ?)
        """,
        (now, now),
    )
