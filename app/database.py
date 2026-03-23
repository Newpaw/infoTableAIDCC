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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    note TEXT,
                    checked_in_at TEXT NOT NULL,
                    released_at TEXT,
                    release_reason TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_active
                ON sessions (released_at, checked_in_at);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_name
                ON sessions (user_name, released_at);
                """
            )

    def list_active_sessions(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_name, note, checked_in_at
                FROM sessions
                WHERE released_at IS NULL
                ORDER BY checked_in_at ASC
                """
            ).fetchall()
        return [self._serialize_active_row(row) for row in rows]

    def list_recent_history(self, limit: int | None = None) -> list[dict]:
        query_limit = limit or self.settings.history_limit
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_name, note, checked_in_at, released_at, release_reason
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

    def reserve_session(self, user_name: str, note: str) -> tuple[str, dict | None]:
        checked_in_at = isoformat(utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT 1
                FROM sessions
                WHERE lower(user_name) = lower(?) AND released_at IS NULL
                LIMIT 1
                """,
                (user_name,),
            ).fetchone()
            if duplicate is not None:
                return "duplicate", None

            active_count = connection.execute(
                "SELECT COUNT(*) AS total FROM sessions WHERE released_at IS NULL"
            ).fetchone()
            if int(active_count["total"]) >= self.settings.max_slots:
                return "full", None

            cursor = connection.execute(
                """
                INSERT INTO sessions (user_name, note, checked_in_at, released_at, release_reason)
                VALUES (?, ?, ?, NULL, NULL)
                """,
                (user_name, note or None, checked_in_at),
            )
            row = connection.execute(
                """
                SELECT id, user_name, note, checked_in_at
                FROM sessions
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return "created", self._serialize_active_row(row)

    def release_session(
        self,
        *,
        session_id: int | None = None,
        user_name: str | None = None,
        reason: str,
    ) -> dict | None:
        with self._connect() as connection:
            if session_id is not None:
                row = connection.execute(
                    """
                    SELECT id, user_name, note, checked_in_at
                    FROM sessions
                    WHERE id = ? AND released_at IS NULL
                    """,
                    (session_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT id, user_name, note, checked_in_at
                    FROM sessions
                    WHERE lower(user_name) = lower(?) AND released_at IS NULL
                    ORDER BY checked_in_at DESC
                    LIMIT 1
                    """,
                    (user_name,),
                ).fetchone()

            if row is None:
                return None

            connection.execute(
                """
                UPDATE sessions
                SET released_at = ?, release_reason = ?
                WHERE id = ?
                """,
                (isoformat(utc_now()), reason, row["id"]),
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
        return connection

    def _serialize_active_row(self, row: sqlite3.Row) -> dict:
        checked_in_at = parse_timestamp(row["checked_in_at"])
        age = utc_now() - checked_in_at
        age_minutes = self._duration_minutes(checked_in_at, utc_now())
        stale = age >= timedelta(minutes=self.settings.stale_after_minutes)
        return {
            "id": row["id"],
            "user_name": row["user_name"],
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
