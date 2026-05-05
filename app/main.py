"""MY-IA V2 — Point d'entrée principal.

Stack 100% Python : FastAPI sert HTML (Jinja2 + HTMX) ET API JSON
depuis un seul backend.

Architecture de routage :
  - Routes API (JSON)  → routers existants (compat my-ia v1)
  - Routes Web (HTML)  → app/web/ (à venir Phase 2)

Note : la versionnage `/api/v1/*` sera un refactor dédié post-boot.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.deps import get_chroma_client, get_ingestion_pipeline
from app.core.logging import setup_logging, setup_db_logging, stop_db_logging
from app.common.llm import get_provider, close_provider
from app.features.user.service import UserNotApprovedException
from app.features.sources.scheduler import start_scheduler, stop_scheduler
from app.web.jinja import make_templates, web_context
from app.web.auth import router as web_auth_router
from app.web.chat import router as web_chat_router
from app.web.documents import router as web_documents_router
from app.web.preferences import router as web_preferences_router
from app.web.deps import AuthRedirect, require_web_auth

# --- Routers ---
from app.features.health.router import router as health_router
from app.features.chat.router import router as chat_router, assistant_router, test_router
from app.features.ingestion.router import router as ingestion_router
from app.features.admin.router import router as admin_router
from app.features.auth.router import router as auth_router
from app.features.user.router import router as user_router
from app.features.conversations.router import router as conversations_router
from app.features.documents.router import router as documents_router
from app.features.preferences.router import router as preferences_router
from app.features.geo.router import router as geo_router
from app.features.config.public_router import router as public_config_router
from app.features.speech.router import router as speech_router
from app.features.admin.documents.router import router as admin_documents_router
from app.features.admin.documents.router import quota_router as admin_quota_router
from app.features.admin.collections.router import router as admin_collections_router
from app.features.admin.validation.router import router as admin_validation_router
from app.features.sources.router import (
    router as admin_sources_router,
    public_router as sources_public_router,
)
from app.features.audit.router import router as audit_router
from app.features.analytics.router import router as analytics_router
from app.features.logs.router import router as logs_router
from app.features.admin.config.router import router as admin_config_router
from app.features.admin.corpus.router import router as admin_corpus_router
from app.features.admin.permissions.router import router as admin_permissions_router
from app.features.collections.router import router as collections_router

# Logging structuré JSON
setup_logging()
logger = logging.getLogger(__name__)

# Chemins templates / static
APP_DIR = Path(__file__).parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


# ============================================================================
# LIFESPAN
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bootstrap / shutdown ordonné des composants."""
    logger.info("Starting MY-IA V2 API...")

    # ChromaDB
    chroma_client = get_chroma_client()
    if chroma_client:
        logger.info("ChromaDB initialized successfully")

    # Pipeline d'ingestion
    pipeline = get_ingestion_pipeline()
    if pipeline:
        logger.info("Ingestion pipeline initialized successfully")

    # Provider LLM (chargé depuis BDD)
    try:
        from app.db import async_session_maker
        from app.features.system.service import SystemConfigService
        from app.common.llm import set_provider_override, set_embedding_provider_override

        async with async_session_maker() as db_session:
            config_service = SystemConfigService(db_session)
            db_provider = await config_service.get("llm.provider", None)
            if db_provider:
                set_provider_override(db_provider)
                logger.info(f"LLM provider loaded from DB: {db_provider}")
            db_embedding_provider = await config_service.get("llm.embedding_provider", None)
            if db_embedding_provider:
                set_embedding_provider_override(db_embedding_provider)
                logger.info(f"Embedding provider loaded from DB: {db_embedding_provider}")
        provider = get_provider()
        logger.info(f"LLM provider initialized: {provider.provider_name}")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM provider: {e}")

    # Scheduler ré-indexation
    try:
        start_scheduler()
        logger.info("Source indexation scheduler started")
    except Exception as e:
        logger.warning(f"Failed to start scheduler: {e}")

    # Restaurer config debug depuis BDD
    try:
        from app.db import async_session_maker
        from app.features.admin.config.service import ConfigService

        async with async_session_maker() as db_session:
            await ConfigService.apply_debug_config_from_db(db_session)
            logger.info("Debug config restored from database")
    except Exception as e:
        logger.warning(f"Failed to restore debug config from DB: {e}")

    # Activer logs BDD (table app_logs)
    try:
        setup_db_logging()
        logger.info("Database log handler started")
    except Exception as e:
        logger.warning(f"Failed to start database log handler: {e}")

    yield

    # Shutdown
    logger.info("Shutting down MY-IA V2 API...")
    try:
        await stop_db_logging()
    except Exception as e:
        logger.warning(f"Error stopping db log handler: {e}")
    try:
        stop_scheduler()
    except Exception as e:
        logger.warning(f"Error stopping scheduler: {e}")
    await close_provider()
    logger.info("LLM provider closed")


