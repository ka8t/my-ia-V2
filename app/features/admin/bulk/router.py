"""
Router Admin Bulk

Endpoints pour les opérations en masse.
Tous les endpoints nécessitent le rôle admin.
"""
import logging

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.bulk.service import BulkService
from app.features.admin.bulk.schemas import (
    BulkUserIds, BulkRoleChange, BulkDeleteRequest, BulkOperationResult,
    BulkFilteredRequest, BulkFilteredRoleChange, BulkPreflightResponse, BulkUserFilters
)
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# UTILISATEURS
# =============================================================================

@router.post("/users/activate", response_model=BulkOperationResult)
async def bulk_activate_users(
    data: BulkUserIds,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Active plusieurs utilisateurs en masse.

    Body:
    - user_ids: Liste des IDs utilisateurs (max 100)

    Requires: Admin role
    """
    try:
        result = await BulkService.activate_users(
            db=db,
            user_ids=data.user_ids,
            admin_user_id=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_users_activated',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'user_ids_count': len(data.user_ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/activate", method="POST", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/activate", method="POST", status="500"
        ).inc()
        logger.error(f"Error bulk activating users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/deactivate", response_model=BulkOperationResult)
async def bulk_deactivate_users(
    data: BulkUserIds,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Désactive plusieurs utilisateurs en masse.

    Body:
    - user_ids: Liste des IDs utilisateurs (max 100)

    Restrictions:
    - Ne peut pas désactiver son propre compte

    Requires: Admin role
    """
    try:
        result = await BulkService.deactivate_users(
            db=db,
            user_ids=data.user_ids,
            admin_user_id=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_users_deactivated',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'user_ids_count': len(data.user_ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/deactivate", method="POST", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/deactivate", method="POST", status="500"
        ).inc()
        logger.error(f"Error bulk deactivating users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/role", response_model=BulkOperationResult)
async def bulk_change_users_role(
    data: BulkRoleChange,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Change le rôle de plusieurs utilisateurs en masse.

    Body:
    - user_ids: Liste des IDs utilisateurs (max 100)
    - new_role_id: Nouveau rôle ID
    - reason: Raison du changement (optionnel)

    Restrictions:
    - Ne peut pas rétrograder son propre compte

    Requires: Admin role
    """
    try:
        result = await BulkService.change_users_role(
            db=db,
            user_ids=data.user_ids,
            new_role_id=data.new_role_id,
            admin_user_id=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_users_role_changed',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'user_ids_count': len(data.user_ids),
                'new_role_id': data.new_role_id,
                'reason': data.reason,
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/role", method="POST", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users/role", method="POST", status="500"
        ).inc()
        logger.error(f"Error bulk changing users role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users", response_model=BulkOperationResult)
async def bulk_delete_users(
    data: BulkDeleteRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime plusieurs utilisateurs en masse.

    Body:
    - ids: Liste des IDs utilisateurs (max 100)
    - confirm: Doit être true pour confirmer la suppression

    Restrictions:
    - Ne peut pas supprimer son propre compte
    - confirm doit être true

    Requires: Admin role
    """
    try:
        result = await BulkService.delete_users(
            db=db,
            user_ids=data.ids,
            admin_user_id=admin_user.id,
            confirm=data.confirm
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_users_deleted',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'user_ids_count': len(data.ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users", method="DELETE", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/users", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error bulk deleting users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONVERSATIONS
# =============================================================================

@router.delete("/conversations", response_model=BulkOperationResult)
async def bulk_delete_conversations(
    data: BulkDeleteRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime plusieurs conversations en masse.

    Body:
    - ids: Liste des IDs conversations (max 100)
    - confirm: Doit être true pour confirmer la suppression

    Requires: Admin role
    """
    try:
        result = await BulkService.delete_conversations(
            db=db,
            conversation_ids=data.ids,
            confirm=data.confirm
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_conversations_deleted',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=None,
            details={
                'conversation_ids_count': len(data.ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/conversations", method="DELETE", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/conversations", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error bulk deleting conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DOCUMENTS
# =============================================================================

@router.delete("/documents", response_model=BulkOperationResult)
async def bulk_delete_documents(
    data: BulkDeleteRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime plusieurs documents en masse (DB + ChromaDB).

    Body:
    - ids: Liste des IDs documents (max 100)
    - confirm: Doit être true pour confirmer la suppression

    Requires: Admin role
    """
    try:
        result = await BulkService.delete_documents(
            db=db,
            document_ids=data.ids,
            confirm=data.confirm
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_documents_deleted',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=None,
            details={
                'document_ids_count': len(data.ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/documents", method="DELETE", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/documents", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error bulk deleting documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SESSIONS
# =============================================================================

@router.delete("/sessions", response_model=BulkOperationResult)
async def bulk_revoke_sessions(
    data: BulkDeleteRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Révoque plusieurs sessions en masse.

    Body:
    - ids: Liste des IDs sessions (max 100)
    - confirm: Doit être true pour confirmer la révocation

    Requires: Admin role
    """
    try:
        result = await BulkService.revoke_sessions(
            db=db,
            session_ids=data.ids,
            confirm=data.confirm
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='bulk_sessions_revoked',
            user_id=admin_user.id,
            resource_type_name='session',
            resource_id=None,
            details={
                'session_ids_count': len(data.ids),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/sessions", method="DELETE", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/bulk/sessions", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error bulk revoking sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UTILISATEURS - OPÉRATIONS FILTRÉES
# =============================================================================

@router.post("/users/filtered/preflight", response_model=BulkPreflightResponse)
async def preflight_filtered_users(
    filters: BulkUserFilters,
    check_admins: bool = True,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Vérifie les utilisateurs qui seront impactés par une opération bulk filtrée.

    Query params:
    - check_admins: Vérifier la présence d'admins (défaut: true)

    Body:
    - filters: Filtres à appliquer (role_id, is_active, is_verified, search)

    Returns:
    - total_count: Nombre d'utilisateurs impactés
    - admin_count: Nombre d'admins détectés
    - admins: Liste des admins (si bloquant)
    - can_proceed: True si l'opération peut continuer
    - warning_message: Message d'avertissement

    Requires: Admin role
    """
    return await BulkService.preflight_filtered_users(
        db=db,
        filters=filters,
        check_admins=check_admins,
        admin_user_id=admin_user.id
    )


@router.post("/users/filtered/activate", response_model=BulkOperationResult)
async def bulk_activate_users_filtered(
    data: BulkFilteredRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Active tous les utilisateurs correspondant aux filtres.

    Body:
    - filters: Filtres (role_id, is_active, is_verified, search)
    - confirm: Confirmation obligatoire

    Requires: Admin role
    """
    if not data.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    try:
        result = await BulkService.activate_users_filtered(
            db=db,
            filters=data.filters,
            admin_user_id=admin_user.id
        )

        await AuditService.log_action(
            db=db,
            action_name='bulk_users_activated_filtered',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'filters': data.filters.model_dump(),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error bulk activating users (filtered): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/filtered/deactivate", response_model=BulkOperationResult)
async def bulk_deactivate_users_filtered(
    data: BulkFilteredRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Désactive tous les utilisateurs correspondant aux filtres.
    BLOQUÉ si des admins sont présents dans les résultats.

    Body:
    - filters: Filtres (role_id, is_active, is_verified, search)
    - confirm: Confirmation obligatoire

    Requires: Admin role
    """
    if not data.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    try:
        result = await BulkService.deactivate_users_filtered(
            db=db,
            filters=data.filters,
            admin_user_id=admin_user.id
        )

        await AuditService.log_action(
            db=db,
            action_name='bulk_users_deactivated_filtered',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'filters': data.filters.model_dump(),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error bulk deactivating users (filtered): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/filtered/role", response_model=BulkOperationResult)
async def bulk_change_users_role_filtered(
    data: BulkFilteredRoleChange,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Change le rôle de tous les utilisateurs correspondant aux filtres.
    BLOQUÉ si des admins sont présents dans les résultats.

    Body:
    - filters: Filtres (role_id, is_active, is_verified, search)
    - new_role_id: Nouveau rôle ID
    - confirm: Confirmation obligatoire

    Requires: Admin role
    """
    if not data.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    try:
        result = await BulkService.change_users_role_filtered(
            db=db,
            filters=data.filters,
            new_role_id=data.new_role_id,
            admin_user_id=admin_user.id
        )

        await AuditService.log_action(
            db=db,
            action_name='bulk_users_role_changed_filtered',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'filters': data.filters.model_dump(),
                'new_role_id': data.new_role_id,
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error bulk changing users role (filtered): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/filtered", response_model=BulkOperationResult)
async def bulk_delete_users_filtered(
    data: BulkFilteredRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime tous les utilisateurs correspondant aux filtres.
    BLOQUÉ si des admins sont présents dans les résultats.

    Body:
    - filters: Filtres (role_id, is_active, is_verified, search)
    - confirm: Confirmation obligatoire (doit être true)

    Requires: Admin role
    """
    try:
        result = await BulkService.delete_users_filtered(
            db=db,
            filters=data.filters,
            admin_user_id=admin_user.id,
            confirm=data.confirm
        )

        await AuditService.log_action(
            db=db,
            action_name='bulk_users_deleted_filtered',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=None,
            details={
                'filters': data.filters.model_dump(),
                'success_count': result.success_count,
                'failed_count': result.failed_count
            },
            request=request,
            username=admin_user.username
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error bulk deleting users (filtered): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
