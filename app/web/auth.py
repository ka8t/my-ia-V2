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

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_users.password import PasswordHelper
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.user.dependencies import get_user_manager
from app.models import ApprovalStatus, User
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web", tags=["Web - Auth"])
templates = make_templates(TEMPLATES_DIR)
_password_helper = PasswordHelper()


# ─────────────────────────────────────────────────────────────────────────────
#  Password-reset token helpers (signed, time-limited, no DB row)
# ─────────────────────────────────────────────────────────────────────────────
PASSWORD_RESET_MAX_AGE = 3600  # 1 hour


def _reset_serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET", "dev-only-replace-in-env")
    return URLSafeTimedSerializer(secret, salt="password-reset")


def _make_reset_token(user_id: str) -> str:
    return _reset_serializer().dumps(user_id)


def _verify_reset_token(token: str) -> tuple[str | None, str | None]:
    """Return (user_id, error_reason). One of them is None."""
    try:
        return _reset_serializer().loads(token, max_age=PASSWORD_RESET_MAX_AGE), None
    except SignatureExpired:
        return None, "Lien expiré (plus d'une heure)."
    except BadSignature:
        return None, "Lien invalide ou altéré."


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/login
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_get(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Render the login page. If already authenticated, redirect to home.

    Si ``debug.endpoints_enabled`` est activé en BDD, charge aussi les rôles
    et les credentials de test pour afficher le panneau debug login (parité
    V1 ``app.js:initDebugLoginPanel()``).
    """
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)

    # Charger l'état debug (parité V1 ConfigService.isDebugEndpointsEnabled).
    from app.features.admin.config.service import _runtime_overrides
    debug_enabled = bool(_runtime_overrides.get("debug_endpoints_enabled", False))

    debug_roles: list[dict] = []
    if debug_enabled:
        try:
            from app.features.auth.service import AuthDBService
            roles = await AuthDBService(session=db).list_roles()
            debug_roles = [
                {"id": r.id, "display_name": getattr(r, "display_name", None) or r.name}
                for r in roles
            ]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"[Debug] Failed to load debug roles: {exc}")

    return templates.TemplateResponse(
        request,
        "pages/auth/login.html",
        web_context(
            request,
            debug_enabled=debug_enabled,
            debug_roles=debug_roles,
            # Parité V1 fallbacks (UI-FRONT/js/app.js:514-516).
            debug_test_email="test@example.com",
            debug_test_username="testuser",
            debug_test_password="Test1234!",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/login
# ─────────────────────────────────────────────────────────────────────────────
def _login_error(request: Request, message: str, status_code: int = 401) -> HTMLResponse:
    """Render the full login page with an error banner — submit natif
    (sans hx-post), donc on rend toute la page pour que le navigateur
    déclenche aussi son password manager. Le partial reste inclus dans
    la page via `{% include 'partials/auth/login-error.html' ignore missing %}`."""
    return templates.TemplateResponse(
        request,
        "pages/auth/login.html",
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

    # 3.5) Approval gate — credentials OK but admin must have approved.
    # Parité V1 : écran dédié (pas de banner d'erreur sur la page login).
    if user.approval_status != ApprovalStatus.APPROVED:
        if user.approval_status == ApprovalStatus.REJECTED:
            return templates.TemplateResponse(
                request,
                "pages/auth/register-rejected.html",
                web_context(request),
                status_code=403,
            )
        return templates.TemplateResponse(
            request,
            "pages/auth/register-pending.html",
            web_context(request, email=user.email),
            status_code=403,
        )

    # 4) Persist minimal user dict in session.
    # Charger les prefs theme/language pour les transversaux (3.7.a).
    pref_theme = "auto"
    pref_lang = "fr"
    try:
        from app.models import UserPreference
        prefs = (
            await db.execute(
                select(UserPreference).where(UserPreference.user_id == user.id)
            )
        ).scalar_one_or_none()
        if prefs:
            pref_theme = prefs.theme or "auto"
            pref_lang = prefs.language or "fr"
    except Exception:
        pass
    request.session["user"] = {
        "id": str(user.id),
        "email": user.email,
        "username": getattr(user, "username", None),
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
        "theme": pref_theme,
        "language": pref_lang,
    }
    # Rotate CSRF after auth so the old token can't be replayed
    request.session.pop("csrf_token", None)

    # 5) Redirect — admins atterrissent directement sur la console.
    target = "/web/admin" if user.is_superuser else "/"
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(url=target, status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/register
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
async def register_get(request: Request) -> HTMLResponse:
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request, "pages/auth/register.html", web_context(request)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/register — open signup with admin approval gate
# ─────────────────────────────────────────────────────────────────────────────
def _register_error(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/auth/register-error.html",
        web_context(request, error=message),
        status_code=status_code,
    )


async def _allocate_username(db: AsyncSession, email: str) -> str:
    """Derive a unique username from the email local-part, suffixing if needed."""
    base = email.split("@", 1)[0].lower()
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80] or "user"
    candidate = base
    suffix = 1
    while True:
        result = await db.execute(select(User).where(User.username == candidate))
        if result.unique().scalar_one_or_none() is None:
            return candidate
        suffix += 1
        candidate = f"{base}_{suffix}"
        if suffix > 999:
            # Pathological collision — extremely unlikely
            import secrets as _s
            return f"{base}_{_s.token_hex(3)}"


@router.post("/register")
async def register_post(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    # 1) CSRF
    if not verify_csrf_token(request, csrf_token):
        return _register_error(
            request,
            "Session expirée. Rechargez la page et réessayez.",
        )

    # 2) Field validation
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return _register_error(request, "Adresse e-mail invalide.")
    if len(password) < 8:
        return _register_error(
            request, "Le mot de passe doit faire au moins 8 caractères."
        )
    if password != password_confirm:
        return _register_error(request, "Les deux mots de passe ne correspondent pas.")

    # 3) Email uniqueness
    existing = await db.execute(select(User).where(User.email == email))
    if existing.unique().scalar_one_or_none() is not None:
        return _register_error(
            request, "Un compte avec cette adresse e-mail existe déjà."
        )

    # 4) Create user (pending approval, role=user, active)
    username = await _allocate_username(db, email)
    user = User(
        email=email,
        hashed_password=_password_helper.hash(password),
        username=username,
        role_id=2,  # user
        is_active=True,
        is_superuser=False,
        is_verified=False,
        approval_status=ApprovalStatus.PENDING,
    )
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        return _register_error(
            request,
            "Impossible de créer le compte. Réessayez ultérieurement.",
            status_code=500,
        )

    # 5) Success — render the pending page (full page swap for HTMX,
    #    redirect for non-HTMX so the URL changes)
    if request.headers.get("HX-Request"):
        return Response(
            status_code=204,
            headers={"HX-Redirect": "/web/register/pending?email=" + email},
        )
    return RedirectResponse(
        url=f"/web/register/pending?email={email}", status_code=303
    )


@router.get("/register/pending", response_class=HTMLResponse)
async def register_pending(request: Request, email: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/auth/register-pending.html",
        web_context(request, email=email),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/verify — Email verification (parité V1 handleEmailVerification)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/verify", response_class=HTMLResponse)
async def verify_email(
    request: Request,
    token: str | None = None,
    user_manager=Depends(get_user_manager),
) -> HTMLResponse:
    """Vérifie le token email reçu par l'utilisateur. Parité V1
    `app.js:handleEmailVerification()` : 3 états (success / already / error).

    Sur succès, la page redirige automatiquement vers /web/login après 2s
    via une meta refresh (V1 utilisait setTimeout JS, parité fonctionnelle).
    """
    from fastapi_users.exceptions import (
        InvalidVerifyToken,
        UserAlreadyVerified,
    )

    state = "error"
    error_message = "Le lien est invalide ou a expiré."

    if token:
        try:
            await user_manager.verify(token)
            state = "success"
            error_message = ""
        except UserAlreadyVerified:
            state = "already"
            error_message = ""
        except InvalidVerifyToken:
            state = "error"
            error_message = "Le lien est invalide ou a expiré."
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Verify email failed: {exc}")
            state = "error"
            error_message = "Une erreur est survenue lors de la vérification."

    return templates.TemplateResponse(
        request,
        "pages/auth/verify.html",
        web_context(request, state=state, error_message=error_message),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/password-reset (request form)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/password-reset", response_class=HTMLResponse)
async def password_reset_get(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "pages/auth/password-reset.html", web_context(request)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/password-reset (request — generates a token, optionally emails)
# ─────────────────────────────────────────────────────────────────────────────
def _reset_request_error(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/auth/reset-error.html",
        web_context(request, error=message),
        status_code=status_code,
    )


@router.post("/password-reset")
async def password_reset_post(
    request: Request,
    email: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    if not verify_csrf_token(request, csrf_token):
        return _reset_request_error(
            request, "Session expirée. Rechargez la page et réessayez."
        )

    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return _reset_request_error(request, "Adresse e-mail invalide.")

    # Lookup but never reveal whether the email exists.
    result = await db.execute(select(User).where(User.email == email))
    user = result.unique().scalar_one_or_none()

    if user and user.is_active and user.approval_status == ApprovalStatus.APPROVED:
        token = _make_reset_token(str(user.id))
        # Build the absolute URL using the incoming request (works with reverse proxy)
        base = str(request.base_url).rstrip("/")
        link = f"{base}/web/password-reset/{token}"
        # TODO: wire up SMTP via app.common.email when V2 email config is finalised.
        # For now, log the link so dev/admin can pick it up.
        logger.info(
            "[PWD-RESET] User %s (%s) — reset link valid 1h: %s",
            user.email, user.id, link,
        )

    # Always show the same "check your email" page for security
    if request.headers.get("HX-Request"):
        return Response(
            status_code=204,
            headers={"HX-Redirect": f"/web/password-reset/sent?email={email}"},
        )
    return RedirectResponse(
        url=f"/web/password-reset/sent?email={email}", status_code=303
    )


@router.get("/password-reset/sent", response_class=HTMLResponse)
async def password_reset_sent(request: Request, email: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/auth/password-reset-sent.html",
        web_context(request, email=email),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/password-reset/{token} (confirm form)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/password-reset/{token}", response_class=HTMLResponse)
async def password_reset_confirm_get(request: Request, token: str) -> HTMLResponse:
    user_id, reason = _verify_reset_token(token)
    if user_id is None:
        return templates.TemplateResponse(
            request,
            "pages/auth/password-reset-invalid.html",
            web_context(request, reason=reason),
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "pages/auth/password-reset-confirm.html",
        web_context(request, token=token),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/password-reset/{token} (apply new password)
# ─────────────────────────────────────────────────────────────────────────────
def _reset_confirm_error(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/auth/reset-confirm-error.html",
        web_context(request, error=message),
        status_code=status_code,
    )


@router.post("/password-reset/{token}")
async def password_reset_confirm_post(
    request: Request,
    token: str,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    if not verify_csrf_token(request, csrf_token):
        return _reset_confirm_error(
            request, "Session expirée. Rechargez la page et réessayez."
        )

    if len(password) < 8:
        return _reset_confirm_error(
            request, "Le mot de passe doit faire au moins 8 caractères."
        )
    if password != password_confirm:
        return _reset_confirm_error(
            request, "Les deux mots de passe ne correspondent pas."
        )

    user_id, reason = _verify_reset_token(token)
    if user_id is None:
        return _reset_confirm_error(
            request, reason or "Lien invalide ou expiré."
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if user is None or not user.is_active:
        return _reset_confirm_error(request, "Utilisateur introuvable.")

    user.hashed_password = _password_helper.hash(password)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        return _reset_confirm_error(
            request, "Échec de la mise à jour. Réessayez.", status_code=500
        )

    # Auto-login after reset (matches user expectation)
    request.session["user"] = {
        "id": str(user.id),
        "email": user.email,
        "username": getattr(user, "username", None),
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
    }
    request.session.pop("csrf_token", None)

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
