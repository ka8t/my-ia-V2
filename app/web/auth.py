"""Web authentication routes (HTML — Phase 2.5).

GET  /web/login   — render the login page
POST /web/login   — verify credentials, set session cookie, redirect
POST /web/logout  — clear the session, redirect to /web/login

Uses ``fastapi-users``' ``PasswordHelper`` (argon2 via pwdlib) to verify the
hashed password — same verification path as the JSON ``/auth/jwt/login``,
keeping the two stacks in sync.

CSRF: the form embeds a hidden token rendered by ``web_context``. Each POST
verifies it before any DB lookup. Token is rotated on successful login.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import User
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

router = APIRouter(prefix="/web", tags=["Web - Auth"])
templates = make_templates(TEMPLATES_DIR)
_password_helper = PasswordHelper()


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/login
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request) -> HTMLResponse:
    """Render the login page. If already authenticated, redirect to home."""
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request, "pages/auth/login.html", web_context(request)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/login
# ─────────────────────────────────────────────────────────────────────────────
def _login_error(request: Request, message: str, status_code: int = 401) -> HTMLResponse:
    """Render the error partial — used for every failure path so that
    HTMX (hx-target=#login-error) gets a swap-friendly response."""
    return templates.TemplateResponse(
        request,
        "partials/auth/login-error.html",
        web_context(request, error=message),
        status_code=status_code,
    )


@router.post("/login")
async def login_post(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    # 1) CSRF
    if not verify_csrf_token(request, csrf_token):
        return _login_error(
            request,
            "Session expirée. Rechargez la page et réessayez.",
            status_code=400,
        )

    # 2) Lookup user (case-insensitive on email is a future improvement)
    # .unique() required before scalar_one_or_none() because the User model
    # has eager-loaded joined relations (see CLAUDE.md "Tests" section).
    result = await db.execute(select(User).where(User.email == email))
    user = result.unique().scalar_one_or_none()

    if user is None or not user.is_active:
        return _login_error(request, "Identifiants invalides.")

    # 3) Verify password — constant-time
    try:
        verified, _ = _password_helper.verify_and_update(password, user.hashed_password)
    except Exception:
        verified = False

    if not verified:
        return _login_error(request, "Identifiants invalides.")

    # 4) Persist minimal user dict in session
    request.session["user"] = {
        "id": str(user.id),
        "email": user.email,
        "username": getattr(user, "username", None),
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
    }
    # Rotate CSRF after auth so the old token can't be replayed
    request.session.pop("csrf_token", None)

    # 5) Redirect — HTMX uses HX-Redirect, browsers use 303
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/logout
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/web/login"})
    return RedirectResponse(url="/web/login", status_code=303)
