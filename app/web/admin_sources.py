"""Web routes — Admin sources de contexte (Phase 3.7.b — Vague 1).

CRUD basique des sources de contexte (URL/API/database) — la config technique
JSON par type (selectors web, paramètres API…) est laissée à l'admin V1 le
temps de l'UX dédiée. Vague 2 portera : reindex/clear, health-check, bulk
actions, indexation logs, scheduler status.

Routes
------
GET    /web/admin/sources             — liste filtrable (type, enabled)
POST   /web/admin/sources             — create (champs simples : nom, type, description)
GET    /web/admin/sources/{id}/edit   — partial mode édition
POST   /web/admin/sources/{id}/cancel — sortir du mode édition
PATCH  /web/admin/sources/{id}        — update champs simples
POST   /web/admin/sources/{id}/toggle — toggle is_enabled
DELETE /web/admin/sources/{id}        — delete
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import ApprovalStatus, ContextSource, SourceType, User
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/sources", tags=["Web - Admin Sources"])
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


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = _SLUG_RE.sub("", value)
    return value[:100] or "source"


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    return None


async def _get_source_or_404(db: AsyncSession, source_id: uuid.UUID) -> ContextSource | None:
    result = await db.execute(select(ContextSource).where(ContextSource.id == source_id))
    return result.scalar_one_or_none()


async def _render_row(
    request: Request,
    s: ContextSource,
    *,
    edit: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    template = (
        "partials/admin/source-row-edit.html" if edit else "partials/admin/source-row.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        web_context(request, source=s, error=error, source_types=[t.value for t in SourceType]),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/sources — liste filtrée
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def admin_sources_list(
    request: Request,
    source_type: str | None = None,
    enabled: str | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    query = select(ContextSource).order_by(ContextSource.priority, ContextSource.display_name)

    valid_types = {t.value for t in SourceType}
    if source_type in valid_types:
        query = query.where(ContextSource.source_type == source_type)
    if enabled in {"yes", "no"}:
        query = query.where(ContextSource.is_enabled == (enabled == "yes"))

    result = await db.execute(query)
    sources = list(result.scalars().all())

    return templates.TemplateResponse(
        request,
        "pages/admin/sources.html",
        await _admin_context(
            db,
            request,
            title="Sources de contexte",
            active_section="sources",
            user=user,
            sources=sources,
            source_types=sorted(valid_types),
            filter_type=source_type,
            filter_enabled=enabled,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources — create (champs simples seulement)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", response_class=HTMLResponse)
async def admin_sources_create(
    request: Request,
    display_name: Annotated[str, Form()],
    source_type: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    name = (display_name or "").strip()
    if not name:
        return HTMLResponse(
            "<div class='toast toast--error'>Le nom est requis.</div>", status_code=400
        )
    if source_type not in {t.value for t in SourceType}:
        return HTMLResponse(
            "<div class='toast toast--error'>Type de source invalide.</div>", status_code=400
        )

    slug = _slugify(name)
    base = slug
    i = 2
    while True:
        existing = await db.execute(select(ContextSource).where(ContextSource.name == slug))
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base}-{i}"
        i += 1

    try:
        s = ContextSource(
            name=slug,
            display_name=name,
            description=(description or "").strip() or None,
            source_type=source_type,
            config={},  # config JSON renseignée plus tard via admin V1 (Vague 2 V2)
            is_enabled=False,  # désactivée par défaut tant que la config n'est pas posée
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        logger.info("Admin %s created source '%s' (type=%s)", user.get("email"), slug, source_type)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur création source '%s': %s", slug, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur création de la source.</div>",
            status_code=500,
        )

    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/sources/{id}/edit — partial édition
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{source_id}/edit", response_class=HTMLResponse)
async def admin_sources_edit_form(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, s, edit=True)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources/{id}/cancel
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{source_id}/cancel", response_class=HTMLResponse)
async def admin_sources_cancel(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources/{id}/toggle — toggle is_enabled
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{source_id}/toggle", response_class=HTMLResponse)
async def admin_sources_toggle(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)

    try:
        s.is_enabled = not s.is_enabled
        await db.commit()
        await db.refresh(s)
        logger.info(
            "Admin %s toggled source '%s' → enabled=%s",
            user.get("email"), s.name, s.is_enabled,
        )
    except Exception as e:
        await db.rollback()
        logger.error("Erreur toggle source '%s': %s", s.name, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du toggle.</div>", status_code=500
        )
    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  PATCH /web/admin/sources/{id} — update champs simples
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{source_id}", response_class=HTMLResponse)
async def admin_sources_update(
    request: Request,
    source_id: uuid.UUID,
    display_name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    priority: Annotated[int, Form()] = 100,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)

    name = (display_name or "").strip()
    if not name:
        return await _render_row(request, s, edit=True, error="Le nom est requis.")

    try:
        s.display_name = name
        s.description = (description or "").strip() or None
        s.priority = max(0, min(int(priority), 9999))
        await db.commit()
        await db.refresh(s)
        logger.info("Admin %s updated source '%s'", user.get("email"), s.name)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur update source '%s': %s", s.name, e)
        return await _render_row(
            request, s, edit=True, error="Erreur lors de la sauvegarde."
        )

    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  DELETE /web/admin/sources/{id}
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{source_id}", response_class=Response)
async def admin_sources_delete(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return Response(status_code=404)
    try:
        slug = s.name
        await db.delete(s)
        await db.commit()
        logger.info("Admin %s deleted source '%s'", user.get("email"), slug)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur suppression source %s: %s", source_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>", status_code=500
        )
    return Response(status_code=200, content="")
