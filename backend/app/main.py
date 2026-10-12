"""FastAPI application entrypoint.

Run with::

    cd backend && uvicorn app.main:app --reload --port 8000

Interactive docs at ``/docs``; health at ``/api/settings/health``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_audit,
    routes_auth,
    routes_chat,
    routes_clients,
    routes_dashboard,
    routes_depreciation,
    routes_files,
    routes_reference,
    routes_review,
    routes_settings,
    routes_updates,
    routes_workflows,
)
from app.core.config import get_settings
from app.core.db import init_database
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.tls import configure_global_tls
from app.services.bootstrap_service import bootstrap
from app.services.news_service import BackgroundRefresher, get_news_service

settings = get_settings()
configure_logging(settings.log_level, json_output=settings.is_production)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare storage and schema, and report the security posture at boot."""
    settings.ensure_directories()
    configure_global_tls(settings)
    init_database()
    bootstrap()

    logger.info(
        "%s %s starting in %s mode",
        settings.app_name,
        settings.app_version,
        settings.app_env.value,
    )

    # Surface a degraded privacy posture loudly at startup — these are the
    # settings an operator must never ship by accident.
    if settings.auth_disabled:
        logger.warning(
            "AUTH_DISABLED=true: every request is treated as '%s'. "
            "Development only.",
            settings.dev_default_role.value,
        )
    if not settings.llm_egress_guard_enabled:
        logger.error(
            "SECURITY: the LLM egress guard is DISABLED. Unmasked client data "
            "could be transmitted to the model provider."
        )
    if settings.allow_cloud_ocr_fallback:
        logger.warning(
            "SECURITY: cloud OCR fallback is enabled. Unmasked page images may "
            "be sent to a third-party model."
        )
    if not settings.gemini_api_key:
        logger.info(
            "No Gemini API key configured; LLM calls return deterministic "
            "stubs. The pipeline and chatbot remain fully operational."
        )

    # Industry Updates: refresh the public feeds in the background so no page
    # load waits on an agency website. Off when NEWS_ENABLED=false.
    refresher: BackgroundRefresher | None = None
    if settings.news_enabled:
        refresher = BackgroundRefresher(get_news_service(), settings.news_refresh_seconds)
        refresher.start()

    yield
    if refresher is not None:
        refresher.stop()
    logger.info("%s shutting down", settings.app_name)


app = FastAPI(
    title="TaxScraper API",
    version=settings.app_version,
    description=(
        "US tax automation platform: privacy-preserving workpaper processing "
        "and RAG-grounded tax research.\n\n"
        "**Privacy model** — uploaded documents are encrypted at rest, "
        "sensitive values are tokenized before any AI processing, and real "
        "values are restored locally only when the final output package is "
        "generated. The language model never receives real taxpayer data."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# SECURITY: explicit origin allow-list. Never "*" — these endpoints return
# taxpayer data to authenticated staff, and a wildcard would let any site the
# user visits read it via their browser session.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

register_exception_handlers(app)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach hardening headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # API responses are never a page; a restrictive CSP costs nothing here.
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    # Downloads carry taxpayer data — keep them out of shared caches.
    response.headers["Cache-Control"] = "no-store"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


for router in (
    routes_auth.router,
    routes_dashboard.router,
    routes_files.router,
    routes_workflows.router,
    routes_review.router,
    routes_audit.router,
    routes_settings.router,
    routes_chat.router,
    routes_depreciation.router,
    routes_reference.router,
    routes_clients.router,
    routes_updates.router,
):
    app.include_router(router)


@app.get("/", tags=["meta"])
def root() -> dict[str, object]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/settings/health",
        "privacy": (
            "Client data is masked before AI processing and restored only "
            "locally, after processing completes."
        ),
    }


@app.get("/api/health", tags=["meta"])
def health_alias(request: Request) -> JSONResponse:
    """Convenience alias for ``/api/settings/health``."""
    return JSONResponse({"status": "ok", "detail": "See /api/settings/health"})