# ============================================================================
# APP
# ============================================================================
app = FastAPI(
    title=settings.app_name,
    description="Chatbot RAG — stack 100% Python (FastAPI + Jinja2 + HTMX).",
    version=settings.app_version,
    lifespan=lifespan,
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Exception handler — utilisateur non approuvé
@app.exception_handler(UserNotApprovedException)
async def user_not_approved_exception_handler(
    request: Request, exc: UserNotApprovedException
):
    return JSONResponse(
        status_code=403,
        content={
            "detail": exc.message,
            "approval_status": exc.status.value,
        },
    )


# Exception handler — redirection vers /web/login si dépendance require_web_auth
@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(request: Request, exc: AuthRedirect):
    return RedirectResponse(url=exc.location, status_code=303)


# ============================================================================
# MIDDLEWARE (ordre d'ajout = inverse exécution ; dernier = plus externe)
# ============================================================================
from app.common.middleware.debug_timing import DebugTimingMiddleware
from app.common.middleware.access_log import AccessLogMiddleware
from app.common.middleware.request_context import RequestContextMiddleware

app.add_middleware(DebugTimingMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestContextMiddleware)

# Sessions signées (cookies HttpOnly pour l'auth web)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-replace-in-env"),
    session_cookie="my_ia_v2_session",
    https_only=os.environ.get("DEPLOY_ENV", "dev") != "dev",
    same_site="lax",
)

# CORS — middleware le plus EXTERNE (en-têtes présents même sur erreurs)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# STATIC & TEMPLATES (Jinja2 — globals wired via app.web.jinja)
# ============================================================================
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = make_templates(TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse, tags=["web"])
async def home(
    request: Request,
    user: dict = Depends(require_web_auth),
) -> HTMLResponse:
    """Page d'accueil V2 — protégée. Redirige vers /web/login si non auth."""
    return templates.TemplateResponse(
        request,
        "pages/home.html",
        web_context(request, title=settings.app_name, user=user),
    )


# ============================================================================
# ROUTERS WEB (HTML — Jinja2 + HTMX)
# ============================================================================
app.include_router(web_auth_router)
app.include_router(web_chat_router)
app.include_router(web_documents_router)
app.include_router(web_preferences_router)


# ============================================================================
# ROUTERS API (compat my-ia v1 — refactor /api/v1/* à venir)
# ============================================================================

# Health & Metrics
app.include_router(health_router)

# Auth & Users
app.include_router(auth_router)
app.include_router(user_router)

# User Features
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(preferences_router)
app.include_router(collections_router)

# Chat
app.include_router(chat_router)
app.include_router(assistant_router)
app.include_router(test_router)

# Ingestion
app.include_router(ingestion_router)

# Geo (public)
app.include_router(geo_router, prefix="/geo", tags=["Geo"])

# Config publique
app.include_router(public_config_router, prefix="/api", tags=["Configuration"])

# Speech-to-Text
app.include_router(speech_router, prefix="/api", tags=["Speech-to-Text"])

# Admin
app.include_router(admin_router)
app.include_router(admin_documents_router)
app.include_router(admin_quota_router)
app.include_router(admin_collections_router)
app.include_router(admin_validation_router, prefix="/api/admin", tags=["Admin - Validation"])
app.include_router(admin_sources_router, prefix="/api", tags=["Admin - Sources"])
app.include_router(sources_public_router, prefix="/api", tags=["Sources"])
app.include_router(audit_router, prefix="/api/admin", tags=["Admin - Audit"])
app.include_router(analytics_router, prefix="/api/admin", tags=["Admin - Analytics"])
app.include_router(logs_router, prefix="/api/admin", tags=["Admin - Logs"])
app.include_router(admin_config_router, prefix="/api/admin", tags=["Admin - Configuration"])
app.include_router(admin_corpus_router)
app.include_router(admin_permissions_router)


logger.info(f"{settings.app_name} V2 initialized successfully")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
