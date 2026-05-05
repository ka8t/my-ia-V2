"""Web routes — Documents (Phase 3.4).

GET    /web/documents               — list page
POST   /web/documents/upload        — upload via existing IngestionService
GET    /web/documents/{id}/row      — refresh a single row (for status polling)
DELETE /web/documents/{id}          — soft-delete + storage cleanup

Implementation notes
--------------------
* Per-user "Personnel" Corpus is auto-created on first upload (the existing
  ingestion pipeline requires a corpus_id).
* Indexation status is read from ``app.features.ingestion.router`` progress
  registry when present; otherwise derived from ``chunk_count``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_chroma_client
from app.db import get_async_session
from app.features.documents.repository import DocumentRepository
from app.features.ingestion.service import IngestionService
from app.models import Corpus, Document, User
from app.web.deps import require_web_auth
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/documents", tags=["Web - Documents"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _get_or_create_user_corpus(
    db: AsyncSession, user_id: uuid.UUID
) -> Corpus:
    """Ensure the user has a personal Corpus for their uploads."""
    name = f"user_{user_id}"
    result = await db.execute(select(Corpus).where(Corpus.name == name))
    corp = result.unique().scalar_one_or_none()
    if corp:
        return corp

    corp = Corpus(
        name=name,
        display_name="Personnel",
        description="Corpus personnel — documents uploadés via l'interface web.",
    )
    db.add(corp)
    await db.commit()
    await db.refresh(corp)
    logger.info("Created personal corpus %s for user %s", corp.id, user_id)
    return corp


def _doc_status(doc: Document) -> dict:
    """Derive a status dict for the row template."""
    if doc.chunk_count and doc.chunk_count > 0:
        return {
            "label": "Indexé",
            "kind": "ok",
            "detail": f"{doc.chunk_count} chunk{'s' if doc.chunk_count > 1 else ''}",
        }
    if doc.embedding_count and doc.embedding_count > 0:
        return {"label": "Indexé", "kind": "ok", "detail": f"{doc.embedding_count} embeddings"}
    return {"label": "Indexation…", "kind": "pending", "detail": "en cours"}


def _human_size(n: int | None) -> str:
    if not n:
        return "—"
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


# Inject helpers for templates
def _doc_context(doc: Document) -> dict:
    return {
        "doc": doc,
        "status": _doc_status(doc),
        "size": _human_size(doc.file_size),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/documents — list page
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def documents_index(
    request: Request,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    repo = DocumentRepository(db)
    docs, total = await repo.list_user_documents(
        user_id=uuid.UUID(user["id"]),
        page=1,
        page_size=100,
    )
    rows = [_doc_context(d) for d in docs]
    return templates.TemplateResponse(
        request,
        "pages/documents/list.html",
        web_context(
            request,
            title="Documents",
            user=user,
            rows=rows,
            total=total,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/documents/upload — upload + queue indexation
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/upload", response_class=HTMLResponse)
async def documents_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée. Rechargez la page.</div>",
            status_code=400,
        )
    if not file or not file.filename:
        return HTMLResponse(
            "<div class='toast toast--error'>Aucun fichier sélectionné.</div>",
            status_code=400,
        )

    user_uuid = uuid.UUID(user["id"])
    db_user = (
        (await db.execute(select(User).where(User.id == user_uuid)))
        .unique()
        .scalar_one_or_none()
    )
    if db_user is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Utilisateur introuvable.</div>",
            status_code=403,
        )

    corp = await _get_or_create_user_corpus(db, user_uuid)

    # Lazy resolve dependencies the existing service expects
    from app.core.deps import get_storage_service  # local import to keep startup light
    from app.features.ingestion.router import _run_indexation_in_background, set_doc_reindex_progress  # noqa: PLC0415

    storage = get_storage_service()
    chroma = get_chroma_client()

    try:
        new_doc, content, file_ext, collection_name = (
            await IngestionService.create_document_with_upload(
                db=db,
                user=db_user,
                file=file,
                corpus_id=corp.id,
                storage=storage,
                chroma=chroma,
                replace_if_exists=True,
                visibility="private",
            )
        )
    except Exception as exc:
        logger.exception("Upload failed")
        msg = str(exc) if len(str(exc)) < 200 else "Erreur lors de l'upload."
        return HTMLResponse(
            f"<div class='toast toast--error'>{msg}</div>",
            status_code=500,
        )

    # Kick off background indexation — same pattern as the JSON endpoint
    set_doc_reindex_progress(str(new_doc.id), 0, "queued", document_name=file.filename)
    background_tasks.add_task(
        _run_indexation_in_background,
        document_id=new_doc.id,
        content=content,
        file_ext=file_ext,
        collection_name=collection_name,
    )

    # Render the new row — HTMX will swap it into the list (or refresh)
    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(new_doc), just_uploaded=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/documents/{id}/row — used by HTMX polling for status
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{document_id}/row", response_class=HTMLResponse)
async def documents_row(
    request: Request,
    document_id: uuid.UUID,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    user_uuid = uuid.UUID(user["id"])
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.user_id == user_uuid
        )
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(doc)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  DELETE /web/documents/{id}
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{document_id}", response_class=Response)
async def documents_delete(
    request: Request,
    document_id: uuid.UUID,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    user_uuid = uuid.UUID(user["id"])
    result = await db.execute(
        select(Document).where(
            Document.id == document_id, Document.user_id == user_uuid
        )
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return Response(status_code=404)

    try:
        await db.delete(doc)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Delete document failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>",
            status_code=500,
        )

    # 204 with empty body — HTMX swap removes the row
    return Response(status_code=200, content="")
