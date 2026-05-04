"""
Router Admin

Endpoints d'administration pour gérer les utilisateurs, rôles, audit, etc.
Tous les endpoints nécessitent le rôle admin.
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.deps import get_current_admin_user, get_db
from app.models import User, UserPreference, Document, Message
from app.common.schemas import (
    UserPreferenceRead,
    MessageRead, DocumentRead, SessionRead
)
from app.features.admin.repository import AdminRepository
from app.features.admin.service import AdminService
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# AUDIT LOGS & STATS
# =============================================================================

@router.get("/audit")
async def get_audit_logs(
    username: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les logs d'audit avec filtres

    Query Parameters:
    - username: Filtrer par username (recherche partielle)
    - action: Filtrer par nom d'action
    - date_from: Date de début (format: YYYY-MM-DD)
    - date_to: Date de fin (format: YYYY-MM-DD)
    - limit: Nombre de résultats (max 200)
    - offset: Pagination

    Requires: Admin role
    """
    try:
        limit = min(limit, 200)

        audit_logs = await AdminRepository.get_audit_logs(
            db, username, action, date_from, date_to, limit, offset
        )

        # Enrichir les données avec joinedload pour l'utilisateur
        logs_data = []
        for log in audit_logs:
            # Recuperer le username si l'utilisateur existe
            username = None
            if log.user:
                username = log.user.username or log.user.email.split("@")[0]

            logs_data.append({
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "username": username,
                "user_role": log.user.role.name if log.user and log.user.role else None,
                "action_id": log.action_id,
                "resource_type_id": log.resource_type_id,
                "resource_id": str(log.resource_id) if log.resource_id else None,
                "details": log.details,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat()
            })

        REQUEST_COUNT.labels(endpoint="/admin/audit", method="GET", status="200").inc()

        return {
            "total": len(logs_data),
            "limit": limit,
            "offset": offset,
            "logs": logs_data
        }

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/audit", method="GET", status="500").inc()
        logger.error(f"Error fetching audit logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_admin_stats(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques globales du système

    Requires: Admin role
    """
    try:
        stats = await AdminService.get_stats(db)

        REQUEST_COUNT.labels(endpoint="/admin/stats", method="GET", status="200").inc()

        return stats

    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/stats", method="GET", status="500").inc()
        logger.error(f"Error fetching admin stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ROUTERS (Roles, ConversationModes, ResourceTypes, AuditActions)
# =============================================================================
# Ces routes sont générées automatiquement via le Generic CRUD Router.
# Voir app/features/admin/crud_routers.py pour la configuration.
# =============================================================================

from app.features.admin.crud_routers import (
    roles_crud_router,
    conversation_modes_crud_router,
    resource_types_crud_router,
    audit_actions_crud_router,
)

router.include_router(roles_crud_router)
router.include_router(conversation_modes_crud_router)
router.include_router(resource_types_crud_router)
router.include_router(audit_actions_crud_router)


# =============================================================================
# USER PREFERENCES
# =============================================================================

@router.get("/user-preferences/{user_id}", response_model=UserPreferenceRead)
async def get_user_preferences(
    user_id: uuid.UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère les préférences d'un utilisateur"""
    try:
        preferences = await AdminRepository.get_by_id(db, UserPreference, user_id)
        if not preferences:
            raise HTTPException(status_code=404, detail="User preferences not found")

        REQUEST_COUNT.labels(endpoint="/admin/user-preferences", method="GET", status="200").inc()
        return preferences
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/user-preferences", method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MESSAGES, DOCUMENTS, SESSIONS
# =============================================================================
# Note: L'endpoint GET /conversations est desormais dans conversations_admin_router
# qui supporte tous les filtres (search, user_id, mode_id, etc.)

@router.get("/messages", response_model=list[MessageRead])
async def get_messages(
    conversation_id: Optional[uuid.UUID] = None,
    sender_type: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère tous les messages avec filtres.

    Query Parameters:
    - conversation_id: Filtrer par conversation
    - sender_type: Filtrer par type (user/assistant)
    - include_deleted: Inclure les messages supprimés (soft delete)
    - limit: Nombre de résultats (max 200)
    - offset: Pagination
    """
    try:
        limit = min(limit, 200)
        messages = await AdminRepository.get_messages(
            db, conversation_id, sender_type,
            include_deleted=include_deleted,
            limit=limit, offset=offset
        )

        REQUEST_COUNT.labels(endpoint="/admin/messages", method="GET", status="200").inc()
        return messages
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/messages", method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/deleted", response_model=list[MessageRead])
async def get_deleted_messages(
    conversation_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère uniquement les messages supprimés (soft delete).

    Query Parameters:
    - conversation_id: Filtrer par conversation
    - limit: Nombre de résultats (max 200)
    - offset: Pagination
    """
    try:
        limit = min(limit, 200)
        messages = await AdminRepository.get_messages(
            db, conversation_id, sender_type=None,
            deleted_only=True,
            limit=limit, offset=offset
        )

        REQUEST_COUNT.labels(endpoint="/admin/messages/deleted", method="GET", status="200").inc()
        return messages
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/messages/deleted", method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages/{message_id}", status_code=204)
async def hard_delete_message(
    message_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime physiquement un message (hard delete).

    Cette action est irréversible. Seuls les admins peuvent effectuer cette opération.
    """
    try:
        message = await AdminRepository.get_by_id(db, Message, message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        message_info = {
            'conversation_id': str(message.conversation_id),
            'sender_type': message.sender_type,
            'content_preview': message.content[:100] if message.content else None,
            'was_soft_deleted': message.deleted_at is not None
        }

        deleted = await AdminRepository.hard_delete_message(db, message_id)
        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete message")

        await AuditService.log_action(
            db=db,
            action_name='message_hard_deleted',
            user_id=admin_user.id,
            resource_type_name='message',
            resource_id=message_id,
            details=message_info,
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/messages", method="DELETE", status="204").inc()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/messages", method="DELETE", status="500").inc()
        logger.error(f"Error hard deleting message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/restore", response_model=MessageRead)
async def restore_message(
    message_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Restaure un message supprimé (soft delete).

    Annule le soft delete d'un message.
    """
    try:
        message = await AdminRepository.restore_message(db, message_id)

        if not message:
            raise HTTPException(
                status_code=404,
                detail="Message not found or not deleted"
            )

        await AuditService.log_action(
            db=db,
            action_name='message_restored',
            user_id=admin_user.id,
            resource_type_name='message',
            resource_id=message_id,
            details={'conversation_id': str(message.conversation_id)},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/messages/restore", method="POST", status="200").inc()
        return message
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/messages/restore", method="POST", status="500").inc()
        logger.error(f"Error restoring message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents", response_model=list[DocumentRead])
async def get_documents(
    user_id: Optional[uuid.UUID] = None,
    file_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère tous les documents avec filtres"""
    try:
        limit = min(limit, 200)
        documents = await AdminRepository.get_documents(db, user_id, file_type, limit, offset)

        REQUEST_COUNT.labels(endpoint="/admin/documents", method="GET", status="200").inc()
        return documents
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/documents", method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Supprime un document (aussi dans ChromaDB si possible)"""
    try:
        document = await AdminRepository.get_by_id(db, Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        document_info = {
            'filename': document.filename,
            'file_hash': document.file_hash,
            'user_id': str(document.user_id)
        }

        await AdminService.delete_document(db, document_id)

        await AuditService.log_action(
            db=db,
            action_name='document_deleted',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=document_id,
            details=document_info,
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/documents", method="DELETE", status="204").inc()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/documents", method="DELETE", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/deindex", response_model=DocumentRead)
async def deindex_document(
    document_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Désindexe un document du RAG

    Le document reste dans la base mais n'apparaîtra plus dans les recherches RAG.
    Requires: Admin role
    """
    try:
        document = await AdminService.deindex_document(db, document_id)

        await AuditService.log_action(
            db=db,
            action_name='document_deindexed',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=document_id,
            details={
                'filename': document.filename,
                'file_hash': document.file_hash
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/documents/deindex", method="POST", status="200").inc()
        return document
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/documents/deindex", method="POST", status="500").inc()
        logger.error(f"Error deindexing document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/reindex", response_model=DocumentRead)
async def reindex_document(
    document_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Réindexe un document dans le RAG

    Le document sera à nouveau visible dans les recherches RAG.
    Requires: Admin role
    """
    try:
        document = await AdminService.reindex_document(db, document_id)

        await AuditService.log_action(
            db=db,
            action_name='document_reindexed',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=document_id,
            details={
                'filename': document.filename,
                'file_hash': document.file_hash
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/documents/reindex", method="POST", status="200").inc()
        return document
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/documents/reindex", method="POST", status="500").inc()
        logger.error(f"Error reindexing document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/documents/{document_id}/visibility")
async def update_document_visibility_admin(
    document_id: uuid.UUID,
    visibility: str,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la visibilité d'un document (admin)

    Args:
        visibility: 'public' ou 'private'

    Requires: Admin role
    """
    try:
        document = await AdminService.update_document_visibility(
            db=db,
            document_id=document_id,
            visibility=visibility,
            user_id=admin_user.id,
            is_admin=True
        )

        await AuditService.log_action(
            db=db,
            action_name='document_visibility_updated',
            user_id=admin_user.id,
            resource_type_name='document',
            resource_id=document_id,
            details={
                'filename': document.filename,
                'new_visibility': visibility
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/documents/visibility", method="PATCH", status="200").inc()
        return {
            "success": True,
            "document_id": str(document_id),
            "visibility": visibility
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/documents/visibility", method="PATCH", status="500").inc()
        logger.error(f"Error updating document visibility: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=list[SessionRead])
async def get_sessions(
    user_id: Optional[uuid.UUID] = None,
    active_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère toutes les sessions avec filtres"""
    try:
        limit = min(limit, 200)
        sessions = await AdminRepository.get_sessions(db, user_id, active_only, limit, offset)

        REQUEST_COUNT.labels(endpoint="/admin/sessions", method="GET", status="200").inc()
        return sessions
    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/admin/sessions", method="GET", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/user/{user_id}", status_code=204)
async def revoke_all_user_sessions(
    user_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Révoque toutes les sessions d'un utilisateur"""
    try:
        user = await AdminRepository.get_by_id(db, User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        count = await AdminRepository.revoke_all_user_sessions(db, user_id)

        await AuditService.log_action(
            db=db,
            action_name='all_sessions_revoked',
            user_id=admin_user.id,
            resource_type_name='session',
            resource_id=user_id,
            details={'target_user_id': str(user_id), 'sessions_revoked': count},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(endpoint="/admin/sessions", method="DELETE", status="204").inc()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(endpoint="/admin/sessions", method="DELETE", status="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# INCLUSION DES SUB-ROUTERS
# =============================================================================

from app.features.admin.users.router import router as users_router
from app.features.admin.dashboard.router import router as dashboard_router
from app.features.admin.bulk.router import router as bulk_router
from app.features.admin.export.router import router as export_router
from app.features.admin.conversations.router import router as conversations_admin_router
from app.features.admin.config.router import router as config_router
from app.features.admin.password_policy.router import router as password_policy_router
from app.features.admin.geo.router import router as geo_admin_router
# Note: corpus_router et permissions_router sont inclus directement dans main.py
# car ils ont leur propre préfixe /api/admin/...

router.include_router(users_router, prefix="/users", tags=["Admin - Users"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["Admin - Dashboard"])
router.include_router(bulk_router, prefix="/bulk", tags=["Admin - Bulk"])
router.include_router(export_router, prefix="/export", tags=["Admin - Export"])
router.include_router(conversations_admin_router, prefix="/conversations", tags=["Admin - Conversations"])
router.include_router(config_router, prefix="/config", tags=["Admin - Config"])
router.include_router(password_policy_router, prefix="/password-policies", tags=["Admin - Password Policies"])
router.include_router(geo_admin_router, prefix="/geo", tags=["Admin - Geo"])
