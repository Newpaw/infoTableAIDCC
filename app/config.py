from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: str = "") -> str:
    raw = os.getenv(name, default).strip()
    if not raw or raw == "/":
        return ""
    return "/" + raw.strip("/")


@dataclass(frozen=True)
class Settings:
    app_username: str
    app_password: str
    app_base_path: str
    max_slots: int
    stale_after_minutes: int
    auto_release_stale: bool
    database_path: Path
    history_limit: int


@lru_cache
def get_settings() -> Settings:
    database_path = Path(os.getenv("DATABASE_PATH", "data/tracker.db"))
    return Settings(
        app_username=_require_env("APP_USERNAME"),
        app_password=_require_env("APP_PASSWORD"),
        app_base_path=_path_env("APP_BASE_PATH"),
        max_slots=max(1, int(os.getenv("MAX_SLOTS", "5"))),
        stale_after_minutes=max(1, int(os.getenv("STALE_AFTER_MINUTES", "480"))),
        auto_release_stale=_bool_env("AUTO_RELEASE_STALE", False),
        database_path=database_path,
        history_limit=max(1, int(os.getenv("HISTORY_LIMIT", "20"))),
    )
