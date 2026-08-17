from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

from app.config import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database_path = settings.database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    environment TEXT NOT NULL DEFAULT 'prod',
                    note TEXT,
                    checked_in_at TEXT NOT NULL,
                    released_at TEXT,
                    release_reason TEXT
                )
                """
            )

            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "environment" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN environment TEXT NOT NULL DEFAULT 'prod'"
                )

            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_active_environment
                ON sessions (environment, released_at, checked_in_at);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_environment
                ON sessions (user_name, environment, released_at);
                """
            )

    def list_active_sessions(self, environment: str | None = None) -> list[dict]:
        params: tuple[str, ...] = ()
        where = "released_at IS NULL"
        if environment is not None:
            where += " AND environment = ?"
            params = (environment,)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, user_name, environment, note, checked_in_at
                FROM sessions
                WHERE {where}
                ORDER BY checked_in_at ASC
                """,
                params,
            ).fetchall()
        return [self._serialize_active_row(row) for row in rows]

    def list_recent_history(self, limit: int | None = None) -> list[dict]:
        query_limit = limit or self.settings.history_limit
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_name, environment, note, checked_in_at, released_at, release_reason
                FROM sessions
                ORDER BY checked_in_at DESC
                LIMIT ?
                """,
                (query_limit,),
            ).fetchall()

        history = []
        now = utc_now()
        for row in rows:
            checked_in_at = parse_timestamp(row["checked_in_at"])
            released_at = parse_timestamp(row["released_at"])
            history.append(
                {
                    "id": row["id"],
                    "user_name": row["user_name"],
                    "environment": row["environment"],
                    "note": row["note"] or "",
                    "checked_in_at": row["checked_in_at"],
                    "released_at": row["released_at"],
                    "release_reason": row["release_reason"] or "",
                    "duration_minutes": self._duration_minutes(
                        checked_in_at, released_at or now
                    ),
                }
            )
        return history

    def reserve_session(
        self,
        user_name: str,
        environment: str,
        note: str = "",
    ) -> tuple[str, dict | None]:
        environment_config = self.settings.environment(environment)
        checked_in_at = isoformat(utc_now())

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT id, user_name, environment, note, checked_in_at
                FROM sessions
                WHERE lower(user_name) = lower(?)
                  AND environment = ?
                  AND released_at IS NULL
                ORDER BY checked_in_at DESC
                LIMIT 1
                """,
                (user_name, environment),
            ).fetchone()
            if duplicate is not None:
                return "duplicate", self._serialize_active_row(duplicate)

            if self.settings.global_max_slots is not None:
                global_active_count = connection.execute(
                    "SELECT COUNT(*) AS total FROM sessions WHERE released_at IS NULL"
                ).fetchone()
                if int(global_active_count["total"]) >= self.settings.global_max_slots:
                    return "global_full", None

            active_count = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM sessions
                WHERE environment = ? AND released_at IS NULL
                """,
                (environment,),
            ).fetchone()
            if int(active_count["total"]) >= environment_config.max_slots:
                return "full", None

            cursor = connection.execute(
                """
                INSERT INTO sessions (
                    user_name, environment, note, checked_in_at, released_at, release_reason
                )
                VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (user_name, environment, note or None, checked_in_at),
            )
            row = connection.execute(
                """
                SELECT id, user_name, environment, note, checked_in_at
                FROM sessions
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        return "created", self._serialize_active_row(row)

    def release_session(self, session_id: int, reason: str = "manual") -> dict | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, user_name, environment, note, checked_in_at
                FROM sessions
                WHERE id = ? AND released_at IS NULL
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None

            connection.execute(
                """
                UPDATE sessions
                SET released_at = ?, release_reason = ?
                WHERE id = ?
                """,
                (isoformat(utc_now()), reason, session_id),
            )
        return self._serialize_active_row(row)

    def release_stale_sessions(self) -> int:
        now = utc_now()
        threshold = isoformat(now - timedelta(minutes=self.settings.stale_after_minutes))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET released_at = ?, release_reason = 'auto'
                WHERE released_at IS NULL AND checked_in_at <= ?
                """,
                (isoformat(now), threshold),
            )
        return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _serialize_active_row(self, row: sqlite3.Row) -> dict:
        checked_in_at = parse_timestamp(row["checked_in_at"])
        now = utc_now()
        age_minutes = self._duration_minutes(checked_in_at, now)
        stale = (now - checked_in_at) >= timedelta(
            minutes=self.settings.stale_after_minutes
        )
        return {
            "id": row["id"],
            "user_name": row["user_name"],
            "environment": row["environment"],
            "note": row["note"] or "",
            "checked_in_at": row["checked_in_at"],
            "age_minutes": age_minutes,
            "stale": stale,
        }

    @staticmethod
    def _duration_minutes(start: datetime | None, end: datetime | None) -> int:
        if start is None or end is None:
            return 0
        return max(0, int((end - start).total_seconds() // 60))
