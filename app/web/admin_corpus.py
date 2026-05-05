"""Web routes — Admin corpus (Phase 3.7.b — Vague 1).

CRUD basique des corpus thématiques (regroupement documents + sources).
La gestion des relations corpus↔collections, corpus↔sources et les actions
en cascade (reindex, clear) sont prévues en Vague 2.

Routes
------
GET    /web/admin/corpus              — liste avec compteurs
GET    /web/admin/corpus/{id}         — détail (read-only items rattachés)
POST   /web/admin/corpus              — create (form)
GET    /web/admin/corpus/{id}/edit    — partial mode édition
POST   /web/admin/corpus/{id}/cancel  — sortir du mode édition
PATCH  /web/admin/corpus/{id}         — update (form)
DELETE /web/admin/corpus/{id}         — delete (CASCADE rompt les liaisons)
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
from sqlalchemy.orm import selectinload

from app.db import get_async_session
from app.models import (
    ApprovalStatus,
    Collection,
    ContextSource,
    Corpus,
    CorpusDocument,
    CorpusSource,
    Document,
    User,
)
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/corpus", tags=["Web - Admin Corpus"])
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
    """Slug technique court : minuscule, alphanum + _ -, espaces → -."""
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = _SLUG_RE.sub("", value)
    return value[:100] or "corpus"


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    return None


async def _get_corpus_or_404(db: AsyncSession, corpus_id: uuid.UUID) -> Corpus | None:
    result = await db.execute(select(Corpus).where(Corpus.id == corpus_id))
    return result.unique().scalar_one_or_none()


async def _corpus_with_counts(db: AsyncSession) -> list[dict]:
    """Retourne une liste enrichie : corpus + compteurs documents/sources/collections."""
    rows = (await db.execute(select(Corpus).order_by(Corpus.display_name))).scalars().all()

    out: list[dict] = []
    for c in rows:
        doc_count = (
            await db.execute(
                select(func.count(CorpusDocument.id)).where(CorpusDocument.corpus_id == c.id)
            )
        ).scalar_one()
        src_count = (
            await db.execute(
                select(func.count(CorpusSource.id)).where(CorpusSource.corpus_id == c.id)
            )
        ).scalar_one()
        col_count = (
            await db.execute(
                select(func.count(Collection.id)).where(Collection.corpus_id == c.id)
            )
        ).scalar_one()
        out.append(
            {
                "corpus": c,
                "document_count": doc_count,
                "source_count": src_count,
                "collection_count": col_count,
            }
        )
    return out


async def _render_row(
    request: Request, db: AsyncSession, c: Corpus, *, edit: bool = False, error: str | None = None
) -> HTMLResponse:
    template = (
        "partials/admin/corpus-row-edit.html" if edit else "partials/admin/corpus-row.html"
    )
    # Compteurs pour la ligne (utile en mode lecture)
    doc_count = (
        await db.execute(
            select(func.count(CorpusDocument.id)).where(CorpusDocument.corpus_id == c.id)
        )
    ).scalar_one()
    src_count = (
        await db.execute(
            select(func.count(CorpusSource.id)).where(CorpusSource.corpus_id == c.id)
        )
    ).scalar_one()
    col_count = (
        await db.execute(select(func.count(Collection.id)).where(Collection.corpus_id == c.id))
    ).scalar_one()

    return templates.TemplateResponse(
        request,
        template,
        web_context(
            request,
            corpus=c,
            document_count=doc_count,
            source_count=src_count,
            collection_count=col_count,
            error=error,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/corpus — liste
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def admin_corpus_list(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    rows = await _corpus_with_counts(db)
    return templates.TemplateResponse(
        request,
        "pages/admin/corpus.html",
        await _admin_context(
            db,
            request,
            title="Corpus",
            active_section="corpus",
            user=user,
            rows=rows,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/corpus — create
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", response_class=HTMLResponse)
async def admin_corpus_create(
    request: Request,
    display_name: Annotated[str, Form()],
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

    slug = _slugify(name)
    # Unicité du slug : suffixe -2, -3… si collision
    base = slug
    i = 2
    while True:
        existing = await db.execute(select(Corpus).where(Corpus.name == slug))
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base}-{i}"
        i += 1

    try:
        c = Corpus(
            name=slug,
            display_name=name,
            description=(description or "").strip() or None,
            is_active=True,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        logger.info("Admin %s created corpus '%s'", user.get("email"), slug)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur création corpus '%s': %s", slug, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur création du corpus.</div>", status_code=500
        )

    return await _render_row(request, db, c, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/corpus/{id}/edit — partial édition
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{corpus_id}/edit", response_class=HTMLResponse)
async def admin_corpus_edit_form(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    c = await _get_corpus_or_404(db, corpus_id)
    if c is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, db, c, edit=True)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/corpus/{id}/cancel — sortir du mode édition
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{corpus_id}/cancel", response_class=HTMLResponse)
async def admin_corpus_cancel(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    c = await _get_corpus_or_404(db, corpus_id)
    if c is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, db, c, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  PATCH /web/admin/corpus/{id} — update
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{corpus_id}", response_class=HTMLResponse)
async def admin_corpus_update(
    request: Request,
    corpus_id: uuid.UUID,
    display_name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    is_active: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    c = await _get_corpus_or_404(db, corpus_id)
    if c is None:
        return HTMLResponse("", status_code=404)

    name = (display_name or "").strip()
    if not name:
        return await _render_row(request, db, c, edit=True, error="Le nom est requis.")

    try:
        c.display_name = name
        c.description = (description or "").strip() or None
        c.is_active = is_active == "true"
        await db.commit()
        await db.refresh(c)
        logger.info("Admin %s updated corpus '%s'", user.get("email"), c.name)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur update corpus '%s': %s", c.name, e)
        return await _render_row(
            request, db, c, edit=True, error="Erreur lors de la sauvegarde."
        )

    return await _render_row(request, db, c, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  DELETE /web/admin/corpus/{id}
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{corpus_id}", response_class=Response)
async def admin_corpus_delete(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    c = await _get_corpus_or_404(db, corpus_id)
    if c is None:
        return Response(status_code=404)
    try:
        slug = c.name
        await db.delete(c)
        await db.commit()
        logger.info("Admin %s deleted corpus '%s'", user.get("email"), slug)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur suppression corpus %s: %s", corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>", status_code=500
        )
    return Response(status_code=200, content="")


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/corpus/{id} — détail (read-only)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{corpus_id}", response_class=HTMLResponse)
async def admin_corpus_detail(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    # Eager-load des relations utiles
    result = await db.execute(
        select(Corpus)
        .where(Corpus.id == corpus_id)
        .options(
            selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
            selectinload(Corpus.sources).selectinload(CorpusSource.source),
            selectinload(Corpus.assigned_collections),
        )
    )
    c = result.unique().scalar_one_or_none()
    if c is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    documents = [cd.document for cd in c.corpus_documents if cd.document is not None]
    corpus_sources = [(cs, cs.source) for cs in c.sources if cs.source is not None]
    collections = list(c.assigned_collections or [])

    return templates.TemplateResponse(
        request,
        "pages/admin/corpus-detail.html",
        await _admin_context(
            db,
            request,
            title=f"Corpus · {c.display_name}",
            active_section="corpus",
            user=user,
            corpus=c,
            documents=documents,
            corpus_sources=corpus_sources,
            collections=collections,
        ),
    )
