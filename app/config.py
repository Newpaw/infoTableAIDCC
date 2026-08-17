from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv


load_dotenv()


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
class EnvironmentConfig:
    key: str
    label: str
    url: str
    max_slots: int


@dataclass(frozen=True)
class Settings:
    app_username: str
    app_password: str
    app_base_path: str
    environments: tuple[EnvironmentConfig, ...]
    global_max_slots: int | None
    stale_after_minutes: int
    auto_release_stale: bool
    database_path: Path
    history_limit: int

    @property
    def auth_enabled(self) -> bool:
        return bool(self.app_username and self.app_password)

    def environment(self, key: str) -> EnvironmentConfig:
        normalized = key.strip().lower()
        for environment in self.environments:
            if environment.key == normalized:
                return environment
        raise KeyError(key)


@lru_cache
def get_settings() -> Settings:
    username = os.getenv("APP_USERNAME", "").strip()
    password = os.getenv("APP_PASSWORD", "").strip()
    if bool(username) != bool(password):
        raise RuntimeError("Set both APP_USERNAME and APP_PASSWORD, or leave both empty.")

    return Settings(
        app_username=username,
        app_password=password,
        app_base_path=_path_env("APP_BASE_PATH"),
        environments=(
            EnvironmentConfig(
                key="prod",
                label="Produkce",
                url=os.getenv("PROD_URL", "https://login.mypurecloud.de").strip(),
                max_slots=max(1, int(os.getenv("PROD_MAX_SLOTS", "5"))),
            ),
            EnvironmentConfig(
                key="test",
                label="Test",
                url=os.getenv("TEST_URL", "https://login.mypurecloud.ie").strip(),
                max_slots=max(1, int(os.getenv("TEST_MAX_SLOTS", "5"))),
            ),
        ),
        global_max_slots=(lambda value: value if value > 0 else None)(int(os.getenv("GLOBAL_MAX_SLOTS", "5"))),
        stale_after_minutes=max(1, int(os.getenv("STALE_AFTER_MINUTES", "480"))),
        auto_release_stale=_bool_env("AUTO_RELEASE_STALE", False),
        database_path=Path(os.getenv("DATABASE_PATH", "data/tracker.db")),
        history_limit=max(1, int(os.getenv("HISTORY_LIMIT", "30"))),
    )
