from __future__ import annotations

from base64 import b64decode
from hmac import compare_digest
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings, get_settings
from app.database import SessionStore, utc_now


APP_VERSION = "2026.08.17.2"
templates = Jinja2Templates(directory="app/templates")


class EnterPayload(BaseModel):
    user_name: str = Field(min_length=2, max_length=60)
    environment: Literal["prod", "test"]

    @model_validator(mode="after")
    def normalize(self) -> "EnterPayload":
        self.user_name = " ".join(self.user_name.split())
        if len(self.user_name) < 2:
            raise ValueError("Name must contain at least 2 non-space characters.")
        return self


class CheckOutPayload(BaseModel):
    session_id: int = Field(ge=1)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if request.url.path == "/health":
            return await call_next(request)
        if not settings.auth_enabled or self._is_authorized(request, settings):
            return await call_next(request)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
            content={"detail": "Authentication required."},
        )

    @staticmethod
    def _is_authorized(request: Request, settings: Settings) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = b64decode(header.split(" ", 1)[1]).decode("utf-8")
        except Exception:
            return False
        username, separator, password = decoded.partition(":")
        if not separator:
            return False
        return compare_digest(username, settings.app_username) and compare_digest(
            password, settings.app_password
        )


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if (
            request.url.path == "/"
            or request.url.path.startswith("/static/")
            or request.url.path.startswith("/api/")
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    store = SessionStore(settings)
    store.initialize()

    app = FastAPI(
        title="AIDCC Genesys rozcestník",
        summary="Shared license launcher for Genesys Cloud production and test environments.",
    )
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(NoCacheMiddleware)
    app.add_middleware(BasicAuthMiddleware)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "page_title": "AIDCC Genesys rozcestník",
                "asset_version": APP_VERSION,
                "stale_after_minutes": settings.stale_after_minutes,
            },
        )

    legacy_base_path = settings.app_base_path
    if legacy_base_path:
        @app.get(legacy_base_path, include_in_schema=False)
        @app.get(f"{legacy_base_path}/", include_in_schema=False)
        async def legacy_redirect() -> RedirectResponse:
            return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": APP_VERSION}

    @app.get("/api/status")
    async def get_status(request: Request) -> dict:
        maybe_auto_release(request)
        settings, store = get_runtime(request)
        environments = []

        for environment in settings.environments:
            sessions = store.list_active_sessions(environment.key)
            occupied = len(sessions)
            free_slots = max(0, environment.max_slots - occupied)
            environments.append(
                {
                    "key": environment.key,
                    "label": environment.label,
                    "url": environment.url,
                    "max_slots": environment.max_slots,
                    "occupied_slots": occupied,
                    "free_slots": free_slots,
                    "is_full": occupied >= environment.max_slots,
                    "status_level": occupancy_level(occupied, environment.max_slots),
                    "sessions": sessions,
                }
            )

        all_sessions = store.list_active_sessions()
        global_occupied = len(all_sessions)
        global_limit = settings.global_max_slots
        global_free = None if global_limit is None else max(0, global_limit - global_occupied)

        return {
            "generated_at": utc_now().replace(microsecond=0).isoformat(),
            "global_max_slots": global_limit,
            "global_occupied_slots": global_occupied,
            "global_free_slots": global_free,
            "global_is_full": global_limit is not None and global_occupied >= global_limit,
            "stale_after_minutes": settings.stale_after_minutes,
            "auto_release_stale": settings.auto_release_stale,
            "environments": environments,
        }

    @app.get("/api/history")
    async def get_history(
        request: Request,
        limit: int = Query(default=settings.history_limit, ge=1, le=100),
    ) -> dict:
        maybe_auto_release(request)
        _, store = get_runtime(request)
        return {"items": store.list_recent_history(limit)}

    @app.post("/api/enter")
    async def enter_environment(request: Request, payload: EnterPayload) -> dict:
        maybe_auto_release(request)
        settings, store = get_runtime(request)
        environment = settings.environment(payload.environment)
        result, session = store.reserve_session(payload.user_name, payload.environment)

        if result == "global_full":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Je obsazený celkový limit licencí. Nikdo další se teď nesmí přihlásit.",
            )
        if result == "full":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{environment.label} je plná. Nikdo další se teď nesmí přihlásit.",
            )

        return {
            "message": "Přihlášení už je evidované." if result == "duplicate" else "Licence byla rezervována.",
            "already_active": result == "duplicate",
            "session": session,
            "redirect_url": environment.url,
        }

    @app.post("/api/check-out")
    async def check_out(request: Request, payload: CheckOutPayload) -> dict:
        _, store = get_runtime(request)
        released = store.release_session(payload.session_id, reason="manual")
        if released is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aktivní přihlášení už nebylo nalezeno.",
            )
        return {"message": "Přihlášení bylo ukončeno.", "released_session": released}

    return app


def get_runtime(request: Request) -> tuple[Settings, SessionStore]:
    return request.app.state.settings, request.app.state.store


def maybe_auto_release(request: Request) -> None:
    settings, store = get_runtime(request)
    if settings.auto_release_stale:
        store.release_stale_sessions()


def occupancy_level(occupied: int, max_slots: int) -> str:
    if occupied >= max_slots:
        return "full"
    if occupied >= max(1, max_slots - 1):
        return "warning"
    return "available"


app = create_app()
