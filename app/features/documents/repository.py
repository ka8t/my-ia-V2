"""
Repository pour les opérations de base de données sur les documents.

Pattern Repository : encapsule toutes les requêtes SQL/ORM.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.common.utils.query import paginate_query
from app.models import Document, DocumentVersion, DocumentVisibility, Collection

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Repository pour les opérations CRUD sur les documents."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # === Read Operations ===

    async def get_by_id(self, document_id: UUID) -> Optional[Document]:
        """Récupère un document par son ID."""
        result = await self.session.execute(
            select(Document).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_versions(self, document_id: UUID) -> Optional[Document]:
        """Récupère un document avec ses versions."""
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.versions))
            .where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_user_document(self, user_id: UUID, document_id: UUID) -> Optional[Document]:
        """
        Récupère un document appartenant à un utilisateur.

        Seuls les documents créés par l'utilisateur (user_id) peuvent être modifiés.
        """
        result = await self.session.execute(
            select(Document).where(
                and_(Document.id == document_id, Document.user_id == user_id)
            )
        )
        return result.scalar_one_or_none()

    async def get_user_document_with_versions(
        self, user_id: UUID, document_id: UUID
    ) -> Optional[Document]:
        """
        Récupère un document utilisateur avec ses versions.

        Seuls les documents créés par l'utilisateur (user_id) sont retournés.
        """
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.versions))
            .where(and_(Document.id == document_id, Document.user_id == user_id))
        )
        return result.scalar_one_or_none()

    async def get_accessible_document_with_versions(
        self, user_id: UUID, document_id: UUID
    ) -> Optional[Document]:
        """
        Récupère un document accessible en lecture avec ses versions.

        Inclut :
        - Les documents créés par l'utilisateur (user_id)
        - Les documents dans sa collection privée (uploadés par d'autres)
        """
        # Sous-requête : collections privées de l'utilisateur
        user_private_collections = (
            select(Collection.id)
            .where(Collection.owner_id == user_id)
            .where(Collection.type == "private")
        )

        # Condition : son document OU document dans sa collection privée
        access_condition = or_(
            Document.user_id == user_id,
            Document.collection_id.in_(user_private_collections)
        )

        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.versions), selectinload(Document.collection))
            .where(and_(Document.id == document_id, access_condition))
        )
        return result.scalar_one_or_none()

    async def list_user_documents(
        self,
        user_id: UUID,
        visibility: Optional[str] = None,
        file_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Document], int]:
        """
        Liste les documents d'un utilisateur avec pagination.

        Inclut :
        - Les documents créés par l'utilisateur (user_id)
        - Les documents dans sa collection privée (uploadés par d'autres)

        Returns:
            Tuple[documents, total_count]
        """
        # Sous-requête : collections privées de l'utilisateur
        user_private_collections = (
            select(Collection.id)
            .where(Collection.owner_id == user_id)
            .where(Collection.type == "private")
        )

        # Condition : ses documents OU documents dans sa collection privée
        ownership_condition = or_(
            Document.user_id == user_id,
            Document.collection_id.in_(user_private_collections)
        )

        # Base query avec jointure sur collection
        query = (
            select(Document)
            .options(joinedload(Document.collection))
            .where(ownership_condition)
        )

        # Filtres optionnels
        if visibility:
            query = query.where(Document.visibility == visibility)
        if file_type:
            query = query.where(Document.file_type == file_type)

        # Pagination
        query = query.order_by(desc(Document.updated_at))
        documents, pagination = await paginate_query(
            self.session, query, page=page, page_size=page_size, unique=True
        )

        return documents, pagination.total

    async def search_user_documents(
        self,
        user_id: UUID,
        query: str,
        visibility: Optional[str] = None,
        limit: int = 50,
    ) -> List[Document]:
        """
        Recherche dans les documents d'un utilisateur.

        Inclut :
        - Les documents créés par l'utilisateur (user_id)
        - Les documents dans sa collection privée (uploadés par d'autres)

        Recherche sur filename (ILIKE).
        """
        search_pattern = f"%{query}%"

        # Sous-requête : collections privées de l'utilisateur
        user_private_collections = (
            select(Collection.id)
            .where(Collection.owner_id == user_id)
            .where(Collection.type == "private")
        )

        # Condition : ses documents OU documents dans sa collection privée
        ownership_condition = or_(
            Document.user_id == user_id,
            Document.collection_id.in_(user_private_collections)
        )

        stmt = select(Document).where(
            and_(
                ownership_condition,
                Document.filename.ilike(search_pattern),
            )
        )

        if visibility:
            stmt = stmt.where(Document.visibility == visibility)

        stmt = stmt.order_by(desc(Document.updated_at)).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hash(self, file_hash: str) -> Optional[Document]:
        """Récupère un document par son hash (détection duplicat global)."""
        result = await self.session.execute(
            select(Document).where(Document.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    async def get_user_document_by_hash(
        self, user_id: UUID, file_hash: str
    ) -> Optional[Document]:
        """Récupère un document par hash pour un utilisateur (détection duplicat par user)."""
        result = await self.session.execute(
            select(Document).where(
                and_(Document.user_id == user_id, Document.file_hash == file_hash)
            )
        )
        return result.scalar_one_or_none()

    async def count_user_documents(self, user_id: UUID) -> int:
        """Compte les documents d'un utilisateur."""
        result = await self.session.execute(
            select(func.count()).where(Document.user_id == user_id)
        )
        return result.scalar() or 0

    # === Write Operations ===

    async def create(self, document: Document) -> Document:
        """Crée un nouveau document."""
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def update(self, document: Document) -> Document:
        """Met à jour un document."""
        document.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def delete(self, document: Document) -> bool:
        """Supprime un document."""
        await self.session.delete(document)
        await self.session.flush()
        return True

    # === Version Operations ===

    async def create_version(self, version: DocumentVersion) -> DocumentVersion:
        """Crée une nouvelle version de document."""
        self.session.add(version)
        await self.session.flush()
        await self.session.refresh(version)
        return version

    async def get_version(
        self, document_id: UUID, version_number: int
    ) -> Optional[DocumentVersion]:
        """Récupère une version spécifique."""
        result = await self.session.execute(
            select(DocumentVersion).where(
                and_(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_number == version_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, document_id: UUID) -> List[DocumentVersion]:
        """Liste toutes les versions d'un document."""
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
        )
        return list(result.scalars().all())

    async def get_latest_version(self, document_id: UUID) -> Optional[DocumentVersion]:
        """Récupère la dernière version d'un document."""
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(desc(DocumentVersion.version_number))
            .limit(1)
        )
        return result.scalar_one_or_none()

    # === Visibility Operations ===

    async def update_visibility(
        self, document: Document, visibility: str
    ) -> Document:
        """Met à jour la visibilité d'un document."""
        document.visibility = DocumentVisibility(visibility)
        document.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def list_public_documents(
        self, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Document], int]:
        """Liste les documents publics (pour admin ou affichage global)."""
        query = (
            select(Document)
            .where(Document.visibility == DocumentVisibility.PUBLIC)
            .order_by(desc(Document.updated_at))
        )

        documents, pagination = await paginate_query(
            self.session, query, page=page, page_size=page_size
        )

        return documents, pagination.total
