"""Web routes — Preferences (Phase 3.5).

GET  /web/preferences           — settings page (profile, password, prefs)
POST /web/preferences/profile   — save first_name / last_name
POST /web/preferences/password  — change password (current + new)
POST /web/preferences/settings  — language / theme / RAG mode / show_sources

Each form posts independently and renders an inline toast on success / failure
via HTMX (target = its sibling .pref-status div).
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.admin.password_policy.repository import PasswordPolicyRepository
from app.models import ConversationMode, PasswordPolicy, User, UserPreference
from app.web.deps import require_web_auth
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/preferences", tags=["Web - Preferences"])
templates = make_templates(TEMPLATES_DIR)
_password_helper = PasswordHelper()


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _load_user_and_prefs(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[User | None, UserPreference | None]:
    user = (
        (await db.execute(select(User).where(User.id == user_id)))
        .unique()
        .scalar_one_or_none()
    )
    prefs = (
        (await db.execute(select(UserPreference).where(UserPreference.user_id == user_id)))
        .scalar_one_or_none()
    )
    if user is not None and prefs is None:
        prefs = UserPreference(user_id=user_id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return user, prefs


def _toast(level: str, message: str, status_code: int = 200) -> HTMLResponse:
    cls = "toast--error" if level == "error" else ("toast--success" if level == "success" else "")
    title = "Erreur" if level == "error" else ("Enregistré" if level == "success" else "Info")
    return HTMLResponse(
        f"""<div class="toast {cls}" role="alert">
  <div class="toast__body">
    <div class="toast__title">{title}</div>
    <div>{message}</div>
  </div>
