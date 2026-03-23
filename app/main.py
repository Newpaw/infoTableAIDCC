from __future__ import annotations

from base64 import b64decode
from hmac import compare_digest

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings, get_settings
from app.database import SessionStore, utc_now


templates = Jinja2Templates(directory="app/templates")


class CheckInPayload(BaseModel):
    user_name: str = Field(min_length=2, max_length=60)
    note: str = Field(default="", max_length=180)

    @model_validator(mode="after")
    def normalize(self) -> "CheckInPayload":
        self.user_name = " ".join(self.user_name.split())
        self.note = " ".join(self.note.split())
        if len(self.user_name) < 2:
            raise ValueError("Name must contain at least 2 non-space characters.")
        return self


class CheckOutPayload(BaseModel):
    session_id: int | None = Field(default=None, ge=1)
    user_name: str | None = Field(default=None, min_length=2, max_length=60)

    @model_validator(mode="after")
    def validate_target(self) -> "CheckOutPayload":
        if self.user_name is not None:
            self.user_name = " ".join(self.user_name.split())
        if not self.session_id and not self.user_name:
            raise ValueError("Provide session_id or user_name.")
        return self


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not self._is_authorized(request, settings):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
                content={"detail": "Authentication required."},
            )
        return await call_next(request)

    def _is_authorized(self, request: Request, settings: Settings) -> bool:
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


def create_app() -> FastAPI:
    settings = get_settings()
    store = SessionStore(settings)
    store.initialize()

    app = FastAPI(
        title="Genesys Cloud License Tracker",
        summary="Manual occupancy board for shared Genesys Cloud licenses.",
    )
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(BasicAuthMiddleware)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "page_title": "Genesys Cloud License Tracker",
                "max_slots": settings.max_slots,
                "stale_after_minutes": settings.stale_after_minutes,
                "auto_release_stale": settings.auto_release_stale,
            },
        )

    @app.get("/api/status")
    async def get_status(request: Request) -> dict:
        maybe_auto_release(request)
        settings, store = get_runtime(request)
        sessions = store.list_active_sessions()
        occupied = len(sessions)
        free_slots = max(0, settings.max_slots - occupied)
        status_level = occupancy_level(occupied, settings.max_slots)
        return {
            "generated_at": utc_now().replace(microsecond=0).isoformat(),
            "occupied_slots": occupied,
            "free_slots": free_slots,
            "max_slots": settings.max_slots,
            "is_full": occupied >= settings.max_slots,
            "status_level": status_level,
            "stale_after_minutes": settings.stale_after_minutes,
            "auto_release_stale": settings.auto_release_stale,
            "sessions": sessions,
        }

    @app.get("/api/history")
    async def get_history(
        request: Request,
        limit: int = Query(default=settings.history_limit, ge=1, le=100),
    ) -> dict:
        maybe_auto_release(request)
        _, store = get_runtime(request)
        return {
            "items": store.list_recent_history(limit),
        }

    @app.post("/api/check-in", status_code=status.HTTP_201_CREATED)
    async def check_in(request: Request, payload: CheckInPayload) -> dict:
        maybe_auto_release(request)
        _, store = get_runtime(request)
        result, session = store.reserve_session(payload.user_name, payload.note)
        if result == "duplicate":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user already has an active session.",
            )
        if result == "full":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No free Genesys Cloud slots are currently available.",
            )
        return {"message": "Slot occupied.", "session": session}

    @app.post("/api/check-out")
    async def check_out(request: Request, payload: CheckOutPayload) -> dict:
        settings, store = get_runtime(request)
        released = store.release_session(
            session_id=payload.session_id,
            user_name=payload.user_name,
            reason="manual",
        )
        if released is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No matching active session found.",
            )
        return {
            "message": "Slot released.",
            "released_session": released,
            "max_slots": settings.max_slots,
        }

    @app.post("/api/force-release/{session_id}")
    async def force_release(request: Request, session_id: int) -> dict:
        settings, store = get_runtime(request)
        released = store.release_session(session_id=session_id, reason="force")
        if released is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No matching active session found.",
            )
        return {
            "message": "Session force-released.",
            "released_session": released,
            "max_slots": settings.max_slots,
        }

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
