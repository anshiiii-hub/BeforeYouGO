"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import accountability, admin, analyzer, auth, events, organizer, student
from app.core.config import BACKEND_DIR, PROJECT_ROOT, get_settings
from app.core.db import get_engine, session_scope
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_ctx
from app.services.sources.registry import seed_sources
from app.services.sync import sync_all_sources

logger = logging.getLogger("byg.app")

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def _start_scheduler():
    settings = get_settings()
    if not settings.enable_scheduler or settings.env == "test":
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        sync_all_sources,
        "interval",
        hours=settings.sync_interval_hours,
        id="sync-all-sources",
        max_instances=1,
        coalesce=True,
        kwargs={"trigger": "scheduled"},
    )
    scheduler.start()
    logger.info("scheduler started", extra={"extra_fields": {"interval_hours": settings.sync_interval_hours}})
    return scheduler


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging("INFO")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        with session_scope() as db:
            seed_sources(db)
    except Exception:  # database unreachable: the app still starts, /api/ready reports it
        logger.exception("could not seed the source catalogue")
    scheduler = _start_scheduler()
    if settings.sync_on_startup and scheduler is not None:
        scheduler.add_job(sync_all_sources, id="startup-sync", kwargs={"trigger": "startup"})
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="BeforeYouGo API",
        version="0.1.0",
        description="Event intelligence and accountability platform. Interactive docs at /api/docs.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Response-Time-ms"] = str(int((time.perf_counter() - started) * 1000))
        return response

    install_error_handlers(app)

    @app.get("/api/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ready", tags=["ops"])
    def ready() -> JSONResponse:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
        except Exception as exc:
            return JSONResponse({"status": "unavailable", "database": "down", "detail": type(exc).__name__}, status_code=503)
        return JSONResponse({"status": "ready", "database": "up"})

    for module in (auth, events, student, analyzer, organizer, accountability, admin):
        app.include_router(module.router)

    if FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Unknown API route."}}, status_code=404)
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
_ = BACKEND_DIR, Path
