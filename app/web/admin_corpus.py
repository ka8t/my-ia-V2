"""Web routes — Admin corpus (Phase 3.7.b — Vagues 1 & 2.1-2.3).

CRUD corpus + gestion des relations corpus↔documents/sources/collections.
Les actions en cascade (reindex, clear, health-check) sont prévues en
Vagues 2.4/2.5.

Routes corpus
-------------
GET    /web/admin/corpus              — liste avec compteurs
GET    /web/admin/corpus/{id}         — détail interactif
POST   /web/admin/corpus              — create (form)
GET    /web/admin/corpus/{id}/edit    — partial mode édition
POST   /web/admin/corpus/{id}/cancel  — sortir du mode édition
PATCH  /web/admin/corpus/{id}         — update (form)
DELETE /web/admin/corpus/{id}         — delete (CASCADE rompt les liaisons)

Routes relations (Vagues 2.1+2.2+2.3)
-------------------------------------
GET    /web/admin/corpus/{id}/documents/picker      — modal liste available
POST   /web/admin/corpus/{id}/documents             — attach document
DELETE /web/admin/corpus/{id}/documents/{doc_id}    — detach document

GET    /web/admin/corpus/{id}/sources/picker        — modal liste available
POST   /web/admin/corpus/{id}/sources               — attach source
PATCH  /web/admin/corpus/{id}/sources/{src_id}      — update priority/is_enabled
DELETE /web/admin/corpus/{id}/sources/{src_id}      — detach source

GET    /web/admin/corpus/{id}/collections/picker    — modal liste available
POST   /web/admin/corpus/{id}/collections           — attach collection (publique)
PATCH  /web/admin/corpus/{id}/collections/{col_id}  — update priority
DELETE /web/admin/corpus/{id}/collections/{col_id}  — detach collection
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
    CorpusCollection,
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
#  GET /web/admin/corpus/{id} — détail interactif
# ─────────────────────────────────────────────────────────────────────────────
async def _load_corpus_detail(db: AsyncSession, corpus_id: uuid.UUID) -> Corpus | None:
    """Charge un Corpus avec ses 3 relations eager-loaded."""
    result = await db.execute(
        select(Corpus)
        .where(Corpus.id == corpus_id)
        .options(
            selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
            selectinload(Corpus.sources).selectinload(CorpusSource.source),
            selectinload(Corpus.collections).selectinload(CorpusCollection.collection),
        )
    )
    return result.unique().scalar_one_or_none()


@router.get("/{corpus_id}", response_class=HTMLResponse)
async def admin_corpus_detail(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    c = await _load_corpus_detail(db, corpus_id)
    if c is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    documents = [cd.document for cd in c.corpus_documents if cd.document is not None]
    corpus_sources = [cs for cs in c.sources if cs.source is not None]
    corpus_collections = [cc for cc in c.collections if cc.collection is not None]

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
            corpus_collections=corpus_collections,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers — render rows / partials de relation
# ─────────────────────────────────────────────────────────────────────────────
async def _render_document_row(request: Request, corpus_id: uuid.UUID, doc: Document) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-document-row.html",
        web_context(request, corpus_id=corpus_id, doc=doc),
    )


async def _render_source_row(request: Request, corpus_id: uuid.UUID, cs: CorpusSource) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-source-row.html",
        web_context(request, corpus_id=corpus_id, cs=cs),
    )


async def _render_collection_row(
    request: Request, corpus_id: uuid.UUID, cc: CorpusCollection
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-collection-row.html",
        web_context(request, corpus_id=corpus_id, cc=cc),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.1 — Documents : picker, attach, detach
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/{corpus_id}/documents/picker", response_class=HTMLResponse)
async def admin_corpus_documents_picker(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    # Documents non encore rattachés à ce corpus
    attached_ids = (
        await db.execute(
            select(CorpusDocument.document_id).where(CorpusDocument.corpus_id == corpus_id)
        )
    ).scalars().all()

    query = (
        select(Document, User.email)
        .join(User, User.id == Document.user_id)
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    if attached_ids:
        query = query.where(Document.id.notin_(attached_ids))

    rows = (await db.execute(query)).unique().all()
    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-document-picker.html",
        web_context(request, corpus_id=corpus_id, rows=rows),
    )


@router.post("/{corpus_id}/documents", response_class=HTMLResponse)
async def admin_corpus_attach_document(
    request: Request,
    corpus_id: uuid.UUID,
    document_id: Annotated[uuid.UUID, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    doc = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if doc is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Document introuvable.</div>", status_code=404
        )

    existing = await db.execute(
        select(CorpusDocument).where(
            CorpusDocument.corpus_id == corpus_id,
            CorpusDocument.document_id == document_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            "<div class='toast toast--error'>Document déjà rattaché à ce corpus.</div>",
            status_code=409,
        )

    try:
        db.add(CorpusDocument(corpus_id=corpus_id, document_id=document_id, priority=0))
        await db.commit()
        logger.info("Admin %s attached doc %s to corpus %s", user.get("email"), document_id, corpus_id)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur attach document %s au corpus %s: %s", document_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du rattachement.</div>", status_code=500
        )

    return await _render_document_row(request, corpus_id, doc)


@router.delete("/{corpus_id}/documents/{document_id}", response_class=Response)
async def admin_corpus_detach_document(
    request: Request,
    corpus_id: uuid.UUID,
    document_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    cd = (
        await db.execute(
            select(CorpusDocument).where(
                CorpusDocument.corpus_id == corpus_id,
                CorpusDocument.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if cd is None:
        return Response(status_code=404)
    try:
        await db.delete(cd)
        await db.commit()
        logger.info("Admin %s detached doc %s from corpus %s", user.get("email"), document_id, corpus_id)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur detach document %s du corpus %s: %s", document_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du retrait.</div>", status_code=500
        )
    return Response(status_code=200, content="")


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.2 — Sources : picker, attach, update (priority/is_enabled), detach
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/{corpus_id}/sources/picker", response_class=HTMLResponse)
async def admin_corpus_sources_picker(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    attached_ids = (
        await db.execute(
            select(CorpusSource.source_id).where(CorpusSource.corpus_id == corpus_id)
        )
    ).scalars().all()

    query = select(ContextSource).order_by(ContextSource.display_name)
    if attached_ids:
        query = query.where(ContextSource.id.notin_(attached_ids))
    sources = (await db.execute(query)).scalars().all()

    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-source-picker.html",
        web_context(request, corpus_id=corpus_id, sources=sources),
    )


def _clamp_priority(value: int) -> int:
    return max(1, min(int(value), 1000))


@router.post("/{corpus_id}/sources", response_class=HTMLResponse)
async def admin_corpus_attach_source(
    request: Request,
    corpus_id: uuid.UUID,
    source_id: Annotated[uuid.UUID, Form()],
    priority: Annotated[int, Form()] = 100,
    is_enabled: Annotated[str | None, Form()] = "true",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    src = (
        await db.execute(select(ContextSource).where(ContextSource.id == source_id))
    ).scalar_one_or_none()
    if src is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Source introuvable.</div>", status_code=404
        )

    existing = await db.execute(
        select(CorpusSource).where(
            CorpusSource.corpus_id == corpus_id,
            CorpusSource.source_id == source_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            "<div class='toast toast--error'>Source déjà rattachée à ce corpus.</div>",
            status_code=409,
        )

    try:
        cs = CorpusSource(
            corpus_id=corpus_id,
            source_id=source_id,
            priority=_clamp_priority(priority),
            is_enabled=is_enabled == "true",
        )
        db.add(cs)
        await db.commit()
        # Re-charger avec source pour le row
        cs = (
            await db.execute(
                select(CorpusSource)
                .options(selectinload(CorpusSource.source))
                .where(CorpusSource.id == cs.id)
            )
        ).scalar_one()
        logger.info("Admin %s attached source %s to corpus %s", user.get("email"), source_id, corpus_id)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur attach source %s au corpus %s: %s", source_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du rattachement.</div>", status_code=500
        )

    return await _render_source_row(request, corpus_id, cs)


@router.patch("/{corpus_id}/sources/{source_id}", response_class=HTMLResponse)
async def admin_corpus_update_source(
    request: Request,
    corpus_id: uuid.UUID,
    source_id: uuid.UUID,
    priority: Annotated[int, Form()] = 100,
    is_enabled: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    cs = (
        await db.execute(
            select(CorpusSource)
            .options(selectinload(CorpusSource.source))
            .where(
                CorpusSource.corpus_id == corpus_id,
                CorpusSource.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if cs is None:
        return HTMLResponse("", status_code=404)

    try:
        cs.priority = _clamp_priority(priority)
        cs.is_enabled = is_enabled == "true"
        await db.commit()
        await db.refresh(cs)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur update CorpusSource %s/%s: %s", corpus_id, source_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors de la sauvegarde.</div>", status_code=500
        )

    return await _render_source_row(request, corpus_id, cs)


@router.delete("/{corpus_id}/sources/{source_id}", response_class=Response)
async def admin_corpus_detach_source(
    request: Request,
    corpus_id: uuid.UUID,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    cs = (
        await db.execute(
            select(CorpusSource).where(
                CorpusSource.corpus_id == corpus_id,
                CorpusSource.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if cs is None:
        return Response(status_code=404)
    try:
        await db.delete(cs)
        await db.commit()
        logger.info("Admin %s detached source %s from corpus %s", user.get("email"), source_id, corpus_id)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur detach source %s du corpus %s: %s", source_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du retrait.</div>", status_code=500
        )
    return Response(status_code=200, content="")


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.3 — Collections : picker, attach (publiques), update, detach
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/{corpus_id}/collections/picker", response_class=HTMLResponse)
async def admin_corpus_collections_picker(
    request: Request,
    corpus_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    attached_ids = (
        await db.execute(
            select(CorpusCollection.collection_id).where(
                CorpusCollection.corpus_id == corpus_id
            )
        )
    ).scalars().all()

    query = (
        select(Collection)
        .where(Collection.type == "public")
        .order_by(Collection.display_name)
    )
    if attached_ids:
        query = query.where(Collection.id.notin_(attached_ids))
    collections = (await db.execute(query)).scalars().all()

    return templates.TemplateResponse(
        request,
        "partials/admin/corpus-collection-picker.html",
        web_context(request, corpus_id=corpus_id, collections=collections),
    )


@router.post("/{corpus_id}/collections", response_class=HTMLResponse)
async def admin_corpus_attach_collection(
    request: Request,
    corpus_id: uuid.UUID,
    collection_id: Annotated[uuid.UUID, Form()],
    priority: Annotated[int, Form()] = 100,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if (await _get_corpus_or_404(db, corpus_id)) is None:
        return HTMLResponse("Corpus introuvable.", status_code=404)

    coll = (
        await db.execute(select(Collection).where(Collection.id == collection_id))
    ).scalar_one_or_none()
    if coll is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Bibliothèque introuvable.</div>", status_code=404
        )
    if coll.type != "public":
        return HTMLResponse(
            "<div class='toast toast--error'>Seules les bibliothèques publiques peuvent rejoindre un corpus.</div>",
            status_code=400,
        )

    existing = await db.execute(
        select(CorpusCollection).where(
            CorpusCollection.corpus_id == corpus_id,
            CorpusCollection.collection_id == collection_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return HTMLResponse(
            "<div class='toast toast--error'>Bibliothèque déjà rattachée à ce corpus.</div>",
            status_code=409,
        )

    try:
        cc = CorpusCollection(
            corpus_id=corpus_id,
            collection_id=collection_id,
            priority=_clamp_priority(priority),
        )
        db.add(cc)
        await db.commit()
        cc = (
            await db.execute(
                select(CorpusCollection)
                .options(selectinload(CorpusCollection.collection))
                .where(CorpusCollection.id == cc.id)
            )
        ).scalar_one()
        logger.info("Admin %s attached collection %s to corpus %s", user.get("email"), collection_id, corpus_id)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur attach collection %s au corpus %s: %s", collection_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du rattachement.</div>", status_code=500
        )

    return await _render_collection_row(request, corpus_id, cc)


@router.patch("/{corpus_id}/collections/{collection_id}", response_class=HTMLResponse)
async def admin_corpus_update_collection(
    request: Request,
    corpus_id: uuid.UUID,
    collection_id: uuid.UUID,
    priority: Annotated[int, Form()] = 100,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    cc = (
        await db.execute(
            select(CorpusCollection)
            .options(selectinload(CorpusCollection.collection))
            .where(
                CorpusCollection.corpus_id == corpus_id,
                CorpusCollection.collection_id == collection_id,
            )
        )
    ).scalar_one_or_none()
    if cc is None:
        return HTMLResponse("", status_code=404)

    try:
        cc.priority = _clamp_priority(priority)
        await db.commit()
        await db.refresh(cc)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur update CorpusCollection %s/%s: %s", corpus_id, collection_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors de la sauvegarde.</div>", status_code=500
        )

    return await _render_collection_row(request, corpus_id, cc)


@router.delete("/{corpus_id}/collections/{collection_id}", response_class=Response)
async def admin_corpus_detach_collection(
    request: Request,
    corpus_id: uuid.UUID,
    collection_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    cc = (
        await db.execute(
            select(CorpusCollection).where(
                CorpusCollection.corpus_id == corpus_id,
                CorpusCollection.collection_id == collection_id,
            )
        )
    ).scalar_one_or_none()
    if cc is None:
        return Response(status_code=404)
    try:
        await db.delete(cc)
        await db.commit()
        logger.info(
            "Admin %s detached collection %s from corpus %s",
            user.get("email"), collection_id, corpus_id,
        )
    except Exception as e:
        await db.rollback()
        logger.error("Erreur detach collection %s du corpus %s: %s", collection_id, corpus_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du retrait.</div>", status_code=500
        )
    return Response(status_code=200, content="")
