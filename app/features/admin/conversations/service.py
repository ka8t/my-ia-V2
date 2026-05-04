"""
Service Admin Conversations

Logique métier pour la gestion avancée des conversations.
"""
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, delete
from sqlalchemy.orm import joinedload
from fastapi import HTTPException

from app.common.utils.query import paginate_query
from app.models import Conversation, Message, User, ConversationMode

logger = logging.getLogger(__name__)


class ConversationAdminService:
    """Service pour la gestion admin des conversations"""

    # ========================================================================
    # LECTURE
    # ========================================================================

    @staticmethod
    async def get_conversations(
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
        mode_id: Optional[int] = None,
        search: Optional[str] = None,
        archived: Optional[bool] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Récupère les conversations avec filtres et pagination.

        Args:
            archived: None = tous, True = archivees uniquement, False = actives uniquement

        Returns:
            Tuple (liste de conversations enrichies, total)
        """
        # Requête de base avec jointures
        base_query = select(Conversation).options(
            joinedload(Conversation.user),
            joinedload(Conversation.mode)
        )

        # Application des filtres
        conditions = []
        if user_id:
            conditions.append(Conversation.user_id == user_id)
        if mode_id:
            conditions.append(Conversation.mode_id == mode_id)
        if search:
            conditions.append(Conversation.title.ilike(f"%{search}%"))
        if archived is not None:
            if archived:
                conditions.append(Conversation.archived_at.isnot(None))
            else:
                conditions.append(Conversation.archived_at.is_(None))
        if created_after:
            conditions.append(Conversation.created_at >= created_after)
        if created_before:
            conditions.append(Conversation.created_at <= created_before)

        if conditions:
            base_query = base_query.where(and_(*conditions))

        # Pagination
        base_query = base_query.order_by(Conversation.updated_at.desc())
        conversations, pagination = await paginate_query(
            db, base_query, limit=limit, offset=offset, unique=True
        )

        # Enrichir avec le comptage des messages
        conversations_data = []
        for conv in conversations:
            msg_count_result = await db.execute(
                select(func.count(Message.id)).where(Message.conversation_id == conv.id)
            )
            messages_count = msg_count_result.scalar() or 0

            conversations_data.append({
                "id": conv.id,
                "user_id": conv.user_id,
                "user_email": conv.user.email if conv.user else "",
                "title": conv.title,
                "mode_id": conv.mode_id,
                "mode_name": conv.mode.name if conv.mode else "",
                "messages_count": messages_count,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "archived_at": conv.archived_at
            })

        return conversations_data, pagination.total

    @staticmethod
    async def get_conversation_detail(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Récupère les détails d'une conversation avec ses messages.

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation

        Returns:
            Dictionnaire avec conversation et messages

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        # Récupérer la conversation
        query = select(Conversation).options(
            joinedload(Conversation.user),
            joinedload(Conversation.mode),
            joinedload(Conversation.messages)
        ).where(Conversation.id == conversation_id)

        result = await db.execute(query)
        conversation = result.unique().scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Formater les messages
        messages = [
            {
                "id": msg.id,
                "sender_type": msg.sender_type,
                "content": msg.content,
                "sources": msg.sources,
                "created_at": msg.created_at
            }
            for msg in sorted(conversation.messages, key=lambda m: m.created_at)
        ]

        return {
            "id": conversation.id,
            "user_id": conversation.user_id,
            "user_email": conversation.user.email if conversation.user else "",
            "title": conversation.title,
            "mode_id": conversation.mode_id,
            "mode_name": conversation.mode.name if conversation.mode else "",
            "messages_count": len(messages),
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "archived_at": conversation.archived_at,
            "messages": messages
        }

    # ========================================================================
    # UPDATE
    # ========================================================================

    @staticmethod
    async def update_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID,
        title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Met à jour une conversation (admin peut modifier n'importe quelle conversation).

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation
            title: Nouveau titre (optionnel)

        Returns:
            Dictionnaire avec la conversation mise à jour

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        result = await db.execute(
            select(Conversation).options(
                joinedload(Conversation.user),
                joinedload(Conversation.mode)
            ).where(Conversation.id == conversation_id)
        )
        conversation = result.unique().scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if title is not None:
            conversation.title = title
            conversation.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(conversation)

        # Compter les messages
        msg_count_result = await db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        )
        messages_count = msg_count_result.scalar() or 0

        logger.info(f"Conversation updated by admin: {conversation_id}, title={title}")

        return {
            "id": conversation.id,
            "user_id": conversation.user_id,
            "user_email": conversation.user.email if conversation.user else "",
            "title": conversation.title,
            "mode_id": conversation.mode_id,
            "mode_name": conversation.mode.name if conversation.mode else "",
            "messages_count": messages_count,
            "archived_at": conversation.archived_at,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at
        }

    # ========================================================================
    # SUPPRESSION
    # ========================================================================

    @staticmethod
    async def delete_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> bool:
        """
        Supprime une conversation et ses messages.

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation

        Returns:
            True si supprimée

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        result = await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        await db.delete(conversation)
        await db.commit()

        logger.info(f"Conversation deleted: {conversation_id}")
        return True

    @staticmethod
    async def delete_user_conversations(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> int:
        """
        Supprime toutes les conversations d'un utilisateur.

        Args:
            db: Session de base de données
            user_id: UUID de l'utilisateur

        Returns:
            Nombre de conversations supprimées

        Raises:
            HTTPException 404 si l'utilisateur n'existe pas
        """
        # Vérifier que l'utilisateur existe
        user_result = await db.execute(select(User).where(User.id == user_id))
        if not user_result.unique().scalar_one_or_none():
            raise HTTPException(status_code=404, detail="User not found")

        # Compter avant suppression
        count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        count = count_result.scalar() or 0

        # Supprimer
        await db.execute(
            delete(Conversation).where(Conversation.user_id == user_id)
        )
        await db.commit()

        logger.info(f"Deleted {count} conversations for user {user_id}")
        return count

    # ========================================================================
    # EXPORT
    # ========================================================================

    @staticmethod
    async def export_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> str:
        """
        Exporte une conversation complète en JSON.

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation

        Returns:
            JSON string de la conversation

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        detail = await ConversationAdminService.get_conversation_detail(
            db, conversation_id
        )

        export_data = {
            "conversation": {
                "id": str(detail["id"]),
                "user_id": str(detail["user_id"]),
                "user_email": detail["user_email"],
                "title": detail["title"],
                "mode": detail["mode_name"],
                "created_at": detail["created_at"].isoformat(),
                "updated_at": detail["updated_at"].isoformat()
            },
            "messages": [
                {
                    "id": str(msg["id"]),
                    "sender": msg["sender_type"],
                    "content": msg["content"],
                    "sources": msg["sources"],
                    "timestamp": msg["created_at"].isoformat()
                }
                for msg in detail["messages"]
            ],
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "messages_count": detail["messages_count"]
        }

        return json.dumps(export_data, indent=2, ensure_ascii=False)

    # ========================================================================
    # ARCHIVAGE
    # ========================================================================

    @staticmethod
    async def archive_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Archive une conversation (admin peut archiver n'importe quelle conversation).

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation

        Returns:
            Dictionnaire avec la conversation mise à jour

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        result = await db.execute(
            select(Conversation).options(
                joinedload(Conversation.user),
                joinedload(Conversation.mode)
            ).where(Conversation.id == conversation_id)
        )
        conversation = result.unique().scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.archived_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(conversation)

        logger.info(f"Conversation archived by admin: {conversation_id}")

        return {
            "id": conversation.id,
            "user_id": conversation.user_id,
            "user_email": conversation.user.email if conversation.user else "",
            "title": conversation.title,
            "mode_id": conversation.mode_id,
            "mode_name": conversation.mode.name if conversation.mode else "",
            "archived_at": conversation.archived_at,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at
        }

    @staticmethod
    async def unarchive_conversation(
        db: AsyncSession,
        conversation_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Désarchive une conversation (admin peut désarchiver n'importe quelle conversation).

        Args:
            db: Session de base de données
            conversation_id: UUID de la conversation

        Returns:
            Dictionnaire avec la conversation mise à jour

        Raises:
            HTTPException 404 si la conversation n'existe pas
        """
        result = await db.execute(
            select(Conversation).options(
                joinedload(Conversation.user),
                joinedload(Conversation.mode)
            ).where(Conversation.id == conversation_id)
        )
        conversation = result.unique().scalar_one_or_none()

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation.archived_at = None
        await db.commit()
        await db.refresh(conversation)

        logger.info(f"Conversation unarchived by admin: {conversation_id}")

        return {
            "id": conversation.id,
            "user_id": conversation.user_id,
            "user_email": conversation.user.email if conversation.user else "",
            "title": conversation.title,
            "mode_id": conversation.mode_id,
            "mode_name": conversation.mode.name if conversation.mode else "",
            "archived_at": conversation.archived_at,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at
        }

    # ========================================================================
    # BULK OPERATIONS
    # ========================================================================

    @staticmethod
    async def bulk_archive_conversations(
        db: AsyncSession,
        conversation_ids: List[uuid.UUID]
    ) -> dict:
        """
        Archive plusieurs conversations en masse.

        Args:
            db: Session de base de données
            conversation_ids: Liste des IDs à archiver

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk archive: {len(conversation_ids)} conversations")

        for conv_id in conversation_ids:
            try:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == conv_id)
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    failed_ids.append(conv_id)
                    logger.warning(f"Bulk archive: conversation {conv_id} non trouvée")
                    continue

                if conversation.archived_at is not None:
                    # Déjà archivée, compter comme succès
                    success_count += 1
                    continue

                conversation.archived_at = datetime.now(timezone.utc)
                await db.commit()
                success_count += 1

            except Exception as e:
                await db.rollback()
                failed_ids.append(conv_id)
                logger.error(f"Bulk archive: erreur pour {conv_id}: {e}")

        logger.info(f"Bulk archive terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_delete_conversations(
        db: AsyncSession,
        conversation_ids: List[uuid.UUID]
    ) -> dict:
        """
        Supprime plusieurs conversations en masse.

        Args:
            db: Session de base de données
            conversation_ids: Liste des IDs à supprimer

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk delete: {len(conversation_ids)} conversations")

        for conv_id in conversation_ids:
            try:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == conv_id)
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    failed_ids.append(conv_id)
                    logger.warning(f"Bulk delete: conversation {conv_id} non trouvée")
                    continue

                await db.delete(conversation)
                await db.commit()
                success_count += 1

            except Exception as e:
                await db.rollback()
                failed_ids.append(conv_id)
                logger.error(f"Bulk delete: erreur pour {conv_id}: {e}")

        logger.info(f"Bulk delete terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_unarchive_conversations(
        db: AsyncSession,
        conversation_ids: List[uuid.UUID]
    ) -> dict:
        """
        Desarchive plusieurs conversations en masse.

        Args:
            db: Session de base de données
            conversation_ids: Liste des IDs à desarchiver

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk unarchive: {len(conversation_ids)} conversations")

        for conv_id in conversation_ids:
            try:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == conv_id)
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    failed_ids.append(conv_id)
                    logger.warning(f"Bulk unarchive: conversation {conv_id} non trouvée")
                    continue

                if conversation.archived_at is None:
                    # Déjà active, compter comme succès
                    success_count += 1
                    continue

                conversation.archived_at = None
                await db.commit()
                success_count += 1

            except Exception as e:
                await db.rollback()
                failed_ids.append(conv_id)
                logger.error(f"Bulk unarchive: erreur pour {conv_id}: {e}")

        logger.info(f"Bulk unarchive terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_export_conversations(
        db: AsyncSession,
        conversation_ids: List[uuid.UUID]
    ) -> dict:
        """
        Exporte plusieurs conversations en masse.

        Args:
            db: Session de base de données
            conversation_ids: Liste des IDs à exporter

        Returns:
            Dict avec les conversations exportées
        """
        exports = []
        failed_ids = []

        logger.info(f"Bulk export: {len(conversation_ids)} conversations")

        for conv_id in conversation_ids:
            try:
                detail = await ConversationAdminService.get_conversation_detail(
                    db, conv_id
                )

                export_data = {
                    "conversation": {
                        "id": str(detail["id"]),
                        "user_id": str(detail["user_id"]),
                        "user_email": detail["user_email"],
                        "title": detail["title"],
                        "mode": detail["mode_name"],
                        "created_at": detail["created_at"].isoformat(),
                        "updated_at": detail["updated_at"].isoformat(),
                        "archived_at": detail["archived_at"].isoformat() if detail["archived_at"] else None
                    },
                    "messages": [
                        {
                            "id": str(msg["id"]),
                            "sender": msg["sender_type"],
                            "content": msg["content"],
                            "sources": msg["sources"],
                            "timestamp": msg["created_at"].isoformat()
                        }
                        for msg in detail["messages"]
                    ],
                    "messages_count": detail["messages_count"]
                }
                exports.append(export_data)

            except HTTPException:
                failed_ids.append(conv_id)
                logger.warning(f"Bulk export: conversation {conv_id} non trouvée")
            except Exception as e:
                failed_ids.append(conv_id)
                logger.error(f"Bulk export: erreur pour {conv_id}: {e}")

        logger.info(f"Bulk export terminé: {len(exports)} succès, {len(failed_ids)} échecs")

        return {
            "conversations": exports,
            "success_count": len(exports),
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids,
            "exported_at": datetime.now(timezone.utc).isoformat()
        }
