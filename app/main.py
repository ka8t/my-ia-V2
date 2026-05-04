"""MY-IA V2 — Application FastAPI.

Sert HTML (Jinja2) et API JSON depuis un seul backend Python.
Architecture : `app/api/v1/` pour le JSON, `app/web/` pour le HTML.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

APP_DIR = Path(__file__).parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap : config BDD, providers, etc. — branché en Phase 1
    yield


app = FastAPI(
    title="MY-IA V2",
    version="2.0.0-dev",
    description="Chatbot RAG — stack 100% Python (FastAPI + Jinja2 + HTMX).",
    lifespan=lifespan,
)

# Sessions signées (cookies HttpOnly pour l'auth web)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-replace-in-env"),
    session_cookie="my_ia_v2_session",
    https_only=os.environ.get("DEPLOY_ENV", "dev") != "dev",
    same_site="lax",
)

# Static & Templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": app.version})


@app.get("/", response_class=HTMLResponse, tags=["web"])
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "pages/home.html", {"title": "MY-IA V2"}
    )


# Routers : seront montés en Phase 1 (API) et Phase 2+ (Web)
# from app.api.v1 import api_v1_router
# from app.web import web_router
# app.include_router(api_v1_router, prefix="/api/v1")
# app.include_router(web_router)
