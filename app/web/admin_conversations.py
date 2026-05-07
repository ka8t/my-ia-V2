"""Web routes — Admin conversations (Phase 3.4.f — page entière nouvelle)."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.conversations.repository import MessageRepository
from app.models import ApprovalStatus, Conversation, User
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/conversations", tags=["Web - Admin Conversations"])
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


@router.get("", response_class=HTMLResponse)
async def admin_conversations_list(
    request: Request,
    q: str | None = None,
    archived: str | None = None,
    page: int = 1,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Modération conversations cross-user (parité V1 content-conversations.js)."""
    page_size = 25
    query = (
        select(Conversation, User.email)
        .join(User, User.id == Conversation.user_id)
        .options(joinedload(Conversation.collection))
    )
    if q:
        query = query.where(Conversation.title.ilike(f"%{q.strip()}%"))
    if archived == "yes":
        query = query.where(Conversation.archived_at.is_not(None))
    elif archived == "no":
        query = query.where(Conversation.archived_at.is_(None))

    query = query.order_by(Conversation.updated_at.desc())

    # Total
    cq = select(func.count(Conversation.id))
    if q: cq = cq.where(Conversation.title.ilike(f"%{q.strip()}%"))
    if archived == "yes": cq = cq.where(Conversation.archived_at.is_not(None))
    if archived == "no": cq = cq.where(Conversation.archived_at.is_(None))
    total = (await db.execute(cq)).scalar_one()

    page = max(1, page)
    offset = (page - 1) * page_size
    res = await db.execute(query.offset(offset).limit(page_size))
    rows = []
    for conv, email in res.unique().all():
        rows.append({"conv": conv, "email": email})
    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        request,
        "pages/admin/conversations.html",
        await _admin_context(
            db, request, title="Conversations", active_section="conversations",
            user=user, rows=rows, total=total, q=q or "", archived=archived or "",
            page=page, total_pages=total_pages,
        ),
    )


@router.get("/{cid}/view", response_class=HTMLResponse)
async def admin_conversation_view(
    request: Request,
    cid: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Modal/page de visualisation des messages d'une conversation."""
    conv = (
        await db.execute(
            select(Conversation)
            .options(joinedload(Conversation.collection), joinedload(Conversation.user))
            .where(Conversation.id == cid)
        )
    ).unique().scalar_one_or_none()
    if conv is None:
        return HTMLResponse("Conversation introuvable.", status_code=404)
    messages = await MessageRepository.list_by_conversation(db, cid)
    return templates.TemplateResponse(
        request,
        "partials/admin/conversation-view.html",
        web_context(request, conv=conv, messages=messages),
    )


@router.delete("/{cid}", response_class=Response)
async def admin_conversation_delete(
    request: Request,
    cid: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).unique().scalar_one_or_none()
    if conv is None:
        return Response(status_code=404)
    try:
        await db.delete(conv)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Delete conversation failed")
        return HTMLResponse("<div class='toast toast--error'>Suppression impossible.</div>", status_code=500)
    return Response(status_code=200, content="")


@router.get("/{cid}/export", response_class=HTMLResponse)
async def admin_conversation_export(
    request: Request,
    cid: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
):
    """Export Markdown des messages d'une conversation."""
    conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).unique().scalar_one_or_none()
    if conv is None:
        return HTMLResponse("", status_code=404)
    messages = await MessageRepository.list_by_conversation(db, cid)
    lines = [f"# {conv.title}", "", f"_Créée le {conv.created_at.strftime('%d/%m/%Y')}_", ""]
    for m in messages:
        role = "Vous" if m.sender_type == "user" else "MY-IA"
        lines.append(f"## {role}")
        lines.append(m.content or "")
        lines.append("")
    md = "\n".join(lines)
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="conv-{cid}.md"'},
    )


@router.post("/bulk-delete", response_class=HTMLResponse)
async def admin_conversations_bulk_delete(
    request: Request,
    conversation_ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    affected = 0
    for raw in conversation_ids:
        try:
            cid = uuid.UUID(raw)
        except ValueError:
            continue
        conv = (await db.execute(select(Conversation).where(Conversation.id == cid))).unique().scalar_one_or_none()
        if conv is None:
            continue
        await db.delete(conv)
        affected += 1
    if affected:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            return HTMLResponse("<div class='toast toast--error'>Échec.</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{affected} conversation(s) supprimée(s).</div>",
        headers={"HX-Trigger": "convs-refresh"},
    )
