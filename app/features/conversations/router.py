"""
Router Conversations

Endpoints pour la gestion des conversations utilisateur.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ErrorCode, not_found
from app.db import get_async_session
from app.models import User
from app.features.auth.service import current_active_user
from app.features.conversations.service import ConversationService
from app.features.audit.service import AuditService
from app.features.conversations.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationRead,
    ConversationDetail,
    ConversationListResponse,
    MessageCreate,
    MessageRead,
    ChatRequest,
    ChatResponse,
    MessageDeleteRequest,
    MessageDeleteResponse
)

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"]
)


import logging
logger = logging.getLogger(__name__)

# Mapping role_id -> role_name (évite de charger la relation)
ROLE_NAMES = {1: 'admin', 2: 'user', 3: 'contributor', 4: 'validator'}

def get_role_name(role_id: int) -> str:
    """Retourne le nom du rôle depuis son ID."""
    return ROLE_NAMES.get(role_id, 'unknown')


@router.get(
    "/test-auth",
    summary="Test auth endpoint"
)
async def test_auth(
    current_user: User = Depends(current_active_user)
):
    """Test endpoint pour debug auth"""
    return {"user_id": str(current_user.id), "email": current_user.email}


@router.get(
    "/",
    response_model=ConversationListResponse,
    summary="Lister mes conversations",
    description="Récupère la liste des conversations de l'utilisateur connecté."
)
async def list_conversations(
    limit: int = Query(50, ge=1, le=100, description="Nombre max de résultats"),
    offset: int = Query(0, ge=0, description="Décalage pour pagination"),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationListResponse:
    logger.info(f"list_conversations called - user_id={current_user.id}")
    """
    Liste les conversations de l'utilisateur authentifié.

    - **limit**: Nombre maximum de conversations (1-100)
    - **offset**: Décalage pour la pagination
    """
    items, total = await ConversationService.list_conversations(
        db, current_user.id, limit, offset
    )

    return ConversationListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une conversation",
    description="Crée une nouvelle conversation pour l'utilisateur connecté."
)
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationRead:
    """
    Crée une nouvelle conversation.

    - **title**: Titre de la conversation
    - **collection_id**: ID de la collection ChromaDB cible
    - **mode_id**: ID du mode (1=chatbot, 2=assistant)
    """
    return await ConversationService.create_conversation(
        db, current_user.id, data
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Récupérer une conversation",
    description="Récupère une conversation avec tous ses messages."
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationDetail:
    """
    Récupère une conversation par son ID.

    Retourne la conversation avec la liste complète des messages.
    """
    conversation = await ConversationService.get_conversation(
        db, conversation_id, current_user.id
    )

    if not conversation:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    return conversation


@router.patch(
    "/{conversation_id}",
    response_model=ConversationRead,
    summary="Modifier une conversation",
    description="Met à jour le titre d'une conversation."
)
async def update_conversation(
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationRead:
    """
    Met à jour une conversation.

    - **title**: Nouveau titre (optionnel)
    """
    conversation = await ConversationService.update_conversation(
        db, conversation_id, current_user.id, data
    )

    if not conversation:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit
    try:
        await AuditService.log_action(
            db=db,
            action_name='conversation_updated',
            user_id=current_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            details={'title': data.title},
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging conversation update: {e}")

    return conversation


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une conversation",
    description="Supprime une conversation et tous ses messages."
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> None:
    """
    Supprime une conversation.

    Cette action est irréversible. Tous les messages seront supprimés.
    """
    deleted = await ConversationService.delete_conversation(
        db, conversation_id, current_user.id
    )

    if not deleted:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit
    try:
        await AuditService.log_action(
            db=db,
            action_name='conversation_deleted',
            user_id=current_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging conversation deletion: {e}")


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un message",
    description="Ajoute un message à une conversation existante."
)
async def add_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> MessageRead:
    """
    Ajoute un message à une conversation.

    - **sender_type**: 'user' ou 'assistant'
    - **content**: Contenu du message
    - **sources**: Sources RAG (optionnel)
    """
    message = await ConversationService.add_message(
        db, conversation_id, current_user.id, data
    )

    if not message:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit (seulement pour les messages utilisateur)
    if data.sender_type == 'user':
        try:
            # Extrait du début du message (max 100 caractères)
            content_preview = data.content[:100] + '...' if len(data.content) > 100 else data.content
            await AuditService.log_action(
                db=db,
                action_name='message_created',
                user_id=current_user.id,
                resource_type_name='message',
                resource_id=message.id,
                details={
                    'conversation_id': str(conversation_id),
                    'content_preview': content_preview
                },
                request=request,
                user_role=get_role_name(current_user.role_id)
            )
        except Exception as e:
            logger.error(f"Error logging message creation: {e}")

    return message


@router.post(
    "/{conversation_id}/chat",
    response_model=ChatResponse,
    summary="Chat dans une conversation",
    description="Envoie un message, génère une réponse RAG et sauvegarde les deux."
)
async def chat_in_conversation(
    conversation_id: uuid.UUID,
    data: ChatRequest,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ChatResponse:
    """
    Chat avec sauvegarde automatique dans la conversation.

    - Sauvegarde le message utilisateur
    - Génère une réponse avec RAG selon le mode de la conversation
    - Sauvegarde la réponse assistant
    - Retourne les deux messages sauvegardés
    """
    result = await ConversationService.chat_and_save(
        db, conversation_id, current_user.id, data.query
    )

    if not result:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit du message utilisateur
    try:
        content_preview = data.query[:100] + '...' if len(data.query) > 100 else data.query
        await AuditService.log_action(
            db=db,
            action_name='message_created',
            user_id=current_user.id,
            resource_type_name='message',
            resource_id=result.user_message.id if result.user_message else None,
            details={
                'conversation_id': str(conversation_id),
                'content_preview': content_preview
            },
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging chat message: {e}")

    return result


@router.delete(
    "/{conversation_id}/messages",
    response_model=MessageDeleteResponse,
    summary="Supprimer des messages",
    description="Marque des messages comme supprimés (soft delete). Les messages restent accessibles à l'admin."
)
async def delete_messages(
    conversation_id: uuid.UUID,
    data: MessageDeleteRequest,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> MessageDeleteResponse:
    """
    Supprime des messages d'une conversation (soft delete).

    - Les messages sont marqués comme supprimés avec la date
    - Ils ne sont plus visibles pour l'utilisateur
    - L'admin peut toujours les voir et les supprimer physiquement
    """
    count = await ConversationService.soft_delete_messages(
        db, conversation_id, current_user.id, data.message_ids
    )

    if count == 0:
        raise not_found(ErrorCode.MSG_DELETE_FAILED)

    # Audit
    try:
        await AuditService.log_action(
            db=db,
            action_name='message_deleted',
            user_id=current_user.id,
            resource_type_name='message',
            resource_id=None,
            details={'conversation_id': str(conversation_id), 'count': count},
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging message deletion: {e}")

    return MessageDeleteResponse(deleted_count=count)


@router.post(
    "/{conversation_id}/archive",
    response_model=ConversationRead,
    summary="Archiver une conversation",
    description="Archive une conversation. Elle reste accessible mais n'apparait plus dans la liste principale."
)
async def archive_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationRead:
    """
    Archive une conversation.

    - La conversation est marquée comme archivée
    - Elle reste accessible via son ID
    - Elle n'apparait plus dans la liste principale
    """
    conversation = await ConversationService.archive_conversation(
        db, conversation_id, current_user.id
    )

    if not conversation:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit
    try:
        await AuditService.log_action(
            db=db,
            action_name='conversation_archived',
            user_id=current_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging conversation archive: {e}")

    return conversation


@router.post(
    "/{conversation_id}/unarchive",
    response_model=ConversationRead,
    summary="Désarchiver une conversation",
    description="Désarchive une conversation pour la remettre dans la liste principale."
)
async def unarchive_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> ConversationRead:
    """
    Désarchive une conversation.

    - La conversation est remise dans la liste principale
    - archived_at est remis à None
    """
    conversation = await ConversationService.unarchive_conversation(
        db, conversation_id, current_user.id
    )

    if not conversation:
        raise not_found(ErrorCode.CONV_NOT_FOUND)

    # Audit
    try:
        await AuditService.log_action(
            db=db,
            action_name='conversation_unarchived',
            user_id=current_user.id,
            resource_type_name='conversation',
            resource_id=conversation_id,
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging conversation unarchive: {e}")

    return conversation
