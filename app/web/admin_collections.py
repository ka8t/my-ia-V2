"""Web routes — Admin collections (Phase 3.4.e — page entière nouvelle).

Réutilise l'API existante (app/features/admin/collections/router.py). Couche
web qui rend du HTML pour HTMX.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import ApprovalStatus, Collection, User
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/collections", tags=["Web - Admin Collections"])
templates = make_templates(TEMPLATES_DIR)


async def _admin_context(db: AsyncSession, request: Request, **extra) -> dict:
    pending = (
        await db.execute(select(func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING))
    ).scalar_one() or 0
    return web_context(request, pending_users_count=pending, **extra)


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    return None


async def _get_or_404(db: AsyncSession, cid: uuid.UUID) -> Collection | None:
    res = await db.execute(select(Collection).where(Collection.id == cid))
    return res.unique().scalar_one_or_none()


@router.get("", response_class=HTMLResponse)
async def admin_collections_list(
    request: Request,
    q: str | None = None,
    type_filter: str | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Liste toutes les collections cross-user (parité V1 content-collections)."""
    query = select(Collection)
    if type_filter in {"public", "private"}:
        query = query.where(Collection.type == type_filter)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            (Collection.display_name.ilike(like)) | (Collection.name.ilike(like))
        )
    query = query.order_by(Collection.type, Collection.display_name)
    result = await db.execute(query)
    collections = list(result.unique().scalars().all())

    # Compteurs : owner email pour chaque privée
    user_ids = [c.owner_id for c in collections if c.owner_id]
    owners: dict[uuid.UUID, str] = {}
    if user_ids:
        owners_q = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        for uid, email in owners_q.all():
            owners[uid] = email

    return templates.TemplateResponse(
        request,
        "pages/admin/collections.html",
        await _admin_context(
            db,
            request,
            title="Bibliothèques",
            active_section="collections",
            user=user,
            collections=collections,
            owners=owners,
            q=q or "",
            type_filter=type_filter or "",
            total=len(collections),
        ),
    )


@router.post("", response_class=HTMLResponse)
async def admin_collections_create(
    request: Request,
    display_name: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Crée une collection publique (parité V1 createPublicCollection)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    name = (display_name or "").strip()
    if not name:
        return HTMLResponse("<div class='toast toast--error'>Nom requis.</div>", status_code=400)
    import re
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:80] or "collection"
    base = slug
    i = 2
    while True:
        existing = await db.execute(select(Collection).where(Collection.name == slug))
        if existing.unique().scalar_one_or_none() is None:
            break
        slug = f"{base}-{i}"
        i += 1
    coll = Collection(
        name=slug,
        display_name=name,
        description=(description or "").strip() or None,
        type="public",
    )
    db.add(coll)
    try:
        await db.commit()
        await db.refresh(coll)
    except Exception:
        await db.rollback()
        logger.exception("Create collection failed")
        return HTMLResponse("<div class='toast toast--error'>Échec création.</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Collection « {coll.display_name} » créée.</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )


@router.patch("/{cid}", response_class=HTMLResponse)
async def admin_collections_update(
    request: Request,
    cid: uuid.UUID,
    display_name: Annotated[str, Form()],
    description: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    c = await _get_or_404(db, cid)
    if c is None:
        return HTMLResponse("", status_code=404)
    c.display_name = (display_name or "").strip() or c.display_name
    c.description = (description or "").strip() or None
    await db.commit()
    return HTMLResponse(
        "<div class='toast toast--success'>Mise à jour OK.</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )


@router.delete("/{cid}", response_class=Response)
async def admin_collections_delete(
    request: Request,
    cid: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    c = await _get_or_404(db, cid)
    if c is None:
        return Response(status_code=404)
    try:
        await db.delete(c)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Delete collection failed")
        return HTMLResponse("<div class='toast toast--error'>Suppression impossible.</div>", status_code=500)
    return Response(status_code=200, content="")


@router.post("/{cid}/sync", response_class=HTMLResponse)
async def admin_collections_sync(
    request: Request,
    cid: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Sync compteurs depuis ChromaDB (parité V1 syncCounts)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    c = await _get_or_404(db, cid)
    if c is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.features.admin.collections.service import AdminCollectionService
        svc = AdminCollectionService(db)
        await svc.sync_collection(cid)
    except Exception as exc:
        logger.exception("Sync collection failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Compteurs synchronisés pour « {c.display_name} ».</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )


@router.post("/sync-all", response_class=HTMLResponse)
async def admin_collections_sync_all(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    try:
        from app.features.admin.collections.service import AdminCollectionService
        svc = AdminCollectionService(db)
        result = await svc.sync_all_collections()
        n = getattr(result, "synced_count", None) or len(getattr(result, "synced", []) or [])
    except Exception as exc:
        logger.exception("Sync-all failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Sync terminé ({n}).</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )


@router.post("/{cid}/clear", response_class=HTMLResponse)
async def admin_collections_clear(
    request: Request,
    cid: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Wipe ChromaDB index pour cette collection (parité V1 clearCollection)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    c = await _get_or_404(db, cid)
    if c is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.features.admin.collections.service import AdminCollectionService
        svc = AdminCollectionService(db)
        await svc.clear_collection_index(cid)
    except Exception as exc:
        logger.exception("Clear collection failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Index vidé pour « {c.display_name} ».</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )


@router.get("/{cid}/peek", response_class=HTMLResponse)
async def admin_collections_peek(
    request: Request,
    cid: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Modal preview des chunks (parité V1 peekCollection)."""
    c = await _get_or_404(db, cid)
    if c is None:
        return HTMLResponse("Collection introuvable.", status_code=404)
    chunks = []
    try:
        from app.features.admin.collections.service import AdminCollectionService
        svc = AdminCollectionService(db)
        peek = await svc.peek_collection(cid, limit=10)
        chunks = getattr(peek, "chunks", None) or peek.get("chunks", []) if isinstance(peek, dict) else []
    except Exception as exc:
        logger.warning("Peek failed: %s", exc)
    return templates.TemplateResponse(
        request,
        "partials/admin/collection-peek.html",
        web_context(request, collection=c, chunks=chunks),
    )


@router.post("/bulk-delete", response_class=HTMLResponse)
async def admin_collections_bulk_delete(
    request: Request,
    collection_ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    affected = 0
    for raw in collection_ids:
        try:
            cid = uuid.UUID(raw)
        except ValueError:
            continue
        c = await _get_or_404(db, cid)
        if c is None:
            continue
        await db.delete(c)
        affected += 1
    if affected:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            return HTMLResponse("<div class='toast toast--error'>Échec.</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{affected} collection(s) supprimée(s).</div>",
        headers={"HX-Trigger": "collections-refresh"},
    )
