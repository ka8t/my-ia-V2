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

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import (
    ApprovalStatus,
    Collection,
    ContextSource,
    Conversation,
    Corpus,
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
    """Dashboard admin enrichi (Phase 3.9.d) — overview + trends + usage daily."""
    from app.features.admin.dashboard.service import DashboardService

    # Compteurs simples (utilisés par les tuiles cliquables existantes)
    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    pending_users = (await db.execute(
        select(func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING)
    )).scalar_one()
    total_conversations = (await db.execute(select(func.count(Conversation.id)))).scalar_one()
    total_documents = (await db.execute(select(func.count(Document.id)))).scalar_one()
    total_corpus = (await db.execute(select(func.count(Corpus.id)))).scalar_one()
    total_sources = (await db.execute(select(func.count(ContextSource.id)))).scalar_one()

    stats = {
        "users": total_users,
        "users_pending": pending_users,
        "conversations": total_conversations,
        "documents": total_documents,
        "corpus": total_corpus,
        "sources": total_sources,
    }

    # Analytics enrichies — best-effort, on n'échoue pas le dashboard si une
    # sous-requête plante.
    overview = trends = usage_daily = None
    try:
        overview = await DashboardService.get_overview(db)
    except Exception as e:
        logger.warning("Dashboard overview unavailable: %s", e)
    try:
        trends = await DashboardService.get_trends(db)
    except Exception as e:
        logger.warning("Dashboard trends unavailable: %s", e)
    try:
        usage_daily = await DashboardService.get_usage_daily(db, days=30)
    except Exception as e:
        logger.warning("Dashboard usage_daily unavailable: %s", e)

    return templates.TemplateResponse(
        request,
        "pages/admin/dashboard.html",
        await _admin_context(
            db, request, title="Admin", active_section="dashboard", user=user,
            stats=stats,
            overview=overview, trends=trends, usage_daily=usage_daily,
        ),
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
    q: str | None = None,
    active: str | None = None,
    verified: str | None = None,
    sort: str = "date",
    order: str = "desc",
    page: int = 1,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Liste paginée + filtrée + triée + recherche (parité V1 users.js)."""
    from sqlalchemy.orm import joinedload as _joinedload
    page_size = 25
    # Eager-load preferences (utilisé dans le partial pour voice_to_text)
    query = select(User).options(_joinedload(User.preferences))
    if status in {"pending", "approved", "rejected"}:
        query = query.where(User.approval_status == status)
    if role is not None:
        query = query.where(User.role_id == role)
    if active in {"true", "false"}:
        query = query.where(User.is_active == (active == "true"))
    if verified in {"true", "false"}:
        query = query.where(User.is_verified == (verified == "true"))
    if q:
        # Search ILIKE sur email + username
        like = f"%{q.strip()}%"
        query = query.where((User.email.ilike(like)) | (User.username.ilike(like)))

    # Tri
    sort_col = {
        "email": User.email,
        "username": User.username,
        "role": User.role_id,
        "date": User.created_at,
    }.get(sort, User.created_at)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    page = max(1, page)
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    users = list(result.unique().scalars().all())
    total_pages = max(1, (total + page_size - 1) // page_size)
    roles = await _load_roles(db)

    # Charger les collections privées des users affichés (pour afficher
    # le bouton "créer collection" si absent — parité V1 users.js).
    user_ids = [u.id for u in users]
    user_has_collection: dict = {}
    if user_ids:
        cols_result = await db.execute(
            select(Collection.owner_id).where(
                Collection.owner_id.in_(user_ids),
                Collection.type == "private",
            )
        )
        for owner_id in cols_result.scalars().all():
            user_has_collection[owner_id] = True

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
            user_has_collection=user_has_collection,
            filter_status=status,
            filter_role=role,
            q=q or "",
            active=active or "",
            verified=verified or "",
            sort=sort,
            order=order,
            page=page,
            total=total,
            total_pages=total_pages,
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
    q: str | None = None,
    visibility: str | None = None,
    indexed: str | None = None,
    sort: str = "date",
    order: str = "desc",
    page: int = 1,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Liste cross-user paginée + filtrée (parité V1 content-documents.js)."""
    from sqlalchemy.orm import joinedload as _joinedload
    page_size = 25
    query = (
        select(Document, User.email)
        .join(User, User.id == Document.user_id)
        .options(_joinedload(Document.collection))
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.where(Document.filename.ilike(like))
    if visibility in {"private", "public"}:
        query = query.where(Document.visibility == visibility)
    if indexed in {"true", "false"}:
        if indexed == "true":
            query = query.where(Document.chunk_count > 0)
        else:
            query = query.where((Document.chunk_count.is_(None)) | (Document.chunk_count == 0))

    sort_col = {
        "name": Document.filename,
        "size": Document.file_size,
        "date": Document.updated_at,
    }.get(sort, Document.updated_at)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

    # Total count
    count_q = select(func.count(Document.id)).select_from(Document)
    if q: count_q = count_q.where(Document.filename.ilike(f"%{q.strip()}%"))
    if visibility in {"private", "public"}: count_q = count_q.where(Document.visibility == visibility)
    if indexed == "true": count_q = count_q.where(Document.chunk_count > 0)
    if indexed == "false": count_q = count_q.where((Document.chunk_count.is_(None)) | (Document.chunk_count == 0))
    total = (await db.execute(count_q)).scalar_one()

    page = max(1, page)
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = []
    for doc, email in result.unique().all():
        rows.append({
            "doc": doc,
            "user_email": email,
            "size": _human_size(doc.file_size),
            "indexed": (doc.chunk_count or 0) > 0,
        })
    total_pages = max(1, (total + page_size - 1) // page_size)

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
            total=total,
            q=q or "",
            visibility=visibility or "",
            indexed=indexed or "",
            sort=sort,
            order=order,
            page=page,
            total_pages=total_pages,
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


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.9.a — Audit log viewer
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/audit", response_class=HTMLResponse)
async def admin_audit_get(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    severity: str | None = None,
    user_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Vue paginée des audit_logs avec filtres simples."""
    from datetime import datetime
    from app.features.audit.repository import AuditRepository

    page = max(1, int(page))
    page_size = max(10, min(int(page_size), 200))

    # Filtres date — format ISO YYYY-MM-DD attendu
    parsed_from = parsed_to = None
    if date_from:
        try:
            parsed_from = datetime.fromisoformat(date_from)
        except ValueError:
            parsed_from = None
    if date_to:
        try:
            parsed_to = datetime.fromisoformat(date_to)
        except ValueError:
            parsed_to = None

    # Résolution user_email → user_id (recherche partielle)
    user_id = None
    if user_email:
        result = await db.execute(
            select(User.id).where(User.email.ilike(f"%{user_email.strip()}%")).limit(1)
        )
        user_id = result.scalar_one_or_none()

    logs, total = await AuditRepository.get_logs(
        db=db,
        skip=(page - 1) * page_size,
        limit=page_size,
        user_id=user_id,
        action_name=action.strip() if action else None,
        date_from=parsed_from,
        date_to=parsed_to,
    )

    # Liste des actions distinctes pour le select
    all_actions = await AuditRepository.get_all_actions(db)
    pending = await _pending_users_count(db)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "pages/admin/audit.html",
        web_context(
            request,
            title="Journal d'audit",
            active_section="audit",
            user=user,
            pending_users_count=pending,
            logs=logs,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            all_actions=all_actions,
            filter_action=action or "",
            filter_severity=severity or "",
            filter_user_email=user_email or "",
            filter_date_from=date_from or "",
            filter_date_to=date_to or "",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.9.b — App logs viewer (table app_logs)
# ═════════════════════════════════════════════════════════════════════════════
_LOG_LEVELS_FILTER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_CATEGORIES = ("technical", "access", "audit", "security", "infra")


@router.get("/logs", response_class=HTMLResponse)
async def admin_logs_get(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    level: str | None = None,
    log_category: str | None = None,
    search: str | None = None,
    is_alert: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from datetime import datetime
    from app.features.logs.service import LogService

    page = max(1, int(page))
    page_size = max(10, min(int(page_size), 200))

    parsed_from = parsed_to = None
    if date_from:
        try:
            parsed_from = datetime.fromisoformat(date_from)
        except ValueError:
            parsed_from = None
    if date_to:
        try:
            parsed_to = datetime.fromisoformat(date_to)
        except ValueError:
            parsed_to = None

    is_alert_bool = None
    if is_alert == "yes":
        is_alert_bool = True
    elif is_alert == "no":
        is_alert_bool = False

    response = await LogService.get_logs(
        db=db,
        page=page,
        page_size=page_size,
        log_category=log_category if log_category in _LOG_CATEGORIES else None,
        level=level if level in _LOG_LEVELS_FILTER else None,
        search=(search or "").strip() or None,
        date_from=parsed_from,
        date_to=parsed_to,
        is_alert=is_alert_bool,
    )

    pending = await _pending_users_count(db)
    return templates.TemplateResponse(
        request,
        "pages/admin/logs.html",
        web_context(
            request,
            title="Logs serveur",
            active_section="logs",
            user=user,
            pending_users_count=pending,
            items=response.items,
            total=response.total,
            page=response.page,
            page_size=response.page_size,
            total_pages=response.total_pages,
            log_levels=_LOG_LEVELS_FILTER,
            log_categories=_LOG_CATEGORIES,
            filter_level=level or "",
            filter_category=log_category or "",
            filter_search=search or "",
            filter_is_alert=is_alert or "",
            filter_date_from=date_from or "",
            filter_date_to=date_to or "",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.9.c — Validation workflow (pending users + bulk actions)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/validation", response_class=HTMLResponse)
async def admin_validation_get(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from app.features.admin.validation.service import ValidationService

    page = max(1, int(page))
    page_size = max(10, min(int(page_size), 200))

    pending_list, total = await ValidationService.get_pending_users(
        db, limit=page_size, offset=(page - 1) * page_size,
    )
    stats = await ValidationService.get_validation_stats(db)
    pending = await _pending_users_count(db)

    total_pages = max(1, (total + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request,
        "pages/admin/validation.html",
        web_context(
            request,
            title="Validation des inscriptions",
            active_section="validation",
            user=user,
            pending_users_count=pending,
            pending_users=pending_list,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            stats=stats,
        ),
    )


@router.post("/validation/bulk-approve", response_class=HTMLResponse)
async def admin_validation_bulk_approve(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from app.features.admin.validation.service import ValidationService

    form = await request.form()
    if not verify_csrf_token(request, form.get("csrf_token")):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>", status_code=400
        )

    selected = [v for k, v in form.multi_items() if k == "user_ids"]
    user_ids: list[uuid.UUID] = []
    for raw in selected:
        try:
            user_ids.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    if not user_ids:
        return HTMLResponse(
            "<div class='toast toast--error'>Aucun utilisateur sélectionné.</div>",
            status_code=400,
        )

    result = await ValidationService.bulk_approve_users(
        db, user_ids=user_ids, approver_id=uuid.UUID(user["id"])
    )
    logger.info(
        "Admin %s bulk-approve : %d ok, %d errs",
        user.get("email"), result.get("success_count", 0), result.get("failed_count", 0),
    )
    return RedirectResponse(url="/web/admin/validation", status_code=303)


@router.post("/validation/bulk-reject", response_class=HTMLResponse)
async def admin_validation_bulk_reject(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from app.features.admin.validation.service import ValidationService

    form = await request.form()
    if not verify_csrf_token(request, form.get("csrf_token")):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>", status_code=400
        )

    selected = [v for k, v in form.multi_items() if k == "user_ids"]
    user_ids: list[uuid.UUID] = []
    for raw in selected:
        try:
            user_ids.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    reason = (form.get("reason") or "").strip() or None

    if not user_ids:
        return HTMLResponse(
            "<div class='toast toast--error'>Aucun utilisateur sélectionné.</div>",
            status_code=400,
        )

    result = await ValidationService.bulk_reject_users(
        db, user_ids=user_ids, approver_id=uuid.UUID(user["id"]),
        reason=reason or "Inscription rejetée.",
    )
    logger.info(
        "Admin %s bulk-reject : %d ok, %d errs, reason=%r",
        user.get("email"), result.get("success_count", 0),
        result.get("failed_count", 0), reason,
    )
    return RedirectResponse(url="/web/admin/validation", status_code=303)


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.4.a — Admin/users : create, edit, voice-to-text, create-collection,
#  bulk (parité V1 users.js)
# ═════════════════════════════════════════════════════════════════════════════
from fastapi_users.password import PasswordHelper as _AdminPasswordHelper

_admin_pwd_helper = _AdminPasswordHelper()


@router.post("/users", response_class=HTMLResponse)
async def admin_user_create(
    request: Request,
    email: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role_id: Annotated[int, Form()] = 2,
    first_name: Annotated[str | None, Form()] = None,
    last_name: Annotated[str | None, Form()] = None,
    is_active: Annotated[str | None, Form()] = "true",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Création utilisateur (parité V1 users.js:UserForm save)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    email = (email or "").strip().lower()
    username = (username or "").strip()
    if not email or not username or not password:
        return HTMLResponse(
            "<div class='toast toast--error'>Email, identifiant et mot de passe requis.</div>",
            status_code=400,
        )

    # Vérifier unicité
    existing = await db.execute(
        select(User).where((User.email == email) | (User.username == username))
    )
    if existing.unique().scalar_one_or_none() is not None:
        return HTMLResponse(
            "<div class='toast toast--error'>Email ou identifiant déjà utilisé.</div>",
            status_code=409,
        )

    new_user = User(
        email=email,
        username=username,
        hashed_password=_admin_pwd_helper.hash(password),
        role_id=role_id,
        is_active=(is_active == "true"),
        is_superuser=(role_id == 1),
        is_verified=True,  # créé par admin → considéré vérifié
        approval_status=ApprovalStatus.APPROVED,
        first_name=(first_name or "").strip() or None,
        last_name=(last_name or "").strip() or None,
    )
    db.add(new_user)
    try:
        await db.commit()
        await db.refresh(new_user)
    except Exception:
        await db.rollback()
        logger.exception("Create user failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec de la création.</div>",
            status_code=500,
        )
    return HTMLResponse(
        f"<div class='toast toast--success'>Utilisateur {email} créé.</div>",
        status_code=201,
        headers={"HX-Trigger": "users-refresh"},
    )


@router.patch("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_edit(
    request: Request,
    user_id: uuid.UUID,
    email: Annotated[str | None, Form()] = None,
    username: Annotated[str | None, Form()] = None,
    first_name: Annotated[str | None, Form()] = None,
    last_name: Annotated[str | None, Form()] = None,
    phone: Annotated[str | None, Form()] = None,
    new_password: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Édition complète d'un utilisateur (parité V1 users.js:editUser)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    if email and email.strip().lower() != target.email:
        # Vérifier unicité
        existing = await db.execute(
            select(User).where(User.email == email.strip().lower(), User.id != target.id)
        )
        if existing.unique().scalar_one_or_none() is not None:
            return HTMLResponse(
                "<div class='toast toast--error'>Email déjà utilisé.</div>",
                status_code=409,
            )
        target.email = email.strip().lower()

    if username and username.strip() != target.username:
        existing = await db.execute(
            select(User).where(User.username == username.strip(), User.id != target.id)
        )
        if existing.unique().scalar_one_or_none() is not None:
            return HTMLResponse(
                "<div class='toast toast--error'>Identifiant déjà utilisé.</div>",
                status_code=409,
            )
        target.username = username.strip()

    if first_name is not None:
        target.first_name = first_name.strip() or None
    if last_name is not None:
        target.last_name = last_name.strip() or None
    if phone is not None:
        target.phone = phone.strip() or None
    if new_password:
        target.hashed_password = _admin_pwd_helper.hash(new_password)

    try:
        await db.commit()
        await db.refresh(target)
    except Exception:
        await db.rollback()
        logger.exception("Edit user failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec.</div>",
            status_code=500,
        )
    return await _render_user_row(request, db, target)


@router.post("/users/{user_id}/voice-to-text", response_class=HTMLResponse)
async def admin_user_toggle_voice(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Toggle voice-to-text d'un user (parité V1 users.js:toggleVoiceToText)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)
    # UserPreference est lazy-loaded — on charge ou crée
    from app.models import UserPreference
    pref = (
        await db.execute(select(UserPreference).where(UserPreference.user_id == user_id))
    ).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user_id)
        db.add(pref)
        await db.flush()
    pref.voice_to_text_enabled = not pref.voice_to_text_enabled
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Toggle voice failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec.</div>",
            status_code=500,
        )
    await db.refresh(target)
    return await _render_user_row(request, db, target)


@router.post("/users/{user_id}/create-collection", response_class=HTMLResponse)
async def admin_user_create_collection(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Crée la collection privée d'un user qui n'en a pas (parité V1)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)

    existing = await db.execute(
        select(Collection).where(
            Collection.owner_id == user_id, Collection.type == "private"
        )
    )
    if existing.unique().scalar_one_or_none() is not None:
        return HTMLResponse(
            "<div class='toast toast--info'>Collection déjà existante.</div>",
            status_code=200,
        )

    coll = Collection(
        name=f"user_{user_id}",
        display_name="Personnel",
        type="private",
        owner_id=user_id,
    )
    db.add(coll)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Create collection failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec.</div>",
            status_code=500,
        )
    return await _render_user_row(request, db, target)


@router.post("/users/bulk-action", response_class=HTMLResponse)
async def admin_users_bulk(
    request: Request,
    action: Annotated[str, Form()],
    user_ids: Annotated[list[str], Form()],
    role_id: Annotated[int | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Actions en masse (parité V1 users.js:bulkActions).

    action ∈ {activate, deactivate, delete, change-role, approve, reject}.
    """
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if action not in {"activate", "deactivate", "delete", "change-role", "approve", "reject"}:
        return HTMLResponse(
            "<div class='toast toast--error'>Action invalide.</div>",
            status_code=400,
        )
    self_id = uuid.UUID(user["id"])
    affected = 0
    for raw in user_ids:
        try:
            uid = uuid.UUID(raw)
        except ValueError:
            continue
        if action == "delete" and uid == self_id:
            continue  # protection
        target = await _get_user_or_404(db, uid)
        if target is None:
            continue
        if action == "activate":
            target.is_active = True
        elif action == "deactivate":
            target.is_active = False
        elif action == "delete":
            await db.delete(target)
        elif action == "change-role" and role_id is not None:
            target.role_id = role_id
            target.is_superuser = role_id == 1
        elif action == "approve":
            target.approval_status = ApprovalStatus.APPROVED
            target.approved_by = self_id
            from datetime import datetime, timezone
            target.approved_at = datetime.now(timezone.utc)
        elif action == "reject":
            target.approval_status = ApprovalStatus.REJECTED
        affected += 1
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Bulk action failed")
        return HTMLResponse(
            "<div class='toast toast--error'>Échec bulk.</div>",
            status_code=500,
        )
    return HTMLResponse(
        f"<div class='toast toast--success'>{affected} utilisateur(s) modifié(s).</div>",
        status_code=200,
        headers={"HX-Trigger": "users-refresh"},
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.4.b — Admin/documents : visibility, reindex, clear, details, bulk
# ═════════════════════════════════════════════════════════════════════════════

async def _render_admin_doc_row(request: Request, db: AsyncSession, doc: Document) -> HTMLResponse:
    """Renvoie le row partial admin (re-fetch user email)."""
    from sqlalchemy.orm import joinedload as _joinedload
    res = await db.execute(
        select(Document, User.email)
        .join(User, User.id == Document.user_id)
        .options(_joinedload(Document.collection))
        .where(Document.id == doc.id)
    )
    row_data = res.unique().one_or_none()
    if row_data is None:
        return HTMLResponse("", status_code=404)
    fresh_doc, email = row_data
    return templates.TemplateResponse(
        request,
        "partials/admin/doc-row.html",
        web_context(
            request,
            row={
                "doc": fresh_doc,
                "user_email": email,
                "size": _human_size(fresh_doc.file_size),
                "indexed": (fresh_doc.chunk_count or 0) > 0,
            },
        ),
    )


@router.post("/documents/{doc_id}/visibility", response_class=HTMLResponse)
async def admin_doc_toggle_visibility(
    request: Request,
    doc_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)
    doc.visibility = "private" if str(doc.visibility) == "public" else "public"
    await db.commit()
    return await _render_admin_doc_row(request, db, doc)


@router.post("/documents/{doc_id}/reindex", response_class=HTMLResponse)
async def admin_doc_reindex(
    request: Request,
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.core.deps import get_storage_service, get_chroma_client as _gcc
        from app.features.ingestion.router import _run_indexation_in_background, set_doc_reindex_progress

        storage = get_storage_service()
        if not doc.file_path:
            return HTMLResponse(
                "<div class='toast toast--error'>Fichier source absent.</div>",
                status_code=400,
            )
        content = await storage.download(doc.file_path)
        file_ext = (doc.filename or "").rsplit(".", 1)[-1] if "." in (doc.filename or "") else "txt"
        # Collection cible
        collection_name = None
        if doc.collection_id:
            from app.models import Collection as _Collection
            col = (await db.execute(select(_Collection).where(_Collection.id == doc.collection_id))).unique().scalar_one_or_none()
            if col:
                collection_name = col.name

        set_doc_reindex_progress(str(doc.id), 0, "queued", document_name=doc.filename)
        background_tasks.add_task(
            _run_indexation_in_background,
            document_id=doc.id,
            content=content,
            file_ext=file_ext,
            collection_name=collection_name,
        )
    except Exception as exc:
        logger.exception("Admin reindex failed")
        return HTMLResponse(
            f"<div class='toast toast--error'>Échec : {exc}</div>",
            status_code=500,
        )
    return await _render_admin_doc_row(request, db, doc)


@router.post("/documents/{doc_id}/clear-index", response_class=HTMLResponse)
async def admin_doc_clear_index(
    request: Request,
    doc_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)
    doc.chunk_count = 0
    doc.embedding_count = 0
    await db.commit()
    return await _render_admin_doc_row(request, db, doc)


@router.get("/documents/{doc_id}/details", response_class=HTMLResponse)
async def admin_doc_details(
    request: Request,
    doc_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from sqlalchemy.orm import joinedload as _joinedload
    res = await db.execute(
        select(Document, User.email)
        .join(User, User.id == Document.user_id)
        .options(_joinedload(Document.collection))
        .where(Document.id == doc_id)
    )
    row = res.unique().one_or_none()
    if row is None:
        return HTMLResponse("Document introuvable.", status_code=404)
    doc, email = row
    return templates.TemplateResponse(
        request,
        "partials/admin/doc-details-modal.html",
        web_context(request, doc=doc, owner_email=email, size=_human_size(doc.file_size)),
    )


@router.post("/documents/bulk-action", response_class=HTMLResponse)
async def admin_docs_bulk(
    request: Request,
    action: Annotated[str, Form()],
    doc_ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if action not in {"delete", "toggle-public", "toggle-private", "clear-index"}:
        return HTMLResponse("<div class='toast toast--error'>Action invalide.</div>", status_code=400)
    affected = 0
    for raw in doc_ids:
        try:
            did = uuid.UUID(raw)
        except ValueError:
            continue
        doc = (await db.execute(select(Document).where(Document.id == did))).unique().scalar_one_or_none()
        if doc is None:
            continue
        if action == "delete":
            await db.delete(doc)
        elif action == "toggle-public":
            doc.visibility = "public"
        elif action == "toggle-private":
            doc.visibility = "private"
        elif action == "clear-index":
            doc.chunk_count = 0
            doc.embedding_count = 0
        affected += 1
    if affected:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            return HTMLResponse("<div class='toast toast--error'>Échec.</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{affected} document(s) traité(s).</div>",
        headers={"HX-Trigger": "docs-refresh"},
    )


@router.get("/documents/{doc_id}/row", response_class=HTMLResponse)
async def admin_doc_row(
    request: Request,
    doc_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Refresh d'une ligne admin (HTMX polling status indexation)."""
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).unique().scalar_one_or_none()
    if doc is None:
        return HTMLResponse("", status_code=404)
    return await _render_admin_doc_row(request, db, doc)


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.6.a — admin/audit : modal détails, purge, exports CSV
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/audit/log/{log_id}/details", response_class=HTMLResponse)
async def admin_audit_log_details(
    request: Request,
    log_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Modal détails d'un log d'audit (parité V1 audit.js:showLogDetail)."""
    try:
        from app.features.audit.repository import AuditRepository
        log = await AuditRepository.get_log_by_id(db, log_id)
    except Exception:
        log = None
    if log is None:
        return HTMLResponse("Log introuvable.", status_code=404)
    details = log.details if isinstance(log.details, dict) else {}
    rows = "".join(
        f"<dt>{k}</dt><dd><code>{str(v)[:200]}</code></dd>"
        for k, v in details.items()
    )
    action_name = log.action.name if log.action else "—"
    severity = getattr(log.action, 'severity', '—') if log.action else '—'
    user_email = log.user.email if log.user else "—"
    res_name = log.resource_type.name if log.resource_type else "—"
    res_id = str(log.resource_id)[:24] if log.resource_id else "—"
    return HTMLResponse(
        f"""<header class='admin-modal__head'>
        <h2>Log #{str(log.id)[:8]}</h2>
        <button type='button' x-on:click='auditLogId = null'>✕</button>
        </header>
        <dl class='docs-modal__meta'>
        <dt>Action</dt><dd><code>{action_name}</code></dd>
        <dt>Sévérité</dt><dd>{severity}</dd>
        <dt>Utilisateur</dt><dd>{user_email}</dd>
        <dt>Resource</dt><dd>{res_name} / <code>{res_id}</code></dd>
        <dt>Date</dt><dd>{log.created_at.strftime('%d/%m/%Y %H:%M:%S') if log.created_at else '—'}</dd>
        <dt>IP</dt><dd>{log.ip_address or '—'}</dd>
        {rows}
        </dl>
        <footer class='admin-modal__foot'>
          <button type='button' class='btn btn--ghost btn--sm' x-on:click='auditLogId = null'>Fermer</button>
        </footer>"""
    )


@router.post("/audit/purge", response_class=HTMLResponse)
async def admin_audit_purge(
    request: Request,
    older_than_days: Annotated[int, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Purge logs audit > N jours (parité V1 audit.js:purgeAuditLogs)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if older_than_days < 1:
        return HTMLResponse("<div class='toast toast--error'>Nombre de jours invalide.</div>", status_code=400)
    try:
        from app.features.audit.repository import AuditRepository
        n = await AuditRepository.delete_old_logs(db, days=older_than_days)
        await db.commit()
    except Exception as exc:
        logger.exception("Audit purge failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{n} log(s) audit purgé(s) (>{older_than_days}j).</div>"
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.6.b — admin/logs : stats, cleanup, modal détail, alertes
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/logs/stats", response_class=HTMLResponse)
async def admin_logs_stats(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Stats logs par level/category (parité V1 content-logs.js:loadStats)."""
    try:
        from app.features.logs.service import LogService
        stats = await LogService.get_stats(db)
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Stats indisponibles : {exc}</div>")
    parts = ["<dl class='docs-modal__meta'>"]
    by_level = stats.get("by_level", {}) if isinstance(stats, dict) else getattr(stats, "by_level", {}) or {}
    by_cat = stats.get("by_category", {}) if isinstance(stats, dict) else getattr(stats, "by_category", {}) or {}
    total = stats.get("total", 0) if isinstance(stats, dict) else getattr(stats, "total", 0)
    parts.append(f"<dt>Total</dt><dd>{total}</dd>")
    for k, v in by_level.items():
        parts.append(f"<dt>Level <code>{k}</code></dt><dd>{v}</dd>")
    for k, v in by_cat.items():
        parts.append(f"<dt>Cat <code>{k}</code></dt><dd>{v}</dd>")
    parts.append("</dl>")
    return HTMLResponse("".join(parts))


@router.post("/logs/cleanup", response_class=HTMLResponse)
async def admin_logs_cleanup(
    request: Request,
    older_than_days: Annotated[int, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Cleanup logs > N jours (parité V1 content-logs.js:cleanup)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if older_than_days < 1:
        return HTMLResponse("<div class='toast toast--error'>Nombre de jours invalide.</div>", status_code=400)
    try:
        from app.features.logs.service import LogService
        n = await LogService.cleanup(db, older_than_days=older_than_days)
    except Exception as exc:
        logger.exception("Logs cleanup failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{n} log(s) supprimé(s) (>{older_than_days}j).</div>"
    )


@router.get("/logs/{log_id}/details", response_class=HTMLResponse)
async def admin_logs_details(
    request: Request,
    log_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Modal détails d'un log applicatif."""
    from app.models import AppLog
    log = (await db.execute(select(AppLog).where(AppLog.id == log_id))).unique().scalar_one_or_none()
    if log is None:
        return HTMLResponse("Log introuvable.", status_code=404)
    ctx = log.context if isinstance(log.context, dict) else {}
    rows = "".join(
        f"<dt>{k}</dt><dd><code style='font-size:11px; word-break:break-all'>{str(v)[:500]}</code></dd>"
        for k, v in ctx.items()
    )
    return HTMLResponse(
        f"""<header class='admin-modal__head'>
        <h2>Log #{str(log.id)[:8]}</h2>
        <button type='button' x-on:click='logId = null'>✕</button>
        </header>
        <dl class='docs-modal__meta'>
        <dt>Level</dt><dd>{log.level}</dd>
        <dt>Category</dt><dd>{getattr(log, 'log_category', '—')}</dd>
        <dt>Service</dt><dd>{getattr(log, 'service', '—')}</dd>
        <dt>Logger</dt><dd><code>{getattr(log, 'logger_name', '—')}</code></dd>
        <dt>Date</dt><dd>{log.created_at.strftime('%d/%m/%Y %H:%M:%S') if log.created_at else '—'}</dd>
        <dt>Message</dt><dd style='white-space:pre-wrap; word-break:break-word'>{log.message[:1000] if log.message else '—'}</dd>
        {rows}
        </dl>
        <footer class='admin-modal__foot'>
          <button type='button' class='btn btn--ghost btn--sm' x-on:click='logId = null'>Fermer</button>
        </footer>"""
    )


@router.get("/logs/alerts", response_class=HTMLResponse)
async def admin_logs_alerts(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Polling alertes récentes (parité V1 startAlertPolling)."""
    try:
        from app.features.logs.service import LogService
        alerts = await LogService.get_alerts(db, hours=24)
    except Exception:
        alerts = []
    n = len(alerts) if alerts else 0
    if n == 0:
        return HTMLResponse("<small style='color:var(--color-fg-muted)'>Aucune alerte récente.</small>")
    return HTMLResponse(
        f"<span class='admin-pending-badge'>{n} alerte(s)</span>"
    )


@router.post("/logs/bulk-delete", response_class=HTMLResponse)
async def admin_logs_bulk_delete(
    request: Request,
    log_ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    try:
        ids = [uuid.UUID(s) for s in log_ids if s]
        from app.features.logs.repository import LogRepository
        repo = LogRepository(db)
        n = await repo.delete_by_ids(ids)
        await db.commit()
    except Exception as exc:
        logger.exception("Logs bulk delete failed")
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{n} log(s) supprimé(s).</div>",
        headers={"HX-Trigger": "logs-refresh"},
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.6.c — admin/validation : modal individuel + polling badge
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/validation/{user_id}/approve", response_class=HTMLResponse)
async def admin_validation_approve_single(
    request: Request,
    user_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Approve un user (parité V1 validation.js modal individuel)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    target = await _get_user_or_404(db, user_id)
    if target is None:
        return HTMLResponse("", status_code=404)
    target.approval_status = ApprovalStatus.APPROVED
    target.approved_by = uuid.UUID(user["id"])
    from datetime import datetime, timezone
    target.approved_at = datetime.now(timezone.utc)
    target.rejection_reason = None
    await db.commit()
    return HTMLResponse(
        f"<div class='toast toast--success'>{target.email} approuvé.</div>",
        headers={"HX-Trigger": "validation-refresh"},
    )


@router.post("/validation/{user_id}/reject", response_class=HTMLResponse)
async def admin_validation_reject_single(
    request: Request,
    user_id: uuid.UUID,
    reason: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
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
    return HTMLResponse(
        f"<div class='toast toast--success'>{target.email} refusé.</div>",
        headers={"HX-Trigger": "validation-refresh"},
    )


@router.get("/validation/pending-count", response_class=HTMLResponse)
async def admin_validation_pending_count(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Polling badge sidebar (parité V1 updatePendingBadge)."""
    n = await _pending_users_count(db)
    if n == 0:
        return HTMLResponse("")
    return HTMLResponse(f"<span class='admin-nav__badge'>{n}</span>")


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.6.d — admin/dashboard : timing + recent actions
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard/timing", response_class=HTMLResponse)
async def admin_dashboard_timing(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Timing stats P50/P95/P99 (parité V1 dashboard.js)."""
    try:
        from app.common.utils.timing_stats import timing_stats
        stats = timing_stats.get_all_stats()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Stats indisponibles : {exc}</div>")
    if not stats:
        return HTMLResponse("<p style='color:var(--color-fg-muted)'>Aucune donnée de timing.</p>")
    parts = ["<table class='admin-mini-table'><thead><tr><th>Opération</th><th>Count</th><th>P50 ms</th><th>P95 ms</th><th>P99 ms</th></tr></thead><tbody>"]
    for op, s in stats.items():
        if not isinstance(s, dict):
            continue
        parts.append(
            f"<tr><td><code>{op}</code></td>"
            f"<td>{s.get('count', 0)}</td>"
            f"<td>{s.get('p50_ms', 0):.0f}</td>"
            f"<td>{s.get('p95_ms', 0):.0f}</td>"
            f"<td>{s.get('p99_ms', 0):.0f}</td></tr>"
        )
    parts.append("</tbody></table>")
    return HTMLResponse("".join(parts))


@router.delete("/dashboard/timing", response_class=HTMLResponse)
async def admin_dashboard_timing_reset(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    try:
        from app.common.utils.timing_stats import timing_stats
        timing_stats.reset()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse("<div class='toast toast--success'>Timing stats réinitialisés.</div>")


@router.get("/dashboard/recent-actions", response_class=HTMLResponse)
async def admin_dashboard_recent_actions(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Recent audit actions (parité V1 dashboard.js:loadRecentActions)."""
    try:
        from app.features.audit.repository import AuditRepository
        logs, _total = await AuditRepository.get_logs(db=db, skip=0, limit=20)
    except Exception:
        logs = []
    if not logs:
        return HTMLResponse("<p style='color:var(--color-fg-muted)'>Aucune action récente.</p>")
    parts = ["<ul class='admin-bare-list'>"]
    for log in logs:
        when = log.created_at.strftime('%H:%M') if log.created_at else ''
        action_name = log.action.name if log.action else "—"
        user_email = log.user.email if log.user else "—"
        parts.append(
            f"<li class='admin-bare-list__item'>"
            f"<span class='admin-bare-list__main'><code>{action_name}</code></span>"
            f"<span class='admin-bare-list__meta'>{user_email} · {when}</span>"
            f"</li>"
        )
    parts.append("</ul>")
    return HTMLResponse("".join(parts))
