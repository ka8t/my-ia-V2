"""Web routes — Documents (Phase 3.2b — parité V1).

Routes :

GET    /web/documents                       — list page (filtres, search, tri, pagination, quota)
POST   /web/documents/upload                — upload (collection_id requis)
GET    /web/documents/{id}/row              — refresh d'une ligne (polling status)
GET    /web/documents/{id}/details          — modal détails (chunks, métadonnées)
GET    /web/documents/{id}/download         — télécharger le fichier
POST   /web/documents/{id}/visibility       — toggle public/private
PUT    /web/documents/{id}/replace          — remplacer le fichier
DELETE /web/documents/{id}                  — supprimer (single)
POST   /web/documents/bulk-delete           — supprimer en masse
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.deps import get_chroma_client
from app.db import get_async_session
from app.features.collections.service import CollectionService
from app.features.documents.repository import DocumentRepository
from app.features.documents.service import DocumentService
from app.features.ingestion.service import IngestionService
from app.models import Collection, Corpus, Document, User
from app.web.deps import require_web_auth
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/documents", tags=["Web - Documents"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _get_or_create_user_corpus(db: AsyncSession, user_id: uuid.UUID) -> Corpus:
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
    """Statut visuel du document : indexé / en cours / échec.

    Pour distinguer "indexation en cours" et "indexation échouée" quand le
    BDD est à 0 chunks, on consulte le ReindexManager in-memory. Si l'état
    in-memory est failed/error, on affiche l'erreur et on stoppe le polling.
    Si pas d'état in-memory (ex: container redémarré ou jamais lancé), on
    reste sur "Indexation…" (compromis acceptable tant que la persistance
    BDD du statut n'est pas faite — voir P0.3.b dans le plan).
    """
    if doc.chunk_count and doc.chunk_count > 0:
        return {
            "label": "Indexé",
            "kind": "ok",
            "detail": f"{doc.chunk_count} chunk{'s' if doc.chunk_count > 1 else ''}",
        }
    if doc.embedding_count and doc.embedding_count > 0:
        return {"label": "Indexé", "kind": "ok", "detail": f"{doc.embedding_count} embeddings"}

    # BDD à 0 chunks : interroger le ReindexManager pour distinguer pending vs failed
    try:
        from app.common.utils.reindex import get_doc_reindex_progress
        progress = get_doc_reindex_progress(str(doc.id))
        status = (progress.get("status") or "").lower()
        if status in {"failed", "error"}:
            err = progress.get("error_message") or progress.get("message") or "Indexation échouée"
            # Tronquer pour affichage compact
            if len(err) > 120:
                err = err[:117] + "…"
            return {"label": "Erreur d'indexation", "kind": "error", "detail": err}
    except Exception:  # noqa: BLE001
        # ReindexManager indisponible → fallback pending
        pass

    return {"label": "Indexation…", "kind": "pending", "detail": "en cours"}


def _human_size(n: int | None) -> str:
    if not n:
        return "—"
    n = float(n)
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


def _doc_context(doc: Document) -> dict:
    return {
        "doc": doc,
        "status": _doc_status(doc),
        "size": _human_size(doc.file_size),
    }


async def _load_user_collections(
    db: AsyncSession, user: User
) -> list[Collection]:
    """Collections accessibles par l'user pour l'upload (parité V1
    upload.js:loadUploadCollections : sa privée + les publiques)."""
    chroma = get_chroma_client()
    service = CollectionService(session=db, chroma_client=chroma)
    available = await service.get_available_collections(user)
    out: list[Collection] = []
    if available.my_collection:
        # available.my_collection est un dict-ish; on récupère l'objet ORM
        col_id = available.my_collection.id
        col = (
            (await db.execute(select(Collection).where(Collection.id == col_id)))
            .unique()
            .scalar_one_or_none()
        )
        if col:
            out.append(col)
    for c in available.public_collections:
        col = (
            (await db.execute(select(Collection).where(Collection.id == c.id)))
            .unique()
            .scalar_one_or_none()
        )
        if col:
            out.append(col)
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/documents — list page
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def documents_index(
    request: Request,
    q: Annotated[str | None, "search query"] = None,
    visibility: Annotated[str | None, "private|public"] = None,
    collection_id: Annotated[str | None, "filter by collection uuid"] = None,
    sort: Annotated[str, "name|date|size"] = "date",
    order: Annotated[str, "asc|desc"] = "desc",
    page: Annotated[int, "page number"] = 1,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    user_uuid = uuid.UUID(user["id"])
    db_user = (
        (await db.execute(select(User).where(User.id == user_uuid)))
        .unique()
        .scalar_one_or_none()
    )
    if db_user is None:
        return HTMLResponse("Utilisateur introuvable", status_code=404)

    page_size = 20

    # Liste documents — utilise le repo existant, on filtre/recherche/trie
    # nous-mêmes à la main pour rester sur le même périmètre que V1
    # (search ILIKE, filtres simples, tri date|name|size).
    # On part des documents de l'user privé + publics dans ses collections.
    private_cols_subq = (
        select(Collection.id)
        .where(Collection.owner_id == user_uuid)
        .where(Collection.type == "private")
    )
    base_q = (
        select(Document)
        .options(joinedload(Document.collection))
        .where(
            or_(
                Document.user_id == user_uuid,
                Document.collection_id.in_(private_cols_subq),
            )
        )
    )

    if q:
        base_q = base_q.where(Document.filename.ilike(f"%{q.strip()}%"))
    if visibility in {"private", "public"}:
        base_q = base_q.where(Document.visibility == visibility)
    if collection_id:
        try:
            base_q = base_q.where(Document.collection_id == uuid.UUID(collection_id))
        except ValueError:
            pass

    # Tri
    if sort == "name":
        col = Document.filename
    elif sort == "size":
        col = Document.file_size
    else:
        col = Document.updated_at
    base_q = base_q.order_by(col.asc() if order == "asc" else col.desc())

    # Total avant pagination
    total = (
        await db.execute(select(func.count()).select_from(base_q.subquery()))
    ).scalar_one()

    # Pagination
    page = max(1, page)
    offset = (page - 1) * page_size
    docs = list(
        (await db.execute(base_q.offset(offset).limit(page_size)))
        .unique()
        .scalars()
        .all()
    )
    rows = [_doc_context(d) for d in docs]
    total_pages = max(1, (total + page_size - 1) // page_size)

    # Group by collection (pour rendu groupé optionnel — on construit la map ici)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        key = r["doc"].collection.display_name if r["doc"].collection else "Sans collection"
        grouped.setdefault(key, []).append(r)

    # Quota storage (parité V1 documents.js:loadStorageStats)
    try:
        from app.core.deps import get_storage_service  # local import
        storage = get_storage_service()
        # quota global défini dans system_configs ; fallback 100Mo si absent
        from app.features.admin.config.service import _runtime_overrides
        quota_mb = _runtime_overrides.get("storage.user_quota_mb", 100)
        quota_bytes = int(quota_mb) * 1024 * 1024
        storage_stats = await storage.get_user_stats(user_uuid, quota_bytes)
        quota = {
            "used_bytes": storage_stats.used_bytes,
            "used_human": _human_size(storage_stats.used_bytes),
            "quota_bytes": quota_bytes,
            "quota_human": _human_size(quota_bytes),
            "percent": storage_stats.quota_used_percent,
            "file_count": storage_stats.file_count,
        }
    except Exception:
        logger.exception("Failed to load storage stats — falling back")
        # Fallback : compter via docs
        used = sum(d.file_size or 0 for d in docs)
        quota = {
            "used_bytes": used,
            "used_human": _human_size(used),
            "quota_bytes": None,
            "quota_human": "—",
            "percent": 0.0,
            "file_count": total,
        }

    # Collections pour upload + filtre
    collections = await _load_user_collections(db, db_user)

    return templates.TemplateResponse(
        request,
        "pages/documents/list.html",
        web_context(
            request,
            title="Documents",
            user=user,
            rows=rows,
            grouped=grouped,
            total=total,
            quota=quota,
            collections=collections,
            # États de la toolbar (pour repopuler les inputs)
            q=q or "",
            visibility=visibility or "",
            collection_id=collection_id or "",
            sort=sort,
            order=order,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/documents/upload — upload (avec choix de collection)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/upload", response_class=HTMLResponse)
async def documents_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[str | None, Form()] = None,
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

    # Sécurité collection : vérifier que la collection est accessible par l'user
    target_collection: Collection | None = None
    if collection_id:
        try:
            col_uuid = uuid.UUID(collection_id)
        except ValueError:
            return HTMLResponse(
                "<div class='toast toast--error'>Collection invalide.</div>",
                status_code=400,
            )
        col = (
            (await db.execute(select(Collection).where(Collection.id == col_uuid)))
            .unique()
            .scalar_one_or_none()
        )
        if col is None:
            return HTMLResponse(
                "<div class='toast toast--error'>Collection introuvable.</div>",
                status_code=404,
            )
        # Privée → owner_id == user. Publique → autorisé.
        if col.type == "private" and col.owner_id != user_uuid:
            return HTMLResponse(
                "<div class='toast toast--error'>Collection non autorisée.</div>",
                status_code=403,
            )
        target_collection = col

    corp = await _get_or_create_user_corpus(db, user_uuid)
    visibility = "public" if (target_collection and target_collection.type == "public") else "private"

    from app.core.deps import get_storage_service
    from app.features.ingestion.router import _run_indexation_in_background, set_doc_reindex_progress

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
                visibility=visibility,
                collection_id=target_collection.id if target_collection else None,
            )
        )
    except TypeError:
        # IngestionService ne supporte peut-être pas `collection_id` →
        # retombe sur la signature historique (collection privée auto).
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
                    visibility=visibility,
                )
            )
        except Exception as exc:
            logger.exception("Upload failed (fallback)")
            msg = str(exc) if len(str(exc)) < 200 else "Erreur lors de l'upload."
            return HTMLResponse(
                f"<div class='toast toast--error'>{msg}</div>",
                status_code=500,
            )
    except Exception as exc:
        logger.exception("Upload failed")
        msg = str(exc) if len(str(exc)) < 200 else "Erreur lors de l'upload."
        return HTMLResponse(
            f"<div class='toast toast--error'>{msg}</div>",
            status_code=500,
        )

    set_doc_reindex_progress(str(new_doc.id), 0, "queued", document_name=file.filename)
    background_tasks.add_task(
        _run_indexation_in_background,
        document_id=new_doc.id,
        content=content,
        file_ext=file_ext,
        collection_name=collection_name,
    )

    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(new_doc), just_uploaded=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/documents/{id}/row — refresh row (HTMX polling)
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
        select(Document)
        .options(joinedload(Document.collection))
        .where(Document.id == document_id, Document.user_id == user_uuid)
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
#  GET /web/documents/{id}/details — modal détails
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{document_id}/details", response_class=HTMLResponse)
async def documents_details(
    request: Request,
    document_id: uuid.UUID,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    user_uuid = uuid.UUID(user["id"])
    result = await db.execute(
        select(Document)
        .options(joinedload(Document.collection))
        .where(Document.id == document_id, Document.user_id == user_uuid)
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("Document introuvable.", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/documents/details-modal.html",
        web_context(request, doc=doc, size=_human_size(doc.file_size)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/documents/{id}/download — téléchargement
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{document_id}/download")
async def documents_download(
    document_id: uuid.UUID,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
):
    """Parité V1 documents.js:downloadDocument."""
    from app.core.deps import get_storage_service

    user_uuid = uuid.UUID(user["id"])
    service = DocumentService(
        session=db, storage_service=get_storage_service()
    )
    try:
        content, filename, mime_type = await service.get_download_content(
            user_id=user_uuid, document_id=document_id
        )
    except Exception as exc:
        logger.error(f"Download failed for doc {document_id}: {exc}")
        return Response(status_code=404)
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/documents/{id}/visibility — toggle public/private
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{document_id}/visibility", response_class=HTMLResponse)
async def documents_visibility(
    request: Request,
    document_id: uuid.UUID,
    visibility: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    if visibility not in {"private", "public"}:
        return HTMLResponse(
            "<div class='toast toast--error'>Visibilité invalide.</div>",
            status_code=400,
        )

    user_uuid = uuid.UUID(user["id"])
    result = await db.execute(
        select(Document)
        .options(joinedload(Document.collection))
        .where(Document.id == document_id, Document.user_id == user_uuid)
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Document introuvable.</div>",
            status_code=404,
        )

    doc.visibility = visibility
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Toggle visibility failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec de la mise à jour.</div>",
            status_code=500,
        )

    # Re-render la ligne pour rafraîchir le badge
    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(doc)),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  PUT /web/documents/{id}/replace — remplacer le fichier
# ─────────────────────────────────────────────────────────────────────────────
@router.put("/{document_id}/replace", response_class=HTMLResponse)
async def documents_replace(
    request: Request,
    background_tasks: BackgroundTasks,
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    if not file or not file.filename:
        return HTMLResponse(
            "<div class='toast toast--error'>Aucun fichier.</div>",
            status_code=400,
        )

    user_uuid = uuid.UUID(user["id"])
    db_user = (
        (await db.execute(select(User).where(User.id == user_uuid)))
        .unique()
        .scalar_one_or_none()
    )
    result = await db.execute(
        select(Document)
        .options(joinedload(Document.collection))
        .where(Document.id == document_id, Document.user_id == user_uuid)
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None or db_user is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Document introuvable.</div>",
            status_code=404,
        )

    from app.core.deps import get_storage_service
    from app.features.ingestion.router import _run_indexation_in_background, set_doc_reindex_progress

    storage = get_storage_service()
    chroma = get_chroma_client()
    corp_id = doc.corpus_id

    try:
        # Recréation : delete + create_document_with_upload sur le même corpus.
        await db.delete(doc)
        await db.commit()
        new_doc, content, file_ext, collection_name = (
            await IngestionService.create_document_with_upload(
                db=db,
                user=db_user,
                file=file,
                corpus_id=corp_id,
                storage=storage,
                chroma=chroma,
                replace_if_exists=True,
                visibility=str(doc.visibility) if doc.visibility else "private",
            )
        )
    except Exception as exc:
        logger.exception("Replace failed")
        msg = str(exc) if len(str(exc)) < 200 else "Erreur lors du remplacement."
        return HTMLResponse(
            f"<div class='toast toast--error'>{msg}</div>",
            status_code=500,
        )

    set_doc_reindex_progress(str(new_doc.id), 0, "queued", document_name=file.filename)
    background_tasks.add_task(
        _run_indexation_in_background,
        document_id=new_doc.id,
        content=content,
        file_ext=file_ext,
        collection_name=collection_name,
    )

    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(new_doc), just_uploaded=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  DELETE /web/documents/{id}
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{document_id}/reindex", response_class=HTMLResponse)
async def documents_reindex(
    request: Request,
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Relance l'indexation d'un document (P0.3 — bouton Réessayer).

    Sécurité : seul le propriétaire peut relancer (vérification user_id).
    Récupère le contenu depuis le storage et relance le BackgroundTask.
    """
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    user_uuid = uuid.UUID(user["id"])
    result = await db.execute(
        select(Document)
        .options(joinedload(Document.collection))
        .where(Document.id == document_id, Document.user_id == user_uuid)
    )
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)

    if not doc.file_path:
        return HTMLResponse(
            "<div class='toast toast--error'>Fichier source absent.</div>",
            status_code=400,
        )

    from app.core.deps import get_storage_service
    from app.features.ingestion.router import (
        _run_indexation_in_background,
        set_doc_reindex_progress,
    )

    storage = get_storage_service()
    try:
        content = await storage.download(doc.file_path)
    except Exception:
        logger.exception("Reindex: download failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Fichier source introuvable.</div>",
            status_code=500,
        )

    file_ext = (doc.filename or "").rsplit(".", 1)[-1] if "." in (doc.filename or "") else "txt"
    collection_name = doc.collection.name if doc.collection else None

    # Reset état progress avant nouveau lancement
    set_doc_reindex_progress(str(doc.id), 0, "queued", document_name=doc.filename)
    background_tasks.add_task(
        _run_indexation_in_background,
        document_id=doc.id,
        content=content,
        file_ext=file_ext,
        collection_name=collection_name,
    )

    return templates.TemplateResponse(
        request,
        "partials/documents/row.html",
        web_context(request, **_doc_context(doc)),
    )


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
    return Response(status_code=200, content="")


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/documents/bulk-delete
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/bulk-delete", response_class=HTMLResponse)
async def documents_bulk_delete(
    request: Request,
    ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    user_uuid = uuid.UUID(user["id"])
    deleted = 0
    for raw_id in ids:
        try:
            doc_uuid = uuid.UUID(raw_id)
        except ValueError:
            continue
        doc = (
            (
                await db.execute(
                    select(Document).where(
                        Document.id == doc_uuid, Document.user_id == user_uuid
                    )
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if doc is not None:
            await db.delete(doc)
            deleted += 1
    if deleted > 0:
        await db.commit()

    # Reload page (HX-Redirect) pour reset la sélection + recharger la liste.
    return HTMLResponse(
        f"<div class='toast toast--success'>{deleted} document{'s' if deleted > 1 else ''} supprimé{'s' if deleted > 1 else ''}.</div>",
        status_code=200,
        headers={"HX-Trigger": "docs-refresh"},
    )
