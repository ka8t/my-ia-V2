"""
Router Audit

Endpoints admin pour la consultation des logs d'audit.
"""
import csv
import io
import json
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user
from app.features.audit.repository import AuditRepository
from app.features.audit.schemas import (
    AuditLogResponse,
    AuditLogListResponse,
    AuditActionResponse,
    ResourceTypeResponse,
    AuditStatsResponse,
    AuditUserResponse
)
from app.models import User
from app.common.exceptions.http import not_found, ErrorCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Admin - Audit"])


# --- Liste et détails ---

@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user_id: Optional[UUID] = Query(None, description="Filtrer par utilisateur"),
    username: Optional[str] = Query(None, description="Filtrer par nom d'utilisateur (recherche partielle)"),
    action: Optional[str] = Query(None, description="Filtrer par action"),
    resource_type: Optional[str] = Query(None, description="Filtrer par type de ressource"),
    resource_id: Optional[UUID] = Query(None, description="Filtrer par ressource"),
    severity: Optional[str] = Query(None, description="Filtrer par sévérité"),
    ip_address: Optional[str] = Query(None, description="Filtrer par IP"),
    date_from: Optional[datetime] = Query(None, description="Date de début"),
    date_to: Optional[datetime] = Query(None, description="Date de fin"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Liste les logs d'audit avec filtres et pagination.

    Réservé aux administrateurs.
    """
    skip = (page - 1) * page_size

    logs, total = await AuditRepository.get_logs(
        db,
        skip=skip,
        limit=page_size,
        user_id=user_id,
        username=username,
        action_name=action,
        resource_type=resource_type,
        resource_id=resource_id,
        severity=severity,
        ip_address=ip_address,
        date_from=date_from,
        date_to=date_to
    )

    # Transformer en response
    items = []
    for log in logs:
        user_response = None
        if log.user:
            user_response = AuditUserResponse(
                id=log.user.id,
                username=log.user.username,
                email=log.user.email,
                role_name=log.user.role.name if log.user.role else None
            )

        action_response = AuditActionResponse(
            id=log.action.id,
            name=log.action.name,
            display_name=log.action.display_name,
            severity=log.action.severity
        ) if log.action else None

        resource_type_response = None
        if log.resource_type:
            resource_type_response = ResourceTypeResponse(
                id=log.resource_type.id,
                name=log.resource_type.name,
                display_name=log.resource_type.display_name
            )

        items.append(AuditLogResponse(
            id=log.id,
            created_at=log.created_at,
            user_id=log.user_id,
            user=user_response,
            action=action_response,
            resource_type=resource_type_response,
            resource_id=log.resource_id,
            details=log.details,
            ip_address=log.ip_address,
            user_agent=log.user_agent
        ))

    return AuditLogListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/stats", response_model=AuditStatsResponse)
async def get_audit_stats(
    days: int = Query(30, ge=1, le=365, description="Nombre de jours d'historique"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Récupère les statistiques d'audit.

    Inclut :
    - Totaux (aujourd'hui, semaine, mois)
    - Répartition par action
    - Répartition par sévérité
    - Évolution par jour
    - Top 10 utilisateurs actifs
    """
    stats = await AuditRepository.get_stats(db, days=days)
    return AuditStatsResponse(**stats)


@router.get("/export")
async def export_audit_logs(
    format: str = Query("csv", pattern="^(csv|json)$", description="Format d'export"),
    max_rows: int = Query(10000, ge=1, le=100000, description="Nombre max de lignes"),
    user_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Exporte les logs d'audit en CSV ou JSON.

    Limité à 100 000 lignes maximum.
    """
    data = await AuditRepository.get_logs_for_export(
        db,
        max_rows=max_rows,
        user_id=user_id,
        action_name=action,
        resource_type=resource_type,
        severity=severity,
        date_from=date_from,
        date_to=date_to
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format == "json":
        content = json.dumps(data, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=audit_logs_{timestamp}.json"
            }
        )
    else:
        # CSV
        output = io.StringIO()
        if data:
            # Exclure 'details' du CSV (trop complexe)
            fieldnames = [k for k in data[0].keys() if k != "details"]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(data)

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=audit_logs_{timestamp}.csv"
            }
        )


@router.get("/{log_id}", response_model=AuditLogResponse)
async def get_audit_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Récupère un log d'audit par son ID."""
    log = await AuditRepository.get_log_by_id(db, log_id)
    if not log:
        raise not_found(ErrorCode.NOT_FOUND, {"entity": "audit_log"})

    user_response = None
    if log.user:
        user_response = AuditUserResponse(
            id=log.user.id,
            username=log.user.username,
            email=log.user.email,
            role_name=log.user.role.name if log.user.role else None
        )

    action_response = AuditActionResponse(
        id=log.action.id,
        name=log.action.name,
        display_name=log.action.display_name,
        severity=log.action.severity
    ) if log.action else None

    resource_type_response = None
    if log.resource_type:
        resource_type_response = ResourceTypeResponse(
            id=log.resource_type.id,
            name=log.resource_type.name,
            display_name=log.resource_type.display_name
        )

    return AuditLogResponse(
        id=log.id,
        created_at=log.created_at,
        user_id=log.user_id,
        user=user_response,
        action=action_response,
        resource_type=resource_type_response,
        resource_id=log.resource_id,
        details=log.details,
        ip_address=log.ip_address,
        user_agent=log.user_agent
    )


# --- Référentiels ---

@router.get("/actions/list", response_model=list[AuditActionResponse])
async def list_audit_actions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Liste toutes les actions d'audit disponibles."""
    actions = await AuditRepository.get_all_actions(db)
    return [
        AuditActionResponse(
            id=a.id,
            name=a.name,
            display_name=a.display_name,
            severity=a.severity
        )
        for a in actions
    ]


@router.get("/resource-types/list", response_model=list[ResourceTypeResponse])
async def list_resource_types(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Liste tous les types de ressources."""
    types = await AuditRepository.get_all_resource_types(db)
    return [
        ResourceTypeResponse(
            id=t.id,
            name=t.name,
            display_name=t.display_name
        )
        for t in types
    ]


# --- Maintenance ---

from pydantic import BaseModel, Field


class AuditCleanupRequest(BaseModel):
    """Schema pour la purge des logs d'audit"""
    days: int = Field(default=365, ge=0, le=3650, description="Nombre de jours à conserver (0 = tout supprimer)")


@router.delete("/cleanup")
async def cleanup_old_logs(
    cleanup_data: AuditCleanupRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """
    Supprime les logs d'audit plus anciens que X jours.

    Body Parameters:
    - days: Nombre de jours à conserver (défaut: 365, min: 1, max: 3650)

    Réservé aux super-admins.
    """
    # Vérifier que c'est un super-admin (role_id = 1)
    if admin.role_id != 1:
        from app.common.exceptions.http import forbidden
        raise forbidden(ErrorCode.FORBIDDEN, {"reason": "superadmin_required"})

    deleted_count = await AuditRepository.delete_old_logs(db, days=cleanup_data.days)

    logger.info(f"Admin admin_id={admin.id} cleaned up {deleted_count} audit logs older than {cleanup_data.days} days")

    return {
        "success": True,
        "deleted_count": deleted_count,
        "days_retained": cleanup_data.days
    }
