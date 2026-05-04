"""
Repository Conversations

Opérations de base de données pour les conversations utilisateur.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.utils.query import paginate_query
from app.models import Conversation, Message, ConversationMode, Collection


class ConversationRepository:
    """Repository pour les opérations CRUD sur les conversations"""

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[Conversation]:
        """
        Récupère une conversation par son ID pour un utilisateur donné.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            Conversation ou None si non trouvée
        """
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .options(selectinload(Conversation.mode))
            .options(selectinload(Conversation.collection))
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Conversation], int]:
        """
        Liste les conversations d'un utilisateur avec pagination.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            limit: Nombre max de résultats
            offset: Décalage pour la pagination

        Returns:
            Tuple (liste des conversations, total)
        """
        # Pagination
        query = (
            select(Conversation)
            .options(selectinload(Conversation.mode))
            .options(selectinload(Conversation.collection))
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        conversations, pagination = await paginate_query(
            db, query, limit=limit, offset=offset
        )

        return conversations, pagination.total

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: uuid.UUID,
        title: str,
        collection_id: uuid.UUID,
        mode_id: int = 1
    ) -> Conversation:
        """
        Crée une nouvelle conversation.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            title: Titre de la conversation
            collection_id: ID de la collection ChromaDB
            mode_id: ID du mode de conversation

        Returns:
            Conversation créée
        """
        conversation = Conversation(
            user_id=user_id,
            title=title,
            collection_id=collection_id,
            mode_id=mode_id
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

        # Charger le mode et la collection pour le retour
        await db.refresh(conversation, ["mode", "collection"])
        return conversation

    @staticmethod
    async def update(
        db: AsyncSession,
        conversation: Conversation,
        title: Optional[str] = None
    ) -> Conversation:
        """
        Met à jour une conversation.

        Args:
            db: Session de base de données
            conversation: Conversation à modifier
            title: Nouveau titre (optionnel)

        Returns:
            Conversation mise à jour
        """
        if title is not None:
            conversation.title = title

        await db.commit()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def delete(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> bool:
        """
        Supprime une conversation et ses messages.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            True si supprimée, False si non trouvée
        """
        result = await db.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            )
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def count_messages(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> int:
        """
        Compte le nombre de messages dans une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation

        Returns:
            Nombre de messages
        """
        result = await db.execute(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conversation_id
            )
        )
        return result.scalar() or 0

    @staticmethod
    async def archive(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[Conversation]:
        """
        Archive une conversation (soft archive).

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            Conversation archivée ou None si non trouvée
        """
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.mode))
            .options(selectinload(Conversation.collection))
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            )
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            return None

        conversation.archived_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def unarchive(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[Conversation]:
        """
        Désarchive une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            user_id: ID de l'utilisateur propriétaire

        Returns:
            Conversation désarchivée ou None si non trouvée
        """
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.mode))
            .options(selectinload(Conversation.collection))
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id
            )
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            return None

        conversation.archived_at = None
        await db.commit()
        await db.refresh(conversation)
        return conversation


    @staticmethod
    async def update_summary(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        summary: str
    ) -> bool:
        """
        Met à jour le résumé d'une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            summary: Texte du résumé

        Returns:
            True si mis à jour, False si conversation non trouvée
        """
        result = await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(summary=summary)
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def get_summary(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> Optional[str]:
        """
        Récupère le résumé d'une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation

        Returns:
            Résumé ou None
        """
        result = await db.execute(
            select(Conversation.summary)
            .where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()


class MessageRepository:
    """Repository pour les opérations sur les messages"""

    @staticmethod
    async def get_recent_messages(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        limit: int = 10
    ) -> List[Message]:
        """
        Récupère les N derniers messages non supprimés d'une conversation.

        Utilise une sous-requête pour sélectionner les N derniers messages
        puis les retourne ordonnés chronologiquement (ASC).

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            limit: Nombre maximum de messages à retourner (défaut: 10 = 5 tours)

        Returns:
            Liste des messages ordonnés par date de création (ASC)
        """
        # Sous-requête: les N derniers messages non supprimés (DESC)
        subquery = (
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None)
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).subquery()

        # Requête principale: récupérer ces messages en ordre chronologique (ASC)
        result = await db.execute(
            select(Message)
            .where(Message.id.in_(select(subquery.c.id)))
            .order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def create(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        sender_type: str,
        content: str,
        sources: Optional[dict] = None,
        response_time: Optional[float] = None
    ) -> Message:
        """
        Crée un nouveau message.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            sender_type: 'user' ou 'assistant'
            content: Contenu du message
            sources: Sources RAG (optionnel)
            response_time: Temps de réponse en secondes (optionnel)

        Returns:
            Message créé
        """
        message = Message(
            conversation_id=conversation_id,
            sender_type=sender_type,
            content=content,
            sources=sources,
            response_time=response_time
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message

    @staticmethod
    async def list_by_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        include_deleted: bool = False
    ) -> List[Message]:
        """
        Liste les messages d'une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation
            include_deleted: Inclure les messages supprimés (pour admin)

        Returns:
            Liste des messages ordonnés par date
        """
        query = select(Message).where(Message.conversation_id == conversation_id)

        if not include_deleted:
            query = query.where(Message.deleted_at.is_(None))

        query = query.order_by(Message.created_at)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        message_id: uuid.UUID
    ) -> Optional[Message]:
        """
        Récupère un message par son ID.

        Args:
            db: Session de base de données
            message_id: ID du message

        Returns:
            Message ou None
        """
        result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def soft_delete(
        db: AsyncSession,
        message_id: uuid.UUID
    ) -> bool:
        """
        Marque un message comme supprimé (soft delete).

        Args:
            db: Session de base de données
            message_id: ID du message

        Returns:
            True si le message a été marqué comme supprimé
        """
        result = await db.execute(
            update(Message)
            .where(Message.id == message_id)
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def soft_delete_pair(
        db: AsyncSession,
        message_ids: List[uuid.UUID]
    ) -> int:
        """
        Marque plusieurs messages comme supprimés (soft delete).

        Args:
            db: Session de base de données
            message_ids: Liste des IDs de messages

        Returns:
            Nombre de messages marqués comme supprimés
        """
        result = await db.execute(
            update(Message)
            .where(Message.id.in_(message_ids))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await db.commit()
        return result.rowcount

    @staticmethod
    async def get_last_assistant_sources(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> Optional[dict]:
        """
        Récupère les sources du dernier message assistant d'une conversation.

        Args:
            db: Session de base de données
            conversation_id: ID de la conversation

        Returns:
            Dict des sources ou None si aucun message assistant avec sources
        """
        result = await db.execute(
            select(Message.sources)
            .where(
                Message.conversation_id == conversation_id,
                Message.sender_type == "assistant",
                Message.sources.isnot(None),
                Message.deleted_at.is_(None)
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def hard_delete(
        db: AsyncSession,
        message_id: uuid.UUID
    ) -> bool:
        """
        Supprime physiquement un message (admin uniquement).

        Args:
            db: Session de base de données
            message_id: ID du message

        Returns:
            True si le message a été supprimé
        """
        result = await db.execute(
            delete(Message).where(Message.id == message_id)
        )
        await db.commit()
        return result.rowcount > 0
