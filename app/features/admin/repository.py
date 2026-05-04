"""
Repository Admin

Opérations de base de données pour l'administration.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Type, TypeVar, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, desc
from sqlalchemy.orm import joinedload

from app.models import (
    User, Role, ConversationMode, ResourceType, AuditAction,
    UserPreference, Conversation, Message, Document, Session, AuditLog
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


class AdminRepository:
    """Repository pour les opérations d'administration"""

    # ========================================================================
    # Opérations génériques CRUD
    # ========================================================================

    @staticmethod
    async def get_all(
        db: AsyncSession,
        model: Type[T],
        limit: int = 50,
        offset: int = 0,
        order_by: Any = None
    ) -> List[T]:
        """Récupère tous les éléments d'un modèle"""
        query = select(model)
        if order_by is not None:
            query = query.order_by(order_by)
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        model: Type[T],
        id: Any
    ) -> Optional[T]:
        """Récupère un élément par ID"""
        result = await db.execute(select(model).where(model.id == id))
        return result.scalar_one_or_none()

    @staticmethod
    async def count(db: AsyncSession, model: Type[T]) -> int:
        """Compte le nombre d'éléments"""
        result = await db.execute(select(func.count(model.id)))
        return result.scalar()

    @staticmethod
    async def delete_by_id(db: AsyncSession, model: Type[T], id: Any) -> bool:
        """Supprime un élément par ID"""
        item = await AdminRepository.get_by_id(db, model, id)
        if not item:
            return False

        await db.delete(item)
        await db.commit()
        return True

    # ========================================================================
    # Audit Logs
    # ========================================================================

    @staticmethod
    async def get_audit_logs(
        db: AsyncSession,
        username: Optional[str] = None,
        action_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[AuditLog]:
        """Récupère les logs d'audit avec filtres"""
        query = (
            select(AuditLog)
            .options(joinedload(AuditLog.user).joinedload(User.role))
            .order_by(desc(AuditLog.created_at))
        )

        if username:
            # Recherche partielle par username (case-insensitive)
            query = query.join(AuditLog.user).where(
                func.lower(User.username).contains(username.lower())
            )

        if action_name:
            # Récupérer l'action_id depuis le nom
            action_result = await db.execute(
                select(AuditAction).where(AuditAction.name == action_name)
            )
            action_obj = action_result.scalar_one_or_none()
            if action_obj:
                query = query.where(AuditLog.action_id == action_obj.id)

        if date_from:
            try:
                date_start = datetime.strptime(date_from, "%Y-%m-%d")
                query = query.where(AuditLog.created_at >= date_start)
            except ValueError:
                pass

        if date_to:
            try:
                # Ajouter 1 jour pour inclure toute la journée de fin
                date_end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
                query = query.where(AuditLog.created_at < date_end)
            except ValueError:
                pass

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        # unique() requis avec joinedload
        return result.unique().scalars().all()

    @staticmethod
    async def cleanup_audit_logs(
        db: AsyncSession,
        days: int
    ) -> int:
        """
        Supprime les logs d'audit plus anciens que X jours.

        Args:
            db: Session de base de données
            days: Nombre de jours à conserver

        Returns:
            Nombre de logs supprimés
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Compter avant suppression
        count_query = select(func.count(AuditLog.id)).where(
            AuditLog.created_at < cutoff_date
        )
        count_result = await db.execute(count_query)
        count = count_result.scalar() or 0

        if count > 0:
            # Supprimer les logs anciens
            delete_query = delete(AuditLog).where(
                AuditLog.created_at < cutoff_date
            )
            await db.execute(delete_query)
            await db.commit()
            logger.info(f"Purged {count} audit logs older than {days} days")

        return count

    # ========================================================================
    # Conversations
    # ========================================================================

    @staticmethod
    async def get_conversations(
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        mode_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Conversation]:
        """Récupère les conversations avec filtres et relations User/Mode"""
        from sqlalchemy.orm import joinedload

        query = (
            select(Conversation)
            .options(
                joinedload(Conversation.user),
                joinedload(Conversation.mode)
            )
            .order_by(Conversation.updated_at.desc())
        )

        if user_id:
            query = query.where(Conversation.user_id == user_id)
        if mode_id:
            query = query.where(Conversation.mode_id == mode_id)

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().unique().all()

    @staticmethod
    async def count_conversations(
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        mode_id: Optional[int] = None
    ) -> int:
        """Compte le total des conversations avec filtres"""
        query = select(func.count(Conversation.id))

        if user_id:
            query = query.where(Conversation.user_id == user_id)
        if mode_id:
            query = query.where(Conversation.mode_id == mode_id)

        result = await db.execute(query)
        return result.scalar() or 0

    # ========================================================================
    # Messages
    # ========================================================================

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        conversation_id: Optional[uuid.UUID] = None,
        sender_type: Optional[str] = None,
        include_deleted: bool = False,
        deleted_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Message]:
        """
        Récupère les messages avec filtres.

        Args:
            db: Session de base de données
            conversation_id: Filtrer par conversation
            sender_type: Filtrer par type d'expéditeur
            include_deleted: Inclure les messages supprimés
            deleted_only: Ne montrer que les messages supprimés
            limit: Limite de résultats
            offset: Décalage pour pagination

        Returns:
            Liste des messages
        """
        query = select(Message).order_by(Message.created_at.desc())

        if conversation_id:
            query = query.where(Message.conversation_id == conversation_id)
        if sender_type:
            query = query.where(Message.sender_type == sender_type)

        # Gestion des messages supprimés
        if deleted_only:
            query = query.where(Message.deleted_at.isnot(None))
        elif not include_deleted:
            query = query.where(Message.deleted_at.is_(None))

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def hard_delete_message(
        db: AsyncSession,
        message_id: uuid.UUID
    ) -> bool:
        """
        Supprime physiquement un message (admin uniquement).

        Args:
            db: Session de base de données
            message_id: ID du message

        Returns:
            True si supprimé, False sinon
        """
        result = await db.execute(
            delete(Message).where(Message.id == message_id)
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def restore_message(
        db: AsyncSession,
        message_id: uuid.UUID
    ) -> Optional[Message]:
        """
        Restaure un message supprimé (soft delete).

        Args:
            db: Session de base de données
            message_id: ID du message

        Returns:
            Message restauré ou None
        """
        result = await db.execute(
            select(Message).where(Message.id == message_id)
        )
        message = result.scalar_one_or_none()

        if message and message.deleted_at is not None:
            message.deleted_at = None
            await db.commit()
            await db.refresh(message)
            return message

        return None

    # ========================================================================
    # Documents
    # ========================================================================

    @staticmethod
    async def get_documents(
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        file_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Document]:
        """Récupère les documents avec filtres"""
        query = select(Document).order_by(Document.created_at.desc())

        if user_id:
            query = query.where(Document.user_id == user_id)
        if file_type:
            query = query.where(Document.file_type == file_type)

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all()

    # ========================================================================
    # Sessions
    # ========================================================================

    @staticmethod
    async def get_sessions(
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        active_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Session]:
        """Récupère les sessions avec filtres"""
        from datetime import datetime

        query = select(Session).order_by(Session.created_at.desc())

        if user_id:
            query = query.where(Session.user_id == user_id)
        if active_only:
            query = query.where(Session.expires_at > datetime.now(timezone.utc))

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def revoke_all_user_sessions(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> int:
        """Révoque toutes les sessions d'un utilisateur"""
        count_result = await db.execute(
            select(func.count(Session.id)).where(Session.user_id == user_id)
        )
        count = count_result.scalar()

        await db.execute(delete(Session).where(Session.user_id == user_id))
        await db.commit()

        return count