</div>""",
        status_code=status_code,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/preferences
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def preferences_index(
    request: Request,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    db_user, prefs = await _load_user_and_prefs(db, uuid.UUID(user["id"]))

    # Charger les modes de conversation (chatbot/assistant) pour le select
    # "Mode par défaut" — parité V1 #defaultMode.
    modes_result = await db.execute(
        select(ConversationMode).order_by(ConversationMode.id)
    )
    modes = list(modes_result.scalars().all())

    # Charger la politique de mot de passe par défaut pour afficher
    # les vraies règles dans le card "Mot de passe" (parité V1
    # password_requirements).
    policy = await PasswordPolicyRepository.get_default(db)

    return templates.TemplateResponse(
        request,
        "pages/preferences/index.html",
        web_context(
            request,
            title="Préférences",
            user=user,
            db_user=db_user,
            prefs=prefs,
            modes=modes,
            policy=policy,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/preferences/profile  — first_name + last_name
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    first_name: Annotated[str | None, Form()] = None,
    last_name: Annotated[str | None, Form()] = None,
    username: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return _toast("error", "Session expirée. Rechargez la page.", status_code=400)

    db_user = (
        (await db.execute(select(User).where(User.id == uuid.UUID(user["id"]))))
        .unique()
        .scalar_one_or_none()
    )
    if db_user is None:
        return _toast("error", "Utilisateur introuvable.", status_code=404)

    # Username editable (parité V1 profile.js:UserForm.render).
    new_username = (username or "").strip()
    if new_username and new_username != db_user.username:
        existing = (
            (await db.execute(select(User).where(User.username == new_username, User.id != db_user.id)))
            .unique()
            .scalar_one_or_none()
        )
        if existing is not None:
            return _toast("error", "Ce nom d'utilisateur est déjà pris.", status_code=400)
        db_user.username = new_username

    db_user.first_name = (first_name or "").strip() or None
    db_user.last_name = (last_name or "").strip() or None
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("update_profile failed")
        return _toast("error", "Impossible d'enregistrer les modifications.", status_code=500)

    return _toast("success", "Profil mis à jour.")


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/preferences/password  — change password
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/password", response_class=HTMLResponse)
async def update_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    new_password_confirm: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return _toast("error", "Session expirée.", status_code=400)

    if len(new_password) < 8:
        return _toast("error", "Le nouveau mot de passe doit faire au moins 8 caractères.", status_code=400)
    if new_password != new_password_confirm:
        return _toast("error", "Les deux nouveaux mots de passe ne correspondent pas.", status_code=400)

    db_user = (
        (await db.execute(select(User).where(User.id == uuid.UUID(user["id"]))))
        .unique()
        .scalar_one_or_none()
    )
    if db_user is None:
        return _toast("error", "Utilisateur introuvable.", status_code=404)

    try:
        verified, _ = _password_helper.verify_and_update(current_password, db_user.hashed_password)
    except Exception:
        verified = False
    if not verified:
        return _toast("error", "Mot de passe actuel incorrect.", status_code=403)

    db_user.hashed_password = _password_helper.hash(new_password)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("update_password failed")
        return _toast("error", "Échec de la mise à jour.", status_code=500)

    return _toast("success", "Mot de passe modifié avec succès.")


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/preferences/settings  — language / theme / RAG mode / show_sources
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_LANGS = {"fr", "en"}
ALLOWED_THEMES = {"light", "dark", "auto"}
ALLOWED_RAG = {"auto", "fast", "full"}


@router.post("/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    language: Annotated[str, Form()] = "fr",
    theme: Annotated[str, Form()] = "auto",
    rag_mode: Annotated[str, Form()] = "auto",
    show_sources: Annotated[str | None, Form()] = None,
    default_mode_id: Annotated[int | None, Form()] = None,
    voice_to_text_enabled: Annotated[str | None, Form()] = None,
    voice_auto_send: Annotated[str | None, Form()] = None,
    voice_tts_enabled: Annotated[str | None, Form()] = None,
    voice_tts_auto_play: Annotated[str | None, Form()] = None,
    voice_tts_rate: Annotated[float | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return _toast("error", "Session expirée.", status_code=400)

    if language not in ALLOWED_LANGS:
        return _toast("error", "Langue invalide.", status_code=400)
    if theme not in ALLOWED_THEMES:
        return _toast("error", "Thème invalide.", status_code=400)
    if rag_mode not in ALLOWED_RAG:
        return _toast("error", "Mode RAG invalide.", status_code=400)

    user_uuid = uuid.UUID(user["id"])
    _, prefs = await _load_user_and_prefs(db, user_uuid)
    if prefs is None:
        return _toast("error", "Préférences introuvables.", status_code=404)

    prefs.language = language
    prefs.theme = theme
    prefs.rag_mode = rag_mode
    prefs.show_sources = bool(show_sources)

    # Mode par défaut conversation (parité V1 #defaultMode).
    if default_mode_id is not None:
        # Vérifier que le mode existe avant de l'assigner.
        mode = (
            await db.execute(select(ConversationMode).where(ConversationMode.id == default_mode_id))
        ).scalar_one_or_none()
        if mode is None:
            return _toast("error", "Mode par défaut invalide.", status_code=400)
        prefs.default_mode_id = default_mode_id

    # Préférences vocales (parité V1 #voiceToTextGroup, #voiceTtsGroup).
    prefs.voice_to_text_enabled = bool(voice_to_text_enabled)
    prefs.voice_auto_send = bool(voice_auto_send)
    prefs.voice_tts_enabled = bool(voice_tts_enabled)
    prefs.voice_tts_auto_play = bool(voice_tts_auto_play)
    if voice_tts_rate is not None:
        prefs.voice_tts_rate = max(0.5, min(2.0, voice_tts_rate))

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("update_settings failed")
        return _toast("error", "Échec de l'enregistrement.", status_code=500)

    # Sync session pour que web_context lise theme/lang à jour
    # (parité 3.7.a thème dynamique).
    sess_user = request.session.get("user")
    if sess_user:
        sess_user["theme"] = prefs.theme
        sess_user["language"] = prefs.language
        request.session["user"] = sess_user

    return _toast("success", "Préférences enregistrées.")
