"""Web routes — Admin configuration système (Phase 3.7.a).

Vue/édition générique de la table ``system_configs`` (clé/valeur typée).
Vague 1 du portage admin config : éditeur clé/valeur unique pour toutes les
clés sans validation métier — les sections spécialisées (RAG, LLM, storage…)
viendront en Vague 2 quand le besoin se présente.

Routes
------
GET    /web/admin/config                 — liste filtrable (catégorie + recherche)
GET    /web/admin/config/{key}/edit      — partial mode édition
PATCH  /web/admin/config/{key}           — update value (form), retourne row read
POST   /web/admin/config/{key}/cancel    — annule édition, retourne row read
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import ApprovalStatus, SystemConfig, User
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/config", tags=["Web - Admin Config"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _pending_users_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING)
    )
    return result.scalar_one() or 0


async def _admin_context(db: AsyncSession, request: Request, **extra) -> dict:
    pending = await _pending_users_count(db)
    return web_context(request, pending_users_count=pending, **extra)


async def _get_config_or_404(db: AsyncSession, key: str) -> SystemConfig | None:
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    return result.scalar_one_or_none()


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    return None


def _coerce_value(value_type: str, raw: str) -> tuple[bool, str, str | None]:
    """Valide et normalise ``raw`` selon ``value_type``.

    Returns
    -------
    (ok, normalized_value, error_message)
        - ``ok=True`` → ``normalized_value`` est la string à stocker en BDD.
        - ``ok=False`` → ``error_message`` explique pourquoi le cast a échoué.
    """
    raw = (raw or "").strip()

    if value_type == "bool":
        v = raw.lower()
        if v in {"true", "1", "yes", "on"}:
            return True, "true", None
        if v in {"false", "0", "no", "off", ""}:
            return True, "false", None
        return False, raw, f"Valeur booléenne invalide : « {raw} »"

    if value_type == "int":
        try:
            return True, str(int(raw)), None
        except (ValueError, TypeError):
            return False, raw, f"Entier invalide : « {raw} »"

    if value_type == "float":
        try:
            return True, str(float(raw)), None
        except (ValueError, TypeError):
            return False, raw, f"Nombre invalide : « {raw} »"

    if value_type in {"json", "list"}:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            return False, raw, f"JSON invalide : {e.msg}"
        if value_type == "list" and not isinstance(parsed, list):
            return False, raw, "Une liste JSON est attendue (ex: [\"a\", \"b\"])."
        return True, json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), None

    return True, raw, None


async def _render_row(
    request: Request,
    db: AsyncSession,
    cfg: SystemConfig,
    *,
    edit: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    template = (
        "partials/admin/config-row-edit.html" if edit else "partials/admin/config-row.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        web_context(request, cfg=cfg, error=error),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/config — liste filtrable
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def admin_config_list(
    request: Request,
    category: str | None = None,
    q: str | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    # Catégories distinctes (pour le filtre)
    cat_result = await db.execute(
        select(distinct(SystemConfig.category)).order_by(SystemConfig.category)
    )
    categories = [c for c in cat_result.scalars().all() if c]

    # Construction de la requête
    query = select(SystemConfig)
    if category:
        query = query.where(SystemConfig.category == category)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                SystemConfig.key.ilike(like),
                SystemConfig.value.ilike(like),
                SystemConfig.description.ilike(like),
            )
        )
    query = query.order_by(SystemConfig.category, SystemConfig.key)

    result = await db.execute(query)
    configs = list(result.scalars().all())

    return templates.TemplateResponse(
        request,
        "pages/admin/config.html",
        await _admin_context(
            db,
            request,
            title="Configuration système",
            active_section="config",
            user=user,
            configs=configs,
            categories=categories,
            filter_category=category,
            filter_q=q,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/config/{key}/edit — partial mode édition
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{key:path}/edit", response_class=HTMLResponse)
async def admin_config_edit_form(
    request: Request,
    key: str,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    cfg = await _get_config_or_404(db, key)
    if cfg is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, db, cfg, edit=True)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/config/{key}/cancel — sortir du mode édition
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{key:path}/cancel", response_class=HTMLResponse)
async def admin_config_cancel(
    request: Request,
    key: str,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    cfg = await _get_config_or_404(db, key)
    if cfg is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, db, cfg, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  PATCH /web/admin/config/{key} — update value
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{key:path}", response_class=HTMLResponse)
async def admin_config_update(
    request: Request,
    key: str,
    value: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    cfg = await _get_config_or_404(db, key)
    if cfg is None:
        return HTMLResponse("", status_code=404)

    ok, normalized, error_msg = _coerce_value(cfg.value_type, value)
    if not ok:
        # Reste en mode édition avec l'erreur affichée
        cfg.value = value  # affiche la valeur saisie pour correction
        return await _render_row(request, db, cfg, edit=True, error=error_msg)

    try:
        cfg.value = normalized
        cfg.updated_at = datetime.now(timezone.utc)
        cfg.updated_by = uuid.UUID(user["id"])
        await db.commit()
        await db.refresh(cfg)
        logger.info(
            "Admin %s updated config '%s' (type=%s)", user.get("email"), key, cfg.value_type
        )
    except Exception as e:
        await db.rollback()
        logger.error("Erreur mise à jour config '%s': %s", key, e)
        return await _render_row(
            request, db, cfg, edit=True, error="Erreur lors de la sauvegarde."
        )

    return await _render_row(request, db, cfg, edit=False)
