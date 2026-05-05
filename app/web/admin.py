"""Web routes — Admin (Phase 3.6).

Routes
------
GET  /web/admin                   — dashboard with key counts
GET  /web/admin/users             — users list + filters + actions
POST /web/admin/users/{id}/approve
POST /web/admin/users/{id}/reject
POST /web/admin/users/{id}/role      (form: role_id)
POST /web/admin/users/{id}/active    (toggle is_active)
DELETE /web/admin/users/{id}

GET  /web/admin/documents         — cross-user document list
DELETE /web/admin/documents/{id}

Each non-GET endpoint returns the rendered HTML row (or an empty body for
delete) so HTMX swaps the table inline.
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
from app.models import (
    ApprovalStatus,
    Conversation,
    Document,
    Role,
    User,
)
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin", tags=["Web - Admin"])
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
    """Standard context for admin pages — adds pending users count for the badge."""
    pending = await _pending_users_count(db)
    return web_context(request, pending_users_count=pending, **extra)


def _human_size(n: int | None) -> str:
    if not n:
        return "—"
    f = float(n)
    for unit in ("o", "Ko", "Mo", "Go"):
        if f < 1024:
            return f"{f:.0f} {unit}" if unit == "o" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} To"


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin — dashboard
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    # Compteurs
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    pending_users = (await db.execute(
        select(func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING)
    )).scalar_one()
    total_conversations = (await db.execute(select(func.count(Conversation.id)))).scalar_one()
    total_documents = (await db.execute(select(func.count(Document.id)))).scalar_one()

    stats = {
        "users": total_users,
        "users_pending": pending_users,
        "conversations": total_conversations,
        "documents": total_documents,
    }

    return templates.TemplateResponse(
        request,
        "pages/admin/dashboard.html",
        await _admin_context(db, request, title="Admin", active_section="dashboard", user=user, stats=stats),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/users — list
# ─────────────────────────────────────────────────────────────────────────────
async def _load_roles(db: AsyncSession) -> list[Role]:
    result = await db.execute(select(Role).order_by(Role.id))
    return list(result.scalars().all())


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    status: str | None = None,
    role: int | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    query = select(User).order_by(User.created_at.desc())
    if status in {"pending", "approved", "rejected"}:
        query = query.where(User.approval_status == status)
    if role is not None:
        query = query.where(User.role_id == role)

    result = await db.execute(query)
    users = list(result.unique().scalars().all())
    roles = await _load_roles(db)

    return templates.TemplateResponse(
        request,
        "pages/admin/users.html",
        await _admin_context(
            db,
            request,
            title="Utilisateurs",
            active_section="users",
            user=user,
            users=users,
            roles=roles,
            filter_status=status,
            filter_role=role,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Actions on a single user — return the rendered row partial
# ─────────────────────────────────────────────────────────────────────────────
async def _render_user_row(
    request: Request, db: AsyncSession, target: User
) -> HTMLResponse:
    roles = await _load_roles(db)
    return templates.TemplateResponse(
        request,
        "partials/admin/user-row.html",
        web_context(request, user_row=target, roles=roles),
    )


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    return None


async def _get_user_or_404(db: AsyncSession, uid: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == uid))
    return result.unique().scalar_one_or_none()


@router.post("/users/{user_id}/approve", response_class=HTMLResponse)
async def admin_user_approve(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    target.approval_status = ApprovalStatus.APPROVED
    target.rejection_reason = None
    target.approved_by = uuid.UUID(user["id"])
    from datetime import datetime, timezone
    target.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(target)
    return await _render_user_row(request, db, target)


@router.post("/users/{user_id}/reject", response_class=HTMLResponse)
async def admin_user_reject(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    reason: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    target.approval_status = ApprovalStatus.REJECTED
    target.rejection_reason = (reason or "").strip() or None
    await db.commit()
    await db.refresh(target)
    return await _render_user_row(request, db, target)


@router.post("/users/{user_id}/role", response_class=HTMLResponse)
async def admin_user_role(
    request: Request,
    user_id: uuid.UUID,
    role_id: Annotated[int, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    # Ensure role exists
    role_exists = await db.execute(select(Role.id).where(Role.id == role_id))
    if role_exists.scalar_one_or_none() is None:
        return HTMLResponse(
            "<div class='toast toast--error'>Rôle inconnu.</div>",
            status_code=400,
        )

    target.role_id = role_id
    # role 1 = admin → flip is_superuser to keep the session check coherent
    target.is_superuser = role_id == 1
    await db.commit()
    await db.refresh(target)
    return await _render_user_row(request, db, target)


@router.post("/users/{user_id}/active", response_class=HTMLResponse)
async def admin_user_toggle_active(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    target.is_active = not target.is_active
    await db.commit()
    await db.refresh(target)
    return await _render_user_row(request, db, target)


@router.delete("/users/{user_id}", response_class=Response)
async def admin_user_delete(
    request: Request,
    user_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    if str(user_id) == user["id"]:
        return HTMLResponse(
            "<div class='toast toast--error'>Vous ne pouvez pas supprimer votre propre compte.</div>",
            status_code=400,
        )
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return Response(status_code=404)
    await db.delete(target)
    await db.commit()
    return Response(status_code=200, content="")


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/documents — cross-user list
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/documents", response_class=HTMLResponse)
async def admin_documents(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    query = select(Document, User.email).join(User, User.id == Document.user_id).order_by(Document.created_at.desc()).limit(200)
    result = await db.execute(query)
    rows = []
    for doc, email in result.unique().all():
        rows.append(
            {
                "doc": doc,
                "user_email": email,
                "size": _human_size(doc.file_size),
                "indexed": (doc.chunk_count or 0) > 0,
            }
        )

    return templates.TemplateResponse(
        request,
        "pages/admin/documents.html",
        await _admin_context(
            db,
            request,
            title="Documents",
            active_section="documents",
            user=user,
            rows=rows,
            total=len(rows),
        ),
    )


@router.delete("/documents/{document_id}", response_class=Response)
async def admin_document_delete(
    request: Request,
    document_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.unique().scalar_one_or_none()
    if doc is None:
        return Response(status_code=404)
    try:
        await db.delete(doc)
        await db.commit()
    except Exception:
        await db.rollback()
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>",
            status_code=500,
        )
    return Response(status_code=200, content="")
