"""
Router Admin Conversations

Endpoints pour la gestion avancée des conversations.
Tous les endpoints nécessitent le rôle admin.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.conversations.service import ConversationAdminService
from app.features.admin.conversations.schemas import (
    ConversationDetailRead, ConversationListItem,
    ConversationUpdateAdmin,
    BulkConversationRequest, BulkConversationResponse
)
from app.features.admin.schemas import PaginatedResponse
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# LIST & GET
# =============================================================================

@router.get("", response_model=PaginatedResponse[ConversationListItem])
async def list_conversations(
    user_id: Optional[uuid.UUID] = None,
    mode_id: Optional[int] = None,
    search: Optional[str] = None,
    archived: Optional[bool] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les conversations avec filtres et pagination.

    Query Parameters:
    - user_id: Filtrer par utilisateur
    - mode_id: Filtrer par mode de conversation
    - search: Recherche dans le titre
    - archived: Filtrer par statut (true=archivées, false=actives, absent=toutes)
    - created_after: Filtrer par date de création (après)
    - created_before: Filtrer par date de création (avant)
    - limit: Nombre max de résultats (1-200, défaut: 50)
    - offset: Décalage pour pagination

    Requires: Admin role
    """
    try:
        limit = min(limit, 200)

        conversations, total = await ConversationAdminService.get_conversations(
            db=db,
            user_id=user_id,
            mode_id=mode_id,
            search=search,
            archived=archived,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations", method="GET", status="200"
        ).inc()

        return PaginatedResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=conversations
        )

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# BULK OPERATIONS - AVANT les routes avec {conversation_id}
# =============================================================================

@router.post("/bulk/archive", response_model=BulkConversationResponse)
async def bulk_archive_conversations(
    body: BulkConversationRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Archive plusieurs conversations en masse.

    Requires: Admin role
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.conversation_ids:
        raise HTTPException(
            status_code=400,
            detail="Aucune conversation sélectionnée"
        )

    logger.info(f"Bulk archive: {len(body.conversation_ids)} conversations par admin_id={admin_user.id}")

    result = await ConversationAdminService.bulk_archive_conversations(
        db, body.conversation_ids
    )

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='conversations_bulk_archived',
        user_id=admin_user.id,
        resource_type_name='conversation',
        details={
            'count': len(body.conversation_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request,
        username=admin_user.username
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/conversations/bulk/archive", method="POST", status="200"
    ).inc()

    return BulkConversationResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} conversation(s) archivée(s)"
    )


@router.post("/bulk/delete", response_model=BulkConversationResponse)
async def bulk_delete_conversations(
    body: BulkConversationRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime plusieurs conversations en masse.

    Requires: Admin role
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.conversation_ids:
        raise HTTPException(
            status_code=400,
            detail="Aucune conversation sélectionnée"
        )

    logger.info(f"Bulk delete: {len(body.conversation_ids)} conversations par admin_id={admin_user.id}")

    result = await ConversationAdminService.bulk_delete_conversations(
        db, body.conversation_ids
    )

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='conversations_bulk_deleted',
        user_id=admin_user.id,
        resource_type_name='conversation',
        details={
            'count': len(body.conversation_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request,
        username=admin_user.username
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/conversations/bulk/delete", method="POST", status="200"
    ).inc()

    return BulkConversationResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} conversation(s) supprimée(s)"
    )


@router.post("/bulk/unarchive", response_model=BulkConversationResponse)
async def bulk_unarchive_conversations(
    body: BulkConversationRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Desarchive plusieurs conversations en masse.

    Requires: Admin role
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.conversation_ids:
        raise HTTPException(
            status_code=400,
            detail="Aucune conversation sélectionnée"
        )

    logger.info(f"Bulk unarchive: {len(body.conversation_ids)} conversations par admin_id={admin_user.id}")

    result = await ConversationAdminService.bulk_unarchive_conversations(
        db, body.conversation_ids
    )

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='conversations_bulk_unarchived',
        user_id=admin_user.id,
        resource_type_name='conversation',
        details={
            'count': len(body.conversation_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request,
        username=admin_user.username
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/conversations/bulk/unarchive", method="POST", status="200"
    ).inc()

    return BulkConversationResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} conversation(s) restaurée(s)"
    )


