"""
Router Chat

Endpoints pour le chat conversationnel avec RAG.
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Request, Header, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import verify_api_key, verify_jwt_or_api_key, get_db
from app.features.chat.schemas import ChatRequest, ChatResponse
from app.features.chat.service import ChatService
from app.features.auth.router import current_active_user, optional_current_user
from app.features.conversations.repository import ConversationRepository
from app.common.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(optional_current_user)
):
    """
    Endpoint ChatBot conversationnel avec RAG

    Args:
        chat_request: Requête de chat avec query et session_id optionnel
        db: Session database
        user: Utilisateur connecte (optionnel)

    Returns:
        Réponse du chatbot avec sources filtrees par visibilite
    """
    with REQUEST_LATENCY.labels(endpoint="/chat").time():
        try:
            user_id = str(user.id) if user else None

            # Récupérer le mode de la conversation si session_id fourni
            mode_id = None
            if chat_request.session_id and user:
                try:
                    conv_id = uuid.UUID(chat_request.session_id)
                    conversation = await ConversationRepository.get_by_id(db, conv_id, user.id)
                    if conversation:
                        mode_id = conversation.mode_id
                except (ValueError, TypeError):
                    pass

            # Convertir les UUIDs en strings pour le service
            source_ids = None
            if chat_request.source_ids:
                source_ids = [str(sid) for sid in chat_request.source_ids]

            result = await ChatService.chat_with_rag(
                chat_request.query,
                chat_request.session_id,
                user_id=user_id,
                db=db,
                collection_name=chat_request.collection_name,
                source_ids=source_ids,
                language=chat_request.language,
                mode_id=mode_id,
                rag_mode=chat_request.rag_mode or "auto"
            )

            REQUEST_COUNT.labels(endpoint="/chat", method="POST", status="200").inc()

            return ChatResponse(**result)

        except Exception as e:
            REQUEST_COUNT.labels(endpoint="/chat", method="POST", status="500").inc()
            logger.error(f"Error in chat endpoint: {e}")
            raise


@router.post("/stream")
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(optional_current_user)
):
    """
    Endpoint ChatBot avec streaming

    Args:
        chat_request: Requête de chat (session_id = UUID conversation)
        db: Session database
        user: Utilisateur connecte (optionnel)

    Returns:
        Streaming response avec sources filtrees par collection
    """
    try:
        REQUEST_COUNT.labels(endpoint="/chat/stream", method="POST", status="200").inc()
        user_id = str(user.id) if user else None

        # Récupérer la collection et le mode de la conversation si session_id fourni
        # Priorité: conversation.collection > chat_request.collection_name > None
        collection_name = chat_request.collection_name
        collection_display_name = None
        mode_id = None
        if chat_request.session_id and user:
            try:
                conv_id = uuid.UUID(chat_request.session_id)
                conversation = await ConversationRepository.get_by_id(db, conv_id, user.id)
                if conversation:
                    if conversation.collection:
                        collection_name = conversation.collection.name
                        collection_display_name = conversation.collection.display_name
                        logger.debug(f"Streaming with collection: {collection_name}")
                    mode_id = conversation.mode_id
            except (ValueError, TypeError):
                logger.debug(f"session_id invalide: {chat_request.session_id}")

        # Convertir les UUIDs en strings pour le service
        source_ids = None
        if chat_request.source_ids:
            source_ids = [str(sid) for sid in chat_request.source_ids]

        return StreamingResponse(
            ChatService.chat_stream(
                chat_request.query,
                user_id=user_id,
                db=db,
                collection_name=collection_name,
                collection_display_name=collection_display_name,
                source_ids=source_ids,
                conversation_id=chat_request.session_id,
                language=chat_request.language,
                mode_id=mode_id,
                rag_mode=chat_request.rag_mode or "auto"
            ),
            media_type="application/x-ndjson",
            headers={
                "X-Accel-Buffering": "no",  # Désactive buffering nginx
                "Cache-Control": "no-cache",
            }
        )

    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/chat/stream", method="POST", status="500").inc()
        logger.error(f"Error in chat/stream endpoint: {e}")
        raise


# Router pour les autres modes de chat
assistant_router = APIRouter(prefix="/assistant", tags=["assistant"])
test_router = APIRouter(prefix="/test", tags=["test"])


@assistant_router.post("", response_model=ChatResponse)
async def assistant(
    request: Request,
    chat_request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(optional_current_user)
):
    """
    Endpoint Assistant orienté tâches avec RAG

    Args:
        chat_request: Requête de chat
        db: Session database
        user: Utilisateur connecte (optionnel)

    Returns:
        Réponse de l'assistant avec sources filtrees
    """
    with REQUEST_LATENCY.labels(endpoint="/assistant").time():
        try:
            user_id = str(user.id) if user else None

            # Récupérer le mode de la conversation si session_id fourni
            mode_id = None
            if chat_request.session_id and user:
                try:
                    conv_id = uuid.UUID(chat_request.session_id)
                    conversation = await ConversationRepository.get_by_id(db, conv_id, user.id)
                    if conversation:
                        mode_id = conversation.mode_id
                except (ValueError, TypeError):
                    pass

            # Convertir les UUIDs en strings pour le service
            source_ids = None
            if chat_request.source_ids:
                source_ids = [str(sid) for sid in chat_request.source_ids]

            result = await ChatService.assistant_with_rag(
                chat_request.query,
                chat_request.session_id,
                user_id=user_id,
                db=db,
                collection_name=chat_request.collection_name,
                source_ids=source_ids,
                language=chat_request.language,
                mode_id=mode_id,
                rag_mode=chat_request.rag_mode or "auto"
            )

            REQUEST_COUNT.labels(endpoint="/assistant", method="POST", status="200").inc()

            return ChatResponse(**result)

        except Exception as e:
            REQUEST_COUNT.labels(endpoint="/assistant", method="POST", status="500").inc()
            logger.error(f"Error in assistant endpoint: {e}")
            raise


@test_router.post("", response_model=ChatResponse)
async def test_ollama(
    request: Request,
    chat_request: ChatRequest,
    _: bool = Depends(verify_jwt_or_api_key)
):
    """
    Endpoint de test sans RAG - juste Ollama

    Args:
        chat_request: Requête de chat
        _: Vérification de la clé API

    Returns:
        Réponse sans sources
    """
    with REQUEST_LATENCY.labels(endpoint="/test").time():
        try:
            result = await ChatService.test_ollama(
                chat_request.query,
                chat_request.session_id
            )

            REQUEST_COUNT.labels(endpoint="/test", method="POST", status="200").inc()

            return ChatResponse(**result)

        except Exception as e:
            REQUEST_COUNT.labels(endpoint="/test", method="POST", status="500").inc()
            logger.error(f"Error in test endpoint: {e}")
            raise
