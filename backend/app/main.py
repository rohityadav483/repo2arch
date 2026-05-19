"""
main.py
-------
FastAPI application factory for Repo2Arch.

Registers:
  - CORS middleware
  - Request logging middleware
  - API router (all routes)
  - Startup / shutdown lifecycle events
  - Global exception handler

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.routes import router

# ------------------------------------------------------------------ #
# Logging configuration                                               #
# ------------------------------------------------------------------ #

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Lifespan — startup / shutdown                                       #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup (before first request) and once on shutdown.
    Use for warming up connections, validating config, etc.
    """
    # ── Startup ──────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(" %s v%s starting", settings.APP_NAME, settings.APP_VERSION)
    logger.info(" Debug mode : %s", settings.DEBUG)
    logger.info(" HF model   : %s", settings.HF_MODEL)
    logger.info(" Clone dir  : %s", settings.REPO_CLONE_DIR)
    logger.info("=" * 60)

    # Validate Supabase connectivity at boot
    from app.services.supabase_client import db
    if db.ping():
        logger.info("Supabase connection OK")
    else:
        logger.warning(
            "Supabase unreachable at startup — "
            "history and caching will be unavailable"
        )

    yield   # app is running

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("%s shutting down", settings.APP_NAME)


# ------------------------------------------------------------------ #
# App factory                                                          #
# ------------------------------------------------------------------ #

def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Automatically generate architecture diagrams, "
            "dependency graphs, and AI summaries from any public "
            "GitHub repository."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ── Request logging middleware ────────────────────────────────────
    @application.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()

        logger.info(
            "[%s] → %s %s",
            request_id,
            request.method,
            request.url.path,
        )

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "[%s] ← %d  %.1fms",
            request_id,
            response.status_code,
            elapsed_ms,
        )
        # Attach request ID to response headers for tracing
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Global exception handler ─────────────────────────────────────
    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "An internal server error occurred.",
                "detail": str(exc) if settings.DEBUG else None,
            },
        )

    # ── Routes ───────────────────────────────────────────────────────
    application.include_router(router, prefix="/api/v1")

    # ── Root redirect ─────────────────────────────────────────────────
    @application.get("/", include_in_schema=False)
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }

    return application


# ------------------------------------------------------------------ #
# App instance — referenced by uvicorn                               #
# ------------------------------------------------------------------ #

app = create_app()
