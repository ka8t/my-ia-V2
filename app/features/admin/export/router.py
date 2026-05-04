"""
Router Admin Export

Endpoints pour l'export de données.
Tous les endpoints nécessitent le rôle admin.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.export.service import ExportService
from app.features.admin.export.schemas import ExportFormat
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


def _create_export_response(
    content: str,
    filename: str,
    export_format: ExportFormat
) -> Response:
    """Crée une réponse HTTP avec le contenu exporté."""
    if export_format == ExportFormat.CSV:
        media_type = "text/csv"
        filename = f"{filename}.csv"
    else:
        media_type = "application/json"
        filename = f"{filename}.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


# =============================================================================
# EXPORT UTILISATEURS
# =============================================================================

@router.get("/users")
async def export_users(
    format: ExportFormat = ExportFormat.CSV,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 1000,
    request: Request = None,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte les utilisateurs en CSV ou JSON.

    Query Parameters:
    - format: Format d'export (csv ou json, défaut: csv)
    - created_after: Filtrer par date de création (après)
    - created_before: Filtrer par date de création (avant)
    - limit: Nombre max d'enregistrements (défaut: 1000, max: 10000)

    Requires: Admin role
    """
    try:
        limit = min(limit, 10000)

        data = await ExportService.export_users(
            db=db,
            created_after=created_after,
            created_before=created_before,
            limit=limit
        )

        if format == ExportFormat.CSV:
            content = ExportService.to_csv(data)
        else:
            content = ExportService.to_json(data)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='data_exported',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'export_type': 'users',
                'format': format.value,
                'records_count': len(data)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/export/users", method="GET", status="200"
        ).inc()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return _create_export_response(content, f"users_{timestamp}", format)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/export/users", method="GET", status="500"
        ).inc()
        logger.error(f"Error exporting users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXPORT CONVERSATIONS
# =============================================================================

@router.get("/conversations")
async def export_conversations(
    format: ExportFormat = ExportFormat.CSV,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 1000,
    request: Request = None,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte les conversations en CSV ou JSON.

    Query Parameters:
    - format: Format d'export (csv ou json, défaut: csv)
    - created_after: Filtrer par date de création (après)
    - created_before: Filtrer par date de création (avant)
    - limit: Nombre max d'enregistrements (défaut: 1000, max: 10000)

    Requires: Admin role
    """
    try:
        limit = min(limit, 10000)

        data = await ExportService.export_conversations(
            db=db,
            created_after=created_after,
            created_before=created_before,
            limit=limit
        )

        if format == ExportFormat.CSV:
            content = ExportService.to_csv(data)
        else:
            content = ExportService.to_json(data)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='data_exported',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=None,
            details={
                'export_type': 'conversations',
                'format': format.value,
                'records_count': len(data)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/export/conversations", method="GET", status="200"
        ).inc()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return _create_export_response(content, f"conversations_{timestamp}", format)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/export/conversations", method="GET", status="500"
        ).inc()
        logger.error(f"Error exporting conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXPORT DOCUMENTS
# =============================================================================

@router.get("/documents")
async def export_documents(
    format: ExportFormat = ExportFormat.CSV,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 1000,
    request: Request = None,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte les métadonnées des documents en CSV ou JSON.

    Query Parameters:
    - format: Format d'export (csv ou json, défaut: csv)
    - created_after: Filtrer par date de création (après)
    - created_before: Filtrer par date de création (avant)
    - limit: Nombre max d'enregistrements (défaut: 1000, max: 10000)

    Requires: Admin role
    """
    try:
        limit = min(limit, 10000)

        data = await ExportService.export_documents(
            db=db,
            created_after=created_after,
            created_before=created_before,
            limit=limit
        )

        if format == ExportFormat.CSV:
            content = ExportService.to_csv(data)
        else:
            content = ExportService.to_json(data)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='data_exported',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=None,
            details={
                'export_type': 'documents',
                'format': format.value,
                'records_count': len(data)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/export/documents", method="GET", status="200"
        ).inc()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return _create_export_response(content, f"documents_{timestamp}", format)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/export/documents", method="GET", status="500"
        ).inc()
        logger.error(f"Error exporting documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXPORT AUDIT LOGS
# =============================================================================

@router.get("/audit-logs")
async def export_audit_logs(
    format: ExportFormat = ExportFormat.CSV,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 1000,
    request: Request = None,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte les logs d'audit en CSV ou JSON.

    Query Parameters:
    - format: Format d'export (csv ou json, défaut: csv)
    - created_after: Filtrer par date de création (après)
    - created_before: Filtrer par date de création (avant)
    - limit: Nombre max d'enregistrements (défaut: 1000, max: 10000)

    Requires: Admin role
    """
    try:
        limit = min(limit, 10000)

        data = await ExportService.export_audit_logs(
            db=db,
            created_after=created_after,
            created_before=created_before,
            limit=limit
        )

        if format == ExportFormat.CSV:
            content = ExportService.to_csv(data)
        else:
            content = ExportService.to_json(data)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='data_exported',
            user_id=admin_user.id,
            resource_type_name='audit_log',
            resource_id=None,
            details={
                'export_type': 'audit_logs',
                'format': format.value,
                'records_count': len(data)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/export/audit-logs", method="GET", status="200"
        ).inc()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return _create_export_response(content, f"audit_logs_{timestamp}", format)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/export/audit-logs", method="GET", status="500"
        ).inc()
        logger.error(f"Error exporting audit logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
