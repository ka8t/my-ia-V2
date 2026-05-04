"""
Service Conversations

Logique métier pour la gestion des conversations utilisateur.
"""
import uuid
import logging
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, Collection
from app.features.conversations.repository import ConversationRepository, MessageRepository
from app.features.collections.service import CollectionService
from app.features.conversations.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationRead,
    ConversationDetail,
    MessageRead,
    MessageCreate,
    ChatResponse
)
from app.common.utils.chroma import search_context
from app.common.utils.ollama import generate_response
from app.common.utils.sources import deduplicate_sources, enrich_context_with_display_names
from app.features.audit.service import AuditService
from app.features.chat.service import (
    load_prompt,
    _generate_suggestions,
    _determine_context_status,
    DEFAULT_LANGUAGE
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class ConversationService:
    """Service pour la gestion des conversations"""

    @staticmethod
    async def list_conversations(
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[ConversationRead], int]:
        """
        Liste les conversations de l'utilisateur.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            limit: Nombre max de résultats
            offset: Décalage pour pagination

        Returns:
            Tuple (liste des conversations, total)
        """
        conversations, total = await ConversationRepository.list_by_user(
            db, user_id, limit, offset
        )

        items = []
        for conv in conversations:
            messages_count = await ConversationRepository.count_messages(db, conv.id)
            items.append(ConversationRead(
                id=conv.id,
                title=conv.title,
                collection_id=conv.collection_id,
                collection_name=conv.collection.display_name if conv.collection else None,
                mode_id=conv.mode_id,
                mode_name=conv.mode.name if conv.mode else None,
                messages_count=messages_count,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                archived_at=conv.archived_at
            ))

        return items, total

    @staticmethod
    async def get_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[ConversationDetail]:
        """
        Récupère une conversation avec ses messages.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur

        Returns:
            Détails de la conversation ou None
        """
        conversation = await ConversationRepository.get_by_id(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        messages = [
            MessageRead(
                id=msg.id,
                sender_type=msg.sender_type,
                content=msg.content,
                sources=msg.sources,
                response_time=msg.response_time,
                created_at=msg.created_at
            )
            for msg in conversation.messages
            if msg.deleted_at is None  # Filtrer les messages supprimés
        ]

        return ConversationDetail(
            id=conversation.id,
            title=conversation.title,
            collection_id=conversation.collection_id,
            collection_name=conversation.collection.display_name if conversation.collection else None,
            mode_id=conversation.mode_id,
            mode_name=conversation.mode.name if conversation.mode else None,
            messages=messages,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at
        )

    @staticmethod
    async def create_conversation(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: ConversationCreate
    ) -> ConversationRead:
        """
        Crée une nouvelle conversation.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            data: Données de création

        Returns:
            Conversation créée
        """
        conversation = await ConversationRepository.create(
            db,
            user_id=user_id,
            title=data.title,
            collection_id=data.collection_id,
            mode_id=data.mode_id
        )

        logger.info(f"Conversation created: {conversation.id} for user {user_id} in collection {data.collection_id}")

        # Log dans l'audit
        try:
            mode_name = conversation.mode.name if conversation.mode else "default"
            await AuditService.log_conversation_created(
                db=db,
                user_id=user_id,
                conversation_id=conversation.id,
                mode_name=mode_name
            )
        except Exception as e:
            logger.error(f"Error logging conversation creation: {e}")

        return ConversationRead(
            id=conversation.id,
            title=conversation.title,
            collection_id=conversation.collection_id,
            collection_name=conversation.collection.display_name if conversation.collection else None,
            mode_id=conversation.mode_id,
            mode_name=conversation.mode.name if conversation.mode else None,
            messages_count=0,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at
        )

    @staticmethod
    async def update_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ConversationUpdate
    ) -> Optional[ConversationRead]:
        """
        Met à jour une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur
            data: Données de mise à jour

        Returns:
            Conversation mise à jour ou None
        """
        conversation = await ConversationRepository.get_by_id(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        updated = await ConversationRepository.update(
            db, conversation, title=data.title
        )

        messages_count = await ConversationRepository.count_messages(db, updated.id)

        logger.info(f"Conversation updated: {conversation_id}")

        return ConversationRead(
            id=updated.id,
            title=updated.title,
            collection_id=updated.collection_id,
            collection_name=updated.collection.display_name if updated.collection else None,
            mode_id=updated.mode_id,
            mode_name=updated.mode.name if updated.mode else None,
            messages_count=messages_count,
            created_at=updated.created_at,
            updated_at=updated.updated_at
        )

    @staticmethod
    async def delete_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> bool:
        """
        Supprime une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur

        Returns:
            True si supprimée, False sinon
        """
        deleted = await ConversationRepository.delete(db, conversation_id, user_id)

        if deleted:
            logger.info(f"Conversation deleted: {conversation_id}")

        return deleted

    @staticmethod
    async def add_message(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        data: MessageCreate
    ) -> Optional[MessageRead]:
        """
        Ajoute un message à une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire
            data: Données du message

        Returns:
            Message créé ou None si conversation non trouvée
        """
        # Vérifier que la conversation appartient à l'utilisateur
        conversation = await ConversationRepository.get_by_id(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        message = await MessageRepository.create(
            db,
            conversation_id=conversation_id,
            sender_type=data.sender_type,
            content=data.content,
            sources=data.sources,
            response_time=data.response_time
        )

        return MessageRead(
            id=message.id,
            sender_type=message.sender_type,
            content=message.content,
            sources=message.sources,
            response_time=message.response_time,
            created_at=message.created_at
        )

    @staticmethod
    async def get_or_create_conversation(
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: Optional[str],
        collection_id: uuid.UUID,
        title: str = "Nouvelle conversation",
        mode_id: int = 1
    ) -> Conversation:
        """
        Récupère ou crée une conversation basée sur session_id.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            session_id: ID de session (peut être un UUID de conversation)
            collection_id: ID de la collection ChromaDB
            title: Titre par défaut si création
            mode_id: Mode de conversation

        Returns:
            Conversation existante ou nouvelle
        """
        # Si session_id est fourni et valide, essayer de récupérer la conversation
        if session_id:
            try:
                conv_id = uuid.UUID(session_id)
                existing = await ConversationRepository.get_by_id(db, conv_id, user_id)
                if existing:
                    return existing
            except (ValueError, TypeError):
                pass

        # Créer une nouvelle conversation
        return await ConversationRepository.create(
            db, user_id=user_id, title=title, collection_id=collection_id, mode_id=mode_id
        )

    @staticmethod
    async def soft_delete_messages(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        message_ids: List[uuid.UUID]
    ) -> int:
        """
        Marque des messages comme supprimés (soft delete).

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire
            message_ids: Liste des IDs de messages à supprimer

        Returns:
            Nombre de messages supprimés ou 0 si conversation non trouvée
        """
        # Vérifier que la conversation appartient à l'utilisateur
        conversation = await ConversationRepository.get_by_id(
            db, conversation_id, user_id
        )

        if not conversation:
            return 0

        # Soft delete des messages
        count = await MessageRepository.soft_delete_pair(db, message_ids)
        logger.info(f"Soft deleted {count} message(s) in conversation {conversation_id}")
        return count

    @staticmethod
    async def archive_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[ConversationRead]:
        """
        Archive une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            Conversation archivée ou None si non trouvée
        """
        conversation = await ConversationRepository.archive(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        messages_count = await ConversationRepository.count_messages(db, conversation.id)

        logger.info(f"Conversation archived: {conversation_id}")

        return ConversationRead(
            id=conversation.id,
            title=conversation.title,
            collection_id=conversation.collection_id,
            collection_name=conversation.collection.display_name if conversation.collection else None,
            mode_id=conversation.mode_id,
            mode_name=conversation.mode.name if conversation.mode else None,
            messages_count=messages_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            archived_at=conversation.archived_at
        )

    @staticmethod
    async def unarchive_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[ConversationRead]:
        """
        Désarchive une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            Conversation désarchivée ou None si non trouvée
        """
        conversation = await ConversationRepository.unarchive(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        messages_count = await ConversationRepository.count_messages(db, conversation.id)

        logger.info(f"Conversation unarchived: {conversation_id}")

        return ConversationRead(
            id=conversation.id,
            title=conversation.title,
            collection_id=conversation.collection_id,
            collection_name=conversation.collection.display_name if conversation.collection else None,
            mode_id=conversation.mode_id,
            mode_name=conversation.mode.name if conversation.mode else None,
            messages_count=messages_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            archived_at=conversation.archived_at
        )

    @staticmethod
    async def chat_and_save(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str
    ) -> Optional[ChatResponse]:
        """
        Envoie un message, génère une réponse RAG et sauvegarde les deux.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur
            query: Question de l'utilisateur

        Returns:
            ChatResponse avec les messages sauvegardés ou None si conversation non trouvée
        """
        # Vérifier que la conversation appartient à l'utilisateur
        conversation = await ConversationRepository.get_by_id(
            db, conversation_id, user_id
        )

        if not conversation:
            return None

        # Sauvegarder le message utilisateur
        user_message = await MessageRepository.create(
            db,
            conversation_id=conversation_id,
            sender_type="user",
            content=query
        )

        # Choisir le prompt selon le mode (langue par defaut)
        if conversation.mode and conversation.mode.name == "assistant":
            system_prompt = load_prompt("assistant_system", DEFAULT_LANGUAGE)
        else:
            system_prompt = load_prompt("chatbot_system", DEFAULT_LANGUAGE)

        # Recherche de contexte RAG dans la collection de la conversation
        collection_name = conversation.collection.name if conversation.collection else None
        search_result = await search_context(
            query,
            user_id=str(user_id),
            db_session=db,
            collection_name=collection_name
        )
        context = search_result["context"]
        diagnostics = search_result["diagnostics"]

        # Déterminer le statut du contexte et générer les suggestions si nécessaire
        context_status = _determine_context_status(diagnostics)
        suggestions = None
        if context_status != "ok":
            target_collection = collection_name or settings.collection_name
            suggestions = _generate_suggestions(diagnostics, target_collection)

        # Générer la réponse
        response_text = await generate_response(
            query,
            system_prompt,
            context,
            stream=False
        )

        # Préparer les sources (dedupliquees)
        # Enrichir le contexte avec les display_name des sources (lookup BDD)
        context = await enrich_context_with_display_names(context, db)
        deduped_sources = deduplicate_sources(context)
        sources = {"items": deduped_sources} if deduped_sources else None

        # Sauvegarder la réponse assistant
        assistant_message = await MessageRepository.create(
            db,
            conversation_id=conversation_id,
            sender_type="assistant",
            content=response_text,
            sources=sources
        )

        logger.info(f"Chat saved in conversation {conversation_id}")

        return ChatResponse(
            response=response_text,
            sources=deduped_sources if deduped_sources else None,
            user_message=MessageRead(
                id=user_message.id,
                sender_type=user_message.sender_type,
                content=user_message.content,
                sources=user_message.sources,
                created_at=user_message.created_at
            ),
            assistant_message=MessageRead(
                id=assistant_message.id,
                sender_type=assistant_message.sender_type,
                content=assistant_message.content,
                sources=assistant_message.sources,
                created_at=assistant_message.created_at
            ),
            context_status=context_status,
            suggestions=[{"suggestion_type": s["suggestion_type"], "message": s["message"], "action": s.get("action")} for s in suggestions] if suggestions else None
        )