@router.post("/bulk/export")
async def bulk_export_conversations(
    body: BulkConversationRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte plusieurs conversations en masse (JSON).

    Requires: Admin role
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.conversation_ids:
        raise HTTPException(
            status_code=400,
            detail="Aucune conversation sélectionnée"
        )

    logger.info(f"Bulk export: {len(body.conversation_ids)} conversations par admin_id={admin_user.id}")

    result = await ConversationAdminService.bulk_export_conversations(
        db, body.conversation_ids
    )

    # Audit log
    await AuditService.log_action(
        db=db,
        action_name='conversations_bulk_exported',
        user_id=admin_user.id,
        resource_type_name='conversation',
        details={
            'count': len(body.conversation_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request,
        username=admin_user.username
    )

    REQUEST_COUNT.labels(
        endpoint="/admin/conversations/bulk/export", method="POST", status="200"
    ).inc()

    # Retourner le JSON comme fichier downloadable
    import json
    content = json.dumps(result, indent=2, ensure_ascii=False)

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="conversations_export_{len(result["conversations"])}.json"'
        }
    )


# =============================================================================
# GET BY ID
# =============================================================================

@router.get("/{conversation_id}", response_model=ConversationDetailRead)
async def get_conversation(
    conversation_id: uuid.UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les détails d'une conversation avec ses messages.

    Path Parameters:
    - conversation_id: UUID de la conversation

    Requires: Admin role
    """
    try:
        conversation = await ConversationAdminService.get_conversation_detail(
            db, conversation_id
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="GET", status="200"
        ).inc()

        return conversation

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPDATE
# =============================================================================

@router.patch("/{conversation_id}", response_model=ConversationListItem)
async def update_conversation(
    conversation_id: uuid.UUID,
    data: ConversationUpdateAdmin,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour une conversation (titre).

    Path Parameters:
    - conversation_id: UUID de la conversation

    Body:
    - title: Nouveau titre (optionnel)

    Requires: Admin role
    """
    try:
        result = await ConversationAdminService.update_conversation(
            db, conversation_id, title=data.title
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='conversation_updated',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={
                'conversation_id': str(conversation_id),
                'new_title': data.title
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="PATCH", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DELETE
# =============================================================================

@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime une conversation et ses messages.

    Path Parameters:
    - conversation_id: UUID de la conversation

    Requires: Admin role
    """
    try:
        # Récupérer les infos pour l'audit
        detail = await ConversationAdminService.get_conversation_detail(
            db, conversation_id
        )

        await ConversationAdminService.delete_conversation(db, conversation_id)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='conversation_deleted',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={
                'deleted_conversation_id': str(conversation_id),
                'owner_user_id': str(detail['user_id']),
                'messages_count': detail['messages_count']
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="DELETE", status="204"
        ).inc()

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/user/{user_id}", status_code=204)
async def delete_user_conversations(
    user_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime toutes les conversations d'un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Requires: Admin role
    """
    try:
        count = await ConversationAdminService.delete_user_conversations(db, user_id)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='user_conversations_deleted',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'conversations_deleted': count
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/user/{id}", method="DELETE", status="204"
        ).inc()

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/user/{id}", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting user conversations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXPORT
# =============================================================================

@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporte une conversation complète en JSON.

    Path Parameters:
    - conversation_id: UUID de la conversation

    Requires: Admin role
    """
    try:
        content = await ConversationAdminService.export_conversation(
            db, conversation_id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='conversation_exported',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={'conversation_id': str(conversation_id)},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/export", method="GET", status="200"
        ).inc()

        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="conversation_{conversation_id}.json"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/export", method="GET", status="500"
        ).inc()
        logger.error(f"Error exporting conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ARCHIVAGE
# =============================================================================

@router.post("/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Archive une conversation (admin peut archiver n'importe quelle conversation).

    Path Parameters:
    - conversation_id: UUID de la conversation

    Requires: Admin role
    """
    try:
        result = await ConversationAdminService.archive_conversation(
            db, conversation_id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='conversation_archived',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={
                'conversation_id': str(conversation_id),
                'owner_user_id': str(result['user_id'])
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/archive", method="POST", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/archive", method="POST", status="500"
        ).inc()
        logger.error(f"Error archiving conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{conversation_id}/unarchive")
async def unarchive_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Désarchive une conversation (admin peut désarchiver n'importe quelle conversation).

    Path Parameters:
    - conversation_id: UUID de la conversation

    Requires: Admin role
    """
    try:
        result = await ConversationAdminService.unarchive_conversation(
            db, conversation_id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='conversation_unarchived',
            user_id=admin_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={
                'conversation_id': str(conversation_id),
                'owner_user_id': str(result['user_id'])
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/unarchive", method="POST", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/conversations/{id}/unarchive", method="POST", status="500"
        ).inc()
        logger.error(f"Error unarchiving conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
