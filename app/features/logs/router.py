"""
Router admin pour les logs applicatifs

Endpoints protégés superuser pour consulter, filtrer, exporter et purger les logs.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_session, get_current_admin_user
from app.features.logs.service import LogService
from app.features.logs.schemas import (
    LogListResponse,
    LogStatsResponse,
    LogCleanupRequest,
    LogCleanupResponse,
    AlertListResponse,
    BulkLogDeleteRequest,
    BulkLogDeleteResponse,
)
from app.features.admin.export.schemas import ExportFormat
from app.features.admin.export.service import ExportService
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/logs",
    tags=["Admin - Logs"],
)


@router.get("", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Taille de page"),
    log_category: Optional[str] = Query(None, description="Filtrer par catégorie"),
    level: Optional[str] = Query(None, description="Filtrer par niveau"),
    search: Optional[str] = Query(None, description="Recherche texte"),
    user_id: Optional[UUID] = Query(None, description="Filtrer par utilisateur"),
    request_id: Optional[str] = Query(None, description="Filtrer par request_id"),
    date_from: Optional[datetime] = Query(None, description="Date de début"),
    date_to: Optional[datetime] = Query(None, description="Date de fin"),
    is_alert: Optional[bool] = Query(None, description="Filtrer les alertes"),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Liste les logs applicatifs avec filtres et pagination.

    Réservé aux administrateurs.
    """
    return await LogService.get_logs(
        db=db,
        page=page,
        page_size=page_size,
        log_category=log_category,
        level=level,
        search=search,
        user_id=user_id,
        request_id=request_id,
        date_from=date_from,
        date_to=date_to,
        is_alert=is_alert,
    )


@router.get("/stats", response_model=LogStatsResponse)
async def get_log_stats(
    date_from: Optional[datetime] = Query(None, description="Date de début"),
    date_to: Optional[datetime] = Query(None, description="Date de fin"),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Statistiques des logs (comptages par catégorie, niveau, alertes).

    Réservé aux administrateurs.
    """
    return await LogService.get_stats(db=db, date_from=date_from, date_to=date_to)


@router.get("/alerts", response_model=AlertListResponse)
async def get_alerts(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Taille de page"),
    log_category: Optional[str] = Query(None, description="Filtrer par catégorie"),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Liste les alertes récentes (logs flaggés is_alert=True).

    Réservé aux administrateurs.
    """
    return await LogService.get_alerts(
        db=db,
        page=page,
        page_size=page_size,
        log_category=log_category,
    )


@router.get("/export")
async def export_logs(
    format: ExportFormat = ExportFormat.CSV,
    log_category: Optional[str] = Query(None, description="Filtrer par catégorie"),
    level: Optional[str] = Query(None, description="Filtrer par niveau"),
    search: Optional[str] = Query(None, description="Recherche texte"),
    date_from: Optional[datetime] = Query(None, description="Date de début"),
    date_to: Optional[datetime] = Query(None, description="Date de fin"),
    limit: int = Query(10000, ge=1, le=50000, description="Nombre max de logs"),
    request: Request = None,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Exporte les logs applicatifs en CSV ou JSON.

    Query Parameters:
    - format: Format d'export (csv ou json, défaut: csv)
    - log_category: Filtrer par catégorie
    - level: Filtrer par niveau (INFO, WARNING, ERROR, etc.)
    - search: Recherche texte dans message/logger
    - date_from / date_to: Plage de dates
    - limit: Nombre max d'enregistrements (défaut: 10000, max: 50000)

    Réservé aux administrateurs.
    """
    data = await LogService.export_logs(
        db=db,
        log_category=log_category,
        level=level,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )

    if format == ExportFormat.CSV:
        content = ExportService.to_csv(data)
        media_type = "text/csv"
    else:
        content = ExportService.to_json(data)
        media_type = "application/json"

    # Audit log de l'export
    await AuditService.log_action(
        db=db,
        action_name='data_exported',
        user_id=current_user.id,
        resource_type_name='app_log',
        resource_id=None,
        details={
            'export_type': 'app_logs',
            'format': format.value,
            'records_count': len(data),
            'filters': {
                'log_category': log_category,
                'level': level,
                'search': search,
                'date_from': date_from.isoformat() if date_from else None,
                'date_to': date_to.isoformat() if date_to else None,
            },
        },
        request=request,
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/logs/export", method="GET", status="200"
    ).inc()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"app_logs_{timestamp}.{format.value}"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post("/bulk/delete", response_model=BulkLogDeleteResponse)
async def bulk_delete_logs(
    data: BulkLogDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Supprime des logs en masse par leurs IDs.

    Body:
    - log_ids: Liste des UUIDs des logs à supprimer (max 1000)
    - confirm: Doit être true pour confirmer la suppression

    Réservé aux administrateurs.
    """
    if not data.confirm:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm=true)")

    result = await LogService.bulk_delete(db=db, log_ids=data.log_ids)

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='bulk_deleted',
        user_id=current_user.id,
        resource_type_name='app_log',
        resource_id=None,
        details={
            'action': 'bulk_delete_logs',
            'requested_count': len(data.log_ids),
            'deleted_count': result.success_count,
        },
        request=request,
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/logs/bulk/delete", method="POST", status="200"
    ).inc()

    logger.info(
        "Bulk delete logs: requested=%d deleted=%d",
        len(data.log_ids),
        result.success_count,
    )

    return result


@router.delete("/cleanup", response_model=LogCleanupResponse)
async def cleanup_logs(
    request: LogCleanupRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Purge les logs selon les critères de rétention.

    Réservé aux administrateurs.
    """
    result = await LogService.cleanup(
        db=db,
        category=request.category,
        older_than_days=request.older_than_days,
    )

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='logs_purged',
        user_id=current_user.id,
        resource_type_name='app_log',
        resource_id=None,
        details={
            'action': 'cleanup_logs',
            'category': request.category,
            'older_than_days': request.older_than_days,
            'deleted_count': result.deleted_count,
        },
        request=http_request,
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/logs/cleanup", method="DELETE", status="200"
    ).inc()

    logger.info(
        "Logs cleanup: deleted=%d category=%s older_than=%d days",
        result.deleted_count,
        request.category,
        request.older_than_days,
    )
    return result
