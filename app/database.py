from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo

from app.config import Settings


PRAGUE = ZoneInfo("Europe/Prague")


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
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()}
            if "environment" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN environment TEXT NOT NULL DEFAULT 'prod'")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_active_environment
                ON sessions (environment, released_at, checked_in_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_user_environment
                ON sessions (user_name, environment, released_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_checked_in
                ON sessions (checked_in_at);
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
                f"SELECT id, user_name, environment, note, checked_in_at FROM sessions WHERE {where} ORDER BY checked_in_at ASC",
                params,
            ).fetchall()
        return [self._serialize_active_row(row) for row in rows]

    def list_recent_history(self, limit: int | None = None) -> list[dict]:
        query_limit = limit or self.settings.history_limit
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, user_name, environment, note, checked_in_at, released_at, release_reason FROM sessions ORDER BY checked_in_at DESC LIMIT ?",
                (query_limit,),
            ).fetchall()
        return [self._serialize_history_row(row) for row in rows]

    def analytics(self, days: int = 30) -> dict:
        now = utc_now()
        params: tuple[str, ...] = ()
        where = ""
        if days > 0:
            where = "WHERE checked_in_at >= ?"
            params = (isoformat(now - timedelta(days=days)),)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, user_name, environment, note, checked_in_at, released_at, release_reason FROM sessions {where} ORDER BY checked_in_at DESC",
                params,
            ).fetchall()
        sessions = [self._serialize_history_row(row, now=now) for row in rows]
        durations = [item["duration_minutes"] for item in sessions]
        completed = [item for item in sessions if item["released_at"]]
        active = [item for item in sessions if not item["released_at"]]

        by_environment: dict[str, dict] = {}
        for key in ("prod", "test"):
            env_sessions = [item for item in sessions if item["environment"] == key]
            env_durations = [item["duration_minutes"] for item in env_sessions]
            by_environment[key] = {
                "sessions": len(env_sessions),
                "total_minutes": sum(env_durations),
                "average_minutes": self._average(env_durations),
                "median_minutes": self._median(env_durations),
                "long_sessions": sum(1 for item in env_sessions if item["duration_minutes"] >= self.settings.alert_after_minutes),
            }

        user_stats: dict[str, dict] = {}
        for item in sessions:
            normalized = item["user_name"].strip().casefold()
            if normalized not in user_stats:
                user_stats[normalized] = {
                    "user_name": item["user_name"], "sessions": 0, "total_minutes": 0,
                    "longest_minutes": 0, "prod_sessions": 0, "test_sessions": 0,
                }
            stats = user_stats[normalized]
            stats["sessions"] += 1
            stats["total_minutes"] += item["duration_minutes"]
            stats["longest_minutes"] = max(stats["longest_minutes"], item["duration_minutes"])
            stats[f"{item['environment']}_sessions"] += 1
        top_users = []
        for stats in user_stats.values():
            stats["average_minutes"] = round(stats["total_minutes"] / stats["sessions"])
            top_users.append(stats)
        top_users.sort(key=lambda item: (item["total_minutes"], item["sessions"]), reverse=True)

        daily: dict[str, dict] = defaultdict(lambda: {"prod_minutes": 0, "test_minutes": 0, "sessions": 0})
        hourly = [{"hour": hour, "sessions": 0} for hour in range(24)]
        for item in sessions:
            start = parse_timestamp(item["checked_in_at"])
            local_start = start.astimezone(PRAGUE)
            date_key = local_start.date().isoformat()
            daily[date_key][f"{item['environment']}_minutes"] += item["duration_minutes"]
            daily[date_key]["sessions"] += 1
            hourly[local_start.hour]["sessions"] += 1
        daily_usage = []
        if days > 0:
            for offset in range(days - 1, -1, -1):
                date_key = (now.astimezone(PRAGUE).date() - timedelta(days=offset)).isoformat()
                daily_usage.append({"date": date_key, **daily[date_key]})
        else:
            for date_key in sorted(daily):
                daily_usage.append({"date": date_key, **daily[date_key]})

        long_sessions = [item for item in sessions if item["duration_minutes"] >= self.settings.alert_after_minutes]
        long_sessions.sort(key=lambda item: item["duration_minutes"], reverse=True)
        return {
            "generated_at": now.replace(microsecond=0).isoformat(),
            "period_days": days,
            "thresholds": {"alert_minutes": self.settings.alert_after_minutes, "critical_minutes": self.settings.critical_after_minutes},
            "summary": {
                "total_sessions": len(sessions), "completed_sessions": len(completed), "active_sessions": len(active),
                "total_minutes": sum(durations), "average_minutes": self._average(durations),
                "median_minutes": self._median(durations), "longest_minutes": max(durations, default=0),
                "long_sessions": len(long_sessions),
                "critical_sessions": sum(1 for item in sessions if item["duration_minutes"] >= self.settings.critical_after_minutes),
                "peak_concurrent": self._peak_concurrent(sessions),
            },
            "by_environment": by_environment,
            "top_users": top_users[:20],
            "daily_usage": daily_usage,
            "hourly_checkins": hourly,
            "long_sessions": long_sessions[:30],
            "session_log": sessions[:500],
        }

    def reserve_session(self, user_name: str, environment: str, note: str = "") -> tuple[str, dict | None]:
        environment_config = self.settings.environment(environment)
        checked_in_at = isoformat(utc_now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT id, user_name, environment, note, checked_in_at FROM sessions WHERE lower(user_name)=lower(?) AND environment=? AND released_at IS NULL ORDER BY checked_in_at DESC LIMIT 1",
                (user_name, environment),
            ).fetchone()
            if duplicate is not None:
                return "duplicate", self._serialize_active_row(duplicate)
            if self.settings.global_max_slots is not None:
                global_active_count = connection.execute("SELECT COUNT(*) AS total FROM sessions WHERE released_at IS NULL").fetchone()
                if int(global_active_count["total"]) >= self.settings.global_max_slots:
                    return "global_full", None
            active_count = connection.execute("SELECT COUNT(*) AS total FROM sessions WHERE environment=? AND released_at IS NULL", (environment,)).fetchone()
            if int(active_count["total"]) >= environment_config.max_slots:
                return "full", None
            cursor = connection.execute(
                "INSERT INTO sessions (user_name, environment, note, checked_in_at, released_at, release_reason) VALUES (?, ?, ?, ?, NULL, NULL)",
                (user_name, environment, note or None, checked_in_at),
            )
            row = connection.execute("SELECT id, user_name, environment, note, checked_in_at FROM sessions WHERE id=?", (cursor.lastrowid,)).fetchone()
        return "created", self._serialize_active_row(row)

    def release_session(self, session_id: int, reason: str = "manual") -> dict | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT id, user_name, environment, note, checked_in_at FROM sessions WHERE id=? AND released_at IS NULL", (session_id,)).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE sessions SET released_at=?, release_reason=? WHERE id=?", (isoformat(utc_now()), reason, session_id))
        return self._serialize_active_row(row)

    def release_stale_sessions(self) -> int:
        now = utc_now()
        threshold = isoformat(now - timedelta(minutes=self.settings.stale_after_minutes))
        with self._connect() as connection:
            cursor = connection.execute("UPDATE sessions SET released_at=?, release_reason='auto' WHERE released_at IS NULL AND checked_in_at <= ?", (isoformat(now), threshold))
        return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _alert_level(self, duration_minutes: int) -> str:
        if duration_minutes >= self.settings.critical_after_minutes:
            return "critical"
        if duration_minutes >= self.settings.alert_after_minutes:
            return "warning"
        return "normal"

    def _serialize_active_row(self, row: sqlite3.Row) -> dict:
        checked_in_at = parse_timestamp(row["checked_in_at"])
        now = utc_now()
        age_minutes = self._duration_minutes(checked_in_at, now)
        return {
            "id": row["id"], "user_name": row["user_name"], "environment": row["environment"], "note": row["note"] or "",
            "checked_in_at": row["checked_in_at"], "age_minutes": age_minutes, "alert_level": self._alert_level(age_minutes),
            "overdue": age_minutes >= self.settings.alert_after_minutes,
            "critical": age_minutes >= self.settings.critical_after_minutes,
            "stale": (now - checked_in_at) >= timedelta(minutes=self.settings.stale_after_minutes),
        }

    def _serialize_history_row(self, row: sqlite3.Row, *, now: datetime | None = None) -> dict:
        now = now or utc_now()
        checked_in_at = parse_timestamp(row["checked_in_at"])
        released_at = parse_timestamp(row["released_at"])
        duration = self._duration_minutes(checked_in_at, released_at or now)
        return {
            "id": row["id"], "user_name": row["user_name"], "environment": row["environment"], "note": row["note"] or "",
            "checked_in_at": row["checked_in_at"], "released_at": row["released_at"], "release_reason": row["release_reason"] or "",
            "duration_minutes": duration, "alert_level": self._alert_level(duration),
        }

    @staticmethod
    def _duration_minutes(start: datetime | None, end: datetime | None) -> int:
        if start is None or end is None:
            return 0
        return max(0, int((end - start).total_seconds() // 60))

    @staticmethod
    def _average(values: list[int]) -> int:
        return round(sum(values) / len(values)) if values else 0

    @staticmethod
    def _median(values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        return ordered[midpoint] if len(ordered) % 2 else round((ordered[midpoint - 1] + ordered[midpoint]) / 2)

    @staticmethod
    def _peak_concurrent(sessions: list[dict]) -> int:
        events: list[tuple[datetime, int]] = []
        now = utc_now()
        for item in sessions:
            events.append((parse_timestamp(item["checked_in_at"]), 1))
            events.append((parse_timestamp(item["released_at"]) or now, -1))
        events.sort(key=lambda item: (item[0], item[1]))
        current = 0
        peak = 0
        for _, delta in events:
            current = max(0, current + delta)
            peak = max(peak, current)
        return peak
