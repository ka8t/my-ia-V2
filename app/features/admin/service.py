"""
Service Admin

Logique métier pour l'administration.
"""
import uuid
import logging
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models import (
    User, Role, ConversationMode, ResourceType, AuditAction,
    UserPreference, Conversation, Message, Document, Session, AuditLog
)
from app.features.admin.repository import AdminRepository
from app.core.deps import get_chroma_client
from app.core.config import settings

logger = logging.getLogger(__name__)


class AdminService:
    """Service pour les opérations d'administration"""

    # ========================================================================
    # Statistiques
    # ========================================================================

    @staticmethod
    async def get_stats(db: AsyncSession) -> Dict[str, Any]:
        """Récupère les statistiques globales du système"""
        users_count = await AdminRepository.count(db, User)
        conversations_count = await AdminRepository.count(db, Conversation)
        documents_count = await AdminRepository.count(db, Document)

        return {
            "users": {"total": users_count},
            "conversations": {"total": conversations_count},
            "documents": {"total": documents_count}
        }

    # ========================================================================
    # Helpers privés pour CRUD d'entités nommées
    # ========================================================================

    @staticmethod
    async def _create_named_entity(
        db: AsyncSession,
        model_class,
        data: dict,
        entity_label: str,
    ):
        """
        Crée une entité avec vérification d'unicité sur le champ 'name'.

        Args:
            db: Session de base de données
            model_class: Classe SQLAlchemy (Role, ConversationMode, etc.)
            data: Dictionnaire des données à créer
            entity_label: Libellé pour les messages d'erreur

        Raises:
            HTTPException 409: Si une entité avec le même nom existe déjà
        """
        existing = await db.execute(
            select(model_class).where(model_class.name == data['name'])
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"{entity_label} with name '{data['name']}' already exists"
            )

        entity = model_class(**data)
        db.add(entity)
        await db.commit()
        await db.refresh(entity)
        return entity

    @staticmethod
    async def _update_named_entity(
        db: AsyncSession,
        model_class,
        entity_id: int,
        data: dict,
        entity_label: str,
    ):
        """
        Met à jour une entité avec vérification d'unicité sur le champ 'name'.

        Args:
            db: Session de base de données
            model_class: Classe SQLAlchemy
            entity_id: ID de l'entité à modifier
            data: Dictionnaire des données à mettre à jour
            entity_label: Libellé pour les messages d'erreur

        Raises:
            HTTPException 404: Si l'entité n'existe pas
            HTTPException 409: Si le nouveau nom est déjà utilisé
        """
        entity = await AdminRepository.get_by_id(db, model_class, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail=f"{entity_label} not found")

        if 'name' in data and data['name'] != entity.name:
            existing = await db.execute(
                select(model_class).where(model_class.name == data['name'])
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail=f"{entity_label} with name '{data['name']}' already exists"
                )

        for key, value in data.items():
            setattr(entity, key, value)

        await db.commit()
        await db.refresh(entity)
        return entity

    @staticmethod
    async def _delete_protected_entity(
        db: AsyncSession,
        model_class,
        entity_id: int,
        usage_model,
        usage_fk,
        entity_label: str,
    ) -> bool:
        """
        Supprime une entité avec vérification d'usage.

        Args:
            db: Session de base de données
            model_class: Classe SQLAlchemy de l'entité à supprimer
            entity_id: ID de l'entité
            usage_model: Modèle qui référence cette entité (ex: User pour Role)
            usage_fk: Colonne FK du modèle d'usage (ex: User.role_id)
            entity_label: Libellé pour les messages d'erreur

        Raises:
            HTTPException 404: Si l'entité n'existe pas
            HTTPException 409: Si l'entité est encore utilisée
        """
        entity = await AdminRepository.get_by_id(db, model_class, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail=f"{entity_label} not found")

        count_result = await db.execute(
            select(func.count(usage_model.id)).where(usage_fk == entity_id)
        )
        usage_count = count_result.scalar() or 0
        if usage_count > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete {entity_label.lower()} '{entity.name}': "
                       f"used in {usage_count} record(s)"
            )

        await db.delete(entity)
        await db.commit()
        return True

    # ========================================================================
    # CRUD Roles
    # ========================================================================

    @staticmethod
    async def create_role(db: AsyncSession, role_data: dict) -> Role:
        """Crée un nouveau rôle"""
        return await AdminService._create_named_entity(db, Role, role_data, "Role")

    @staticmethod
    async def update_role(db: AsyncSession, role_id: int, role_data: dict) -> Role:
        """Met à jour un rôle"""
        return await AdminService._update_named_entity(db, Role, role_id, role_data, "Role")

    @staticmethod
    async def delete_role(db: AsyncSession, role_id: int) -> bool:
        """Supprime un rôle"""
        return await AdminService._delete_protected_entity(
            db, Role, role_id, User, User.role_id, "Role"
        )

    # ========================================================================
    # CRUD Conversation Modes
    # ========================================================================

    @staticmethod
    async def create_conversation_mode(db: AsyncSession, mode_data: dict) -> ConversationMode:
        """Crée un mode de conversation"""
        return await AdminService._create_named_entity(
            db, ConversationMode, mode_data, "Conversation mode"
        )

    @staticmethod
    async def update_conversation_mode(
        db: AsyncSession, mode_id: int, mode_data: dict
    ) -> ConversationMode:
        """Met à jour un mode de conversation"""
        return await AdminService._update_named_entity(
            db, ConversationMode, mode_id, mode_data, "Conversation mode"
        )

    @staticmethod
    async def delete_conversation_mode(db: AsyncSession, mode_id: int) -> bool:
        """Supprime un mode de conversation"""
        return await AdminService._delete_protected_entity(
            db, ConversationMode, mode_id, Conversation, Conversation.mode_id, "Conversation mode"
        )

    # ========================================================================
    # CRUD Resource Types
    # ========================================================================

    @staticmethod
    async def create_resource_type(db: AsyncSession, type_data: dict) -> ResourceType:
        """Crée un type de ressource"""
        return await AdminService._create_named_entity(
            db, ResourceType, type_data, "Resource type"
        )

    @staticmethod
    async def update_resource_type(
        db: AsyncSession, type_id: int, type_data: dict
    ) -> ResourceType:
        """Met à jour un type de ressource"""
        return await AdminService._update_named_entity(
            db, ResourceType, type_id, type_data, "Resource type"
        )

    @staticmethod
    async def delete_resource_type(db: AsyncSession, type_id: int) -> bool:
        """Supprime un type de ressource"""
        return await AdminService._delete_protected_entity(
            db, ResourceType, type_id, AuditLog, AuditLog.resource_type_id, "Resource type"
        )

    # ========================================================================
    # CRUD Audit Actions
    # ========================================================================

    @staticmethod
    async def create_audit_action(db: AsyncSession, action_data: dict) -> AuditAction:
        """Crée une action d'audit"""
        return await AdminService._create_named_entity(
            db, AuditAction, action_data, "Audit action"
        )

    @staticmethod
    async def update_audit_action(
        db: AsyncSession, action_id: int, action_data: dict
    ) -> AuditAction:
        """Met à jour une action d'audit"""
        return await AdminService._update_named_entity(
            db, AuditAction, action_id, action_data, "Audit action"
        )

    @staticmethod
    async def delete_audit_action(db: AsyncSession, action_id: int) -> bool:
        """Supprime une action d'audit"""
        return await AdminService._delete_protected_entity(
            db, AuditAction, action_id, AuditLog, AuditLog.action_id, "Audit action"
        )

    # ========================================================================
    # Documents - Suppression avec ChromaDB
    # ========================================================================

    @staticmethod
    async def delete_document(db: AsyncSession, document_id: uuid.UUID) -> bool:
        """Supprime un document (aussi dans ChromaDB si possible)"""
        document = await AdminRepository.get_by_id(db, Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Tentative de suppression dans ChromaDB
        try:
            chroma_client = get_chroma_client()
            if chroma_client:
                collection = chroma_client.get_collection(name=settings.collection_name)
                collection.delete(where={"file_hash": document.file_hash})
                logger.info(f"Document chunks deleted from ChromaDB: {document.file_hash}")
        except Exception as e:
            logger.warning(f"Could not delete document from ChromaDB: {e}")

        # Suppression de la base de données
        await db.delete(document)
        await db.commit()

        return True

    @staticmethod
    async def deindex_document(db: AsyncSession, document_id: uuid.UUID) -> Document:
        """
        Désindexe un document du RAG (is_indexed=False)

        Le document reste dans ChromaDB mais ne sera plus retourné dans les recherches.
        """
        document = await AdminRepository.get_by_id(db, Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        if not document.is_indexed:
            raise HTTPException(status_code=400, detail="Document is already deindexed")

        document.is_indexed = False
        await db.commit()
        await db.refresh(document)

        logger.info(f"Document deindexed: {document_id} ({document.filename})")
        return document

    @staticmethod
    async def reindex_document(db: AsyncSession, document_id: uuid.UUID) -> Document:
        """
        Réindexe un document dans le RAG (is_indexed=True)
        """
        document = await AdminRepository.get_by_id(db, Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        if document.is_indexed:
            raise HTTPException(status_code=400, detail="Document is already indexed")

        document.is_indexed = True
        await db.commit()
        await db.refresh(document)

        logger.info(f"Document reindexed: {document_id} ({document.filename})")
        return document

    @staticmethod
    async def update_document_visibility(
        db: AsyncSession,
        document_id: uuid.UUID,
        visibility: str,
        user_id: uuid.UUID,
        is_admin: bool = False
    ) -> Document:
        """
        Met à jour la visibilité d'un document

        Args:
            db: Session DB
            document_id: ID du document
            visibility: 'public' ou 'private'
            user_id: ID de l'utilisateur qui fait la demande
            is_admin: True si l'utilisateur est admin (peut modifier tous les docs)
        """
        from app.models import DocumentVisibility

        document = await AdminRepository.get_by_id(db, Document, document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Vérifier les permissions (sauf admin)
        if not is_admin and document.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="You can only modify your own documents"
            )

        # Valider la visibilité
        try:
            new_visibility = DocumentVisibility(visibility)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid visibility. Must be 'public' or 'private'"
            )

        if document.visibility == new_visibility:
            raise HTTPException(
                status_code=400,
                detail=f"Document visibility is already '{visibility}'"
            )

        document.visibility = new_visibility
        await db.commit()
        await db.refresh(document)

        # Mettre à jour aussi dans ChromaDB
        try:
            chroma_client = get_chroma_client()
            if chroma_client:
                collection = chroma_client.get_collection(name=settings.collection_name)
                # On ne peut pas mettre à jour les metadata directement dans ChromaDB
                # Il faudrait supprimer et réinsérer les chunks
                logger.warning(
                    f"Document visibility updated in DB but not in ChromaDB. "
                    f"Re-upload document to sync: {document.filename}"
                )
        except Exception as e:
            logger.warning(f"Could not check ChromaDB: {e}")

        logger.info(f"Document visibility updated: {document_id} -> {visibility}")
        return document
