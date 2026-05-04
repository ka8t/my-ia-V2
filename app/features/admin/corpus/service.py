"""
Service Admin Corpus - Gestion des corpus.

Un corpus est un regroupement de collections et sources externes
pour creer des "domaines de connaissances" indexables.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.storage.service import StorageService
from app.common.utils.query import paginate_query
from app.models import (
    Collection,
    Corpus,
    CorpusCollection,
    CorpusDocument,
    ContextSource,
    CorpusSource,
    Document,
    User,
)
from app.features.admin.corpus.schemas import (
    CorpusCreateRequest,
    CorpusUpdateRequest,
    CorpusResponse,
    CorpusDetailResponse,
    CorpusListResponse,
    CorpusCollectionAdd,
    CorpusCollectionUpdate,
    CorpusCollectionRead,
    CorpusCollectionsListResponse,
    CorpusSourceAdd,
    CorpusSourceUpdate,
    CorpusSourceRead,
    CorpusSourcesListResponse,
    AvailableCollectionRead,
    AvailableSourceRead,
    BulkCollectionsAddRequest,
    BulkCollectionsRemoveRequest,
    BulkSourcesAddRequest,
    BulkSourcesRemoveRequest,
    BulkOperationResult,
    CorpusDocumentRead,
    CorpusDocumentsListResponse,
    AvailableDocumentRead,
    CorpusDocumentAdd,
    BulkDocumentsAddRequest,
    BulkDocumentsRemoveRequest,
    CorpusReindexResponse,
    BulkCorpusReindexResponse,
)

logger = logging.getLogger(__name__)


class AdminCorpusService:
    """Service d'administration des corpus."""

    def __init__(
        self,
        session: AsyncSession,
        storage_service: Optional[StorageService] = None,
        chroma_client=None,
    ):
        self.session = session
        self.storage = storage_service
        self.chroma = chroma_client

    # =========================================================================
    # CRUD Corpus
    # =========================================================================

    async def list_corpus(
        self,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        provider_filter: Optional[str] = None,
    ) -> CorpusListResponse:
        """Liste tous les corpus avec filtres.

        Args:
            provider_filter: Si fourni, filtre sources_count par provider
        """
        query = select(Corpus).options(
            selectinload(Corpus.assigned_collections),
            selectinload(Corpus.sources).selectinload(CorpusSource.source),
            selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
        )

        if is_active is not None:
            query = query.where(Corpus.is_active == is_active)
        if search:
            query = query.where(
                Corpus.display_name.ilike(f"%{search}%") |
                Corpus.name.ilike(f"%{search}%")
            )

        query = query.order_by(desc(Corpus.created_at))
        corpus_list, pagination = await paginate_query(
            self.session, query,
            page=page, page_size=page_size,
            limit=limit, offset=offset,
            unique=True
        )

        return CorpusListResponse(
            corpus=[self._to_response(c, provider_filter=provider_filter) for c in corpus_list],
            total=pagination.total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=pagination.total_pages,
        )

    async def create_corpus(self, data: CorpusCreateRequest) -> CorpusResponse:
        """Cree un nouveau corpus."""
        # Verifier unicite du nom
        existing = await self.session.execute(
            select(Corpus).where(Corpus.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Corpus '{data.name}' existe deja")

        corpus = Corpus(
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            is_active=data.is_active,
        )
        self.session.add(corpus)
        await self.session.commit()

        # Recharger avec les relations pour _to_response
        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.assigned_collections),
                selectinload(Corpus.sources).selectinload(CorpusSource.source),
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
            )
            .where(Corpus.id == corpus.id)
        )
        corpus = result.unique().scalar_one()

        logger.info(f"Corpus cree: {data.name}")
        return self._to_response(corpus)

    async def get_corpus(self, corpus_id: UUID) -> CorpusDetailResponse:
        """Recupere un corpus avec ses membres."""
        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.assigned_collections),
                selectinload(Corpus.sources).selectinload(CorpusSource.source),
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document).selectinload(Document.user),
            )
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one_or_none()

        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        return self._to_detail_response(corpus)

    async def update_corpus(self, corpus_id: UUID, data: CorpusUpdateRequest) -> CorpusResponse:
        """Modifie un corpus."""
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()

        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        if data.display_name is not None:
            corpus.display_name = data.display_name
        if data.description is not None:
            corpus.description = data.description
        if data.is_active is not None:
            corpus.is_active = data.is_active

        await self.session.commit()

        # Recharger avec les relations pour _to_response
        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.assigned_collections),
                selectinload(Corpus.sources).selectinload(CorpusSource.source),
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
            )
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one()

        logger.info(f"Corpus modifie: {corpus.name}")
        return self._to_response(corpus)

    async def clear_corpus_index(self, corpus_id: UUID) -> dict:
        """
        Vide uniquement les index ChromaDB d'un corpus (documents + sources).

        Ne supprime pas les fichiers ni les enregistrements DB.
        Cascade : tous les documents et sources du corpus sont vidés.

        Args:
            corpus_id: ID du corpus

        Returns:
            Dict avec documents_cleared, sources_cleared, total_chunks
        """
        from app.common.utils.chroma_helpers import clear_document_chunks, clear_source_chunks

        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
                selectinload(Corpus.sources).selectinload(CorpusSource.source),
                selectinload(Corpus.assigned_collections),
            )
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one_or_none()

        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        documents = corpus.documents or []
        sources = [cs.source for cs in (corpus.sources or []) if cs.source]
        assigned_collections = corpus.assigned_collections or []

        # Déterminer le nom de la collection pour les documents
        collection_name = assigned_collections[0].name if assigned_collections else corpus.name

        total_chunks = 0
        docs_cleared = 0
        sources_cleared = 0

        # 1. Vider les index des documents
        for doc in documents:
            if doc.file_hash and self.chroma:
                deleted = clear_document_chunks(self.chroma, collection_name, doc.file_hash)
                total_chunks += deleted
                if deleted > 0:
                    doc.chunk_count = 0
                    doc.embedding_count = 0
                    doc.is_indexed = False
                    docs_cleared += 1

        # 2. Vider les index des sources
        for source in sources:
            if source.name and self.chroma:
                deleted = clear_source_chunks(self.chroma, source.name)
                total_chunks += deleted
                if deleted > 0:
                    source.chunk_count = 0
                    source.last_indexed_at = None
                    sources_cleared += 1

        # 3. Mettre à jour les compteurs des collections assignées
        for coll in assigned_collections:
            coll.chunk_count = 0

        await self.session.commit()

        logger.info(f"Corpus {corpus.name}: index vidé ({docs_cleared} docs, {sources_cleared} sources, {total_chunks} chunks)")

        return {
            "documents_cleared": docs_cleared,
            "sources_cleared": sources_cleared,
            "total_chunks": total_chunks
        }

    async def delete_corpus(self, corpus_id: UUID) -> None:
        """
        Supprime un corpus avec nettoyage complet.

        Effectue dans l'ordre :
        1. Supprime les fichiers des documents du storage
        2. Supprime les chunks des documents de ChromaDB
        3. Supprime le corpus (SQL CASCADE supprime les enregistrements DB)
        """
        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
                selectinload(Corpus.assigned_collections),
            )
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one_or_none()

        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        corpus_name = corpus.name
        documents = corpus.documents or []
        assigned_collections = corpus.assigned_collections or []

        # Déterminer le nom de la collection ChromaDB pour les documents du corpus
        chroma_collection_name = None
        if assigned_collections:
            chroma_collection_name = assigned_collections[0].name
        else:
            chroma_collection_name = corpus_name

        # 1. Nettoyer les documents (storage + ChromaDB)
        docs_cleaned = 0
        for document in documents:
            try:
                # Supprimer du storage
                if self.storage and document.user_id:
                    try:
                        await self.storage.delete_document(document.user_id, document.id)
                    except Exception as e:
                        logger.warning(f"Erreur suppression storage pour {document.id}: {e}")

                # Supprimer de ChromaDB
                if self.chroma and document.file_hash and chroma_collection_name:
                    try:
                        chroma_coll = self.chroma.get_collection(name=chroma_collection_name)
                        chroma_coll.delete(where={"document_hash": document.file_hash})
                    except Exception as e:
                        logger.warning(f"Erreur suppression ChromaDB pour {document.id}: {e}")

                docs_cleaned += 1
            except Exception as e:
                logger.error(f"Erreur nettoyage document {document.id}: {e}")

        # 2. Supprimer le corpus (SQL CASCADE supprime documents, corpus_sources, etc.)
        await self.session.delete(corpus)
        await self.session.commit()

        logger.info(f"Corpus supprime: {corpus_name} ({docs_cleaned} documents nettoyes)")

    async def bulk_delete_corpus(self, corpus_ids: List[UUID]) -> BulkOperationResult:
        """
        Supprime plusieurs corpus en masse.

        Collecte les erreurs sans interrompre les autres suppressions.
        """
        success_count = 0
        errors = []

        for corpus_id in corpus_ids:
            try:
                await self.delete_corpus(corpus_id)
                success_count += 1
            except HTTPException as e:
                errors.append(f"{corpus_id}: {e.detail}")
            except Exception as e:
                logger.error(f"Erreur suppression corpus {corpus_id}: {e}")
                errors.append(f"{corpus_id}: {str(e)}")

        logger.info(
            f"Bulk delete corpus: {success_count} supprimes, {len(errors)} erreurs"
        )

        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )

    # =========================================================================
    # Gestion des collections du corpus
    # =========================================================================

    async def list_corpus_collections(self, corpus_id: UUID) -> CorpusCollectionsListResponse:
        """Liste les collections d'un corpus."""
        # Verifier que le corpus existe
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Charger les membres avec leurs collections
        result = await self.session.execute(
            select(CorpusCollection)
            .options(selectinload(CorpusCollection.collection))
            .where(CorpusCollection.corpus_id == corpus_id)
            .order_by(CorpusCollection.priority)
        )
        members = result.scalars().all()

        return CorpusCollectionsListResponse(
            corpus_id=corpus.id,
            corpus_name=corpus.name,
            collections=[self._member_to_response(m) for m in members],
            total=len(members),
        )

    async def add_collection_to_corpus(
        self, corpus_id: UUID, data: CorpusCollectionAdd
    ) -> CorpusCollectionRead:
        """Ajoute une collection publique a un corpus."""
        # Verifier corpus
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Verifier collection (doit etre publique)
        result = await self.session.execute(
            select(Collection).where(Collection.id == data.collection_id)
        )
        collection = result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        if collection.type != "public":
            raise HTTPException(
                status_code=400,
                detail="Seules les collections publiques peuvent etre ajoutees a un corpus"
            )

        # Verifier si deja membre
        result = await self.session.execute(
            select(CorpusCollection).where(
                CorpusCollection.corpus_id == corpus_id,
                CorpusCollection.collection_id == data.collection_id,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Collection deja dans ce corpus")

        member = CorpusCollection(
            corpus_id=corpus_id,
            collection_id=data.collection_id,
            priority=data.priority,
        )
        self.session.add(member)
        await self.session.commit()
        await self.session.refresh(member)

        # Recharger avec la relation collection
        result = await self.session.execute(
            select(CorpusCollection)
            .options(selectinload(CorpusCollection.collection))
            .where(CorpusCollection.id == member.id)
        )
        member = result.scalar_one()

        logger.info(f"Collection {collection.name} ajoutee au corpus {corpus.name}")
        return self._member_to_response(member)

    async def update_corpus_collection(
        self, corpus_id: UUID, collection_id: UUID, data: CorpusCollectionUpdate
    ) -> CorpusCollectionRead:
        """Modifie la priorite d'une collection dans un corpus."""
        result = await self.session.execute(
            select(CorpusCollection)
            .options(selectinload(CorpusCollection.collection))
            .where(
                CorpusCollection.corpus_id == corpus_id,
                CorpusCollection.collection_id == collection_id,
            )
        )
        member = result.scalar_one_or_none()

        if not member:
            raise HTTPException(status_code=404, detail="Collection non trouvee dans ce corpus")

        member.priority = data.priority
        await self.session.commit()
        await self.session.refresh(member)

        return self._member_to_response(member)

    async def remove_collection_from_corpus(self, corpus_id: UUID, collection_id: UUID) -> None:
        """Retire une collection d'un corpus."""
        result = await self.session.execute(
            select(CorpusCollection).where(
                CorpusCollection.corpus_id == corpus_id,
                CorpusCollection.collection_id == collection_id,
            )
        )
        member = result.scalar_one_or_none()

        if not member:
            raise HTTPException(status_code=404, detail="Collection non trouvee dans ce corpus")

        await self.session.delete(member)
        await self.session.commit()

        logger.info(f"Collection retiree du corpus {corpus_id}")

    async def list_available_collections(self, corpus_id: UUID) -> List[AvailableCollectionRead]:
        """Liste les collections publiques non encore dans le corpus."""
        # Verifier que le corpus existe
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # IDs des collections deja dans le corpus
        existing_ids = await self.session.execute(
            select(CorpusCollection.collection_id).where(
                CorpusCollection.corpus_id == corpus_id
            )
        )
        existing_ids = [row[0] for row in existing_ids]

        # Collections publiques non encore ajoutees
        query = select(Collection).where(
            Collection.type == "public"
        )
        if existing_ids:
            query = query.where(~Collection.id.in_(existing_ids))

        result = await self.session.execute(query.order_by(Collection.display_name))
        collections = result.scalars().all()

        return [
            AvailableCollectionRead(
                id=c.id,
                name=c.name,
                display_name=c.display_name,
                document_count=c.document_count,
                chunk_count=c.chunk_count,
            )
            for c in collections
        ]

    # =========================================================================
    # Gestion des sources du corpus
    # =========================================================================

    async def list_corpus_sources(
        self, corpus_id: UUID, provider_filter: Optional[str] = None
    ) -> CorpusSourcesListResponse:
        """Liste les sources d'un corpus.

        Args:
            corpus_id: ID du corpus
            provider_filter: Si fourni, filtre par indexed_provider = provider OR IS NULL
        """
        from sqlalchemy import or_

        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        query = (
            select(CorpusSource)
            .options(selectinload(CorpusSource.source))
            .where(CorpusSource.corpus_id == corpus_id)
        )

        result = await self.session.execute(query.order_by(CorpusSource.priority))
        corpus_sources = result.scalars().all()

        # Filtrer par provider après chargement (car filtre sur relation)
        if provider_filter:
            corpus_sources = [
                cs for cs in corpus_sources
                if cs.source.indexed_provider == provider_filter or cs.source.indexed_provider is None
            ]

        return CorpusSourcesListResponse(
            corpus_id=corpus.id,
            corpus_name=corpus.name,
            sources=[self._corpus_source_to_response(cs) for cs in corpus_sources],
            total=len(corpus_sources),
        )

    async def add_source_to_corpus(
        self, corpus_id: UUID, data: CorpusSourceAdd
    ) -> CorpusSourceRead:
        """Ajoute une source a un corpus."""
        # Verifier corpus
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Verifier source
        result = await self.session.execute(
            select(ContextSource).where(ContextSource.id == data.source_id)
        )
        source = result.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail="Source non trouvee")

        # Verifier si deja presente
        result = await self.session.execute(
            select(CorpusSource).where(
                CorpusSource.corpus_id == corpus_id,
                CorpusSource.source_id == data.source_id,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Source deja dans ce corpus")

        corpus_source = CorpusSource(
            corpus_id=corpus_id,
            source_id=data.source_id,
            priority=data.priority,
            is_enabled=data.is_enabled,
        )
        self.session.add(corpus_source)
        await self.session.commit()
        await self.session.refresh(corpus_source)

        # Recharger avec la relation source
        result = await self.session.execute(
            select(CorpusSource)
            .options(selectinload(CorpusSource.source))
            .where(CorpusSource.id == corpus_source.id)
        )
        corpus_source = result.scalar_one()

        logger.info(f"Source {source.name} ajoutee au corpus {corpus.name}")
        return self._corpus_source_to_response(corpus_source)

    async def update_corpus_source(
        self, corpus_id: UUID, source_id: UUID, data: CorpusSourceUpdate
    ) -> CorpusSourceRead:
        """Modifie une source dans un corpus."""
        result = await self.session.execute(
            select(CorpusSource)
            .options(selectinload(CorpusSource.source))
            .where(
                CorpusSource.corpus_id == corpus_id,
                CorpusSource.source_id == source_id,
            )
        )
        corpus_source = result.scalar_one_or_none()

        if not corpus_source:
            raise HTTPException(status_code=404, detail="Source non trouvee dans ce corpus")

        if data.priority is not None:
            corpus_source.priority = data.priority
        if data.is_enabled is not None:
            corpus_source.is_enabled = data.is_enabled

        await self.session.commit()
        await self.session.refresh(corpus_source)

        return self._corpus_source_to_response(corpus_source)

    async def remove_source_from_corpus(self, corpus_id: UUID, source_id: UUID) -> None:
        """Retire une source d'un corpus."""
        result = await self.session.execute(
            select(CorpusSource).where(
                CorpusSource.corpus_id == corpus_id,
                CorpusSource.source_id == source_id,
            )
        )
        corpus_source = result.scalar_one_or_none()

        if not corpus_source:
            raise HTTPException(status_code=404, detail="Source non trouvee dans ce corpus")

        await self.session.delete(corpus_source)
        await self.session.commit()

        logger.info(f"Source retiree du corpus {corpus_id}")

    # =========================================================================
    # Operations BULK
    # =========================================================================

    async def bulk_add_collections(
        self, corpus_id: UUID, data: BulkCollectionsAddRequest
    ) -> BulkOperationResult:
        """Ajoute plusieurs collections a un corpus."""
        success_count = 0
        errors = []

        for collection_id in data.collection_ids:
            try:
                add_data = CorpusCollectionAdd(
                    collection_id=collection_id,
                    priority=data.priority
                )
                await self.add_collection_to_corpus(corpus_id, add_data)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Collection {collection_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Collection {collection_id}: {str(e)}")

        logger.info(f"Bulk add collections: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    async def bulk_remove_collections(
        self, corpus_id: UUID, data: BulkCollectionsRemoveRequest
    ) -> BulkOperationResult:
        """Retire plusieurs collections d'un corpus."""
        success_count = 0
        errors = []

        for collection_id in data.collection_ids:
            try:
                await self.remove_collection_from_corpus(corpus_id, collection_id)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Collection {collection_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Collection {collection_id}: {str(e)}")

        logger.info(f"Bulk remove collections: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    async def bulk_add_sources(
        self, corpus_id: UUID, data: BulkSourcesAddRequest
    ) -> BulkOperationResult:
        """Ajoute plusieurs sources a un corpus."""
        success_count = 0
        errors = []

        for source_id in data.source_ids:
            try:
                add_data = CorpusSourceAdd(
                    source_id=source_id,
                    priority=data.priority,
                    is_enabled=data.is_enabled
                )
                await self.add_source_to_corpus(corpus_id, add_data)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Source {source_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Source {source_id}: {str(e)}")

        logger.info(f"Bulk add sources: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    async def bulk_remove_sources(
        self, corpus_id: UUID, data: BulkSourcesRemoveRequest
    ) -> BulkOperationResult:
        """Retire plusieurs sources d'un corpus."""
        success_count = 0
        errors = []

        for source_id in data.source_ids:
            try:
                await self.remove_source_from_corpus(corpus_id, source_id)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Source {source_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Source {source_id}: {str(e)}")

        logger.info(f"Bulk remove sources: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    async def list_available_sources(self, corpus_id: UUID) -> List[AvailableSourceRead]:
        """Liste les sources non encore dans le corpus."""
        # Verifier que le corpus existe
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # IDs des sources deja dans le corpus
        existing_ids = await self.session.execute(
            select(CorpusSource.source_id).where(CorpusSource.corpus_id == corpus_id)
        )
        existing_ids = [row[0] for row in existing_ids]

        # Sources non encore ajoutees
        query = select(ContextSource)
        if existing_ids:
            query = query.where(~ContextSource.id.in_(existing_ids))

        result = await self.session.execute(query.order_by(ContextSource.display_name))
        sources = result.scalars().all()

        return [
            AvailableSourceRead(
                id=s.id,
                name=s.name,
                display_name=s.display_name,
                source_type=s.source_type,
                is_enabled=s.is_enabled,
                health_status=s.health_status,
            )
            for s in sources
        ]

    # =========================================================================
    # Helpers de conversion
    # =========================================================================

    def _to_response(self, corpus: Corpus, provider_filter: Optional[str] = None) -> CorpusResponse:
        """Convertit un corpus en reponse API.

        Args:
            provider_filter: Si fourni, filtre sources_count par indexed_provider
        """
        # collections_count = collections qui ont ce corpus assigné (via corpus_id)
        docs = corpus.documents or []
        doc_chunks = sum(d.chunk_count or 0 for d in docs)

        # Filtrer les sources par provider si demandé (cohérence avec list_corpus_sources)
        corpus_sources = corpus.sources or []
        if provider_filter:
            corpus_sources = [
                cs for cs in corpus_sources
                if cs.source and (cs.source.indexed_provider == provider_filter or cs.source.indexed_provider is None)
            ]

        source_chunks = sum(
            cs.source.chunk_count or 0
            for cs in corpus_sources
            if cs.source
        )
        chunks_count = doc_chunks + source_chunks
        return CorpusResponse(
            id=corpus.id,
            name=corpus.name,
            display_name=corpus.display_name,
            description=corpus.description,
            is_active=corpus.is_active,
            collections_count=len(corpus.assigned_collections) if corpus.assigned_collections else 0,
            sources_count=len(corpus_sources),
            documents_count=len(docs),
            chunks_count=chunks_count,
            created_at=corpus.created_at,
            updated_at=corpus.updated_at,
        )

    def _to_detail_response(self, corpus: Corpus) -> CorpusDetailResponse:
        """Convertit un corpus en reponse detaillee."""
        # Utiliser assigned_collections (via Collection.corpus_id) au lieu de la table N-N
        assigned = corpus.assigned_collections or []
        docs = corpus.documents or []
        doc_chunks = sum(d.chunk_count or 0 for d in docs)
        source_chunks = sum(
            cs.source.chunk_count or 0
            for cs in (corpus.sources or [])
            if cs.source
        )
        chunks_count = doc_chunks + source_chunks
        return CorpusDetailResponse(
            id=corpus.id,
            name=corpus.name,
            display_name=corpus.display_name,
            description=corpus.description,
            is_active=corpus.is_active,
            collections_count=len(assigned),
            sources_count=len(corpus.sources) if corpus.sources else 0,
            documents_count=len(docs),
            chunks_count=chunks_count,
            created_at=corpus.created_at,
            updated_at=corpus.updated_at,
            collections=[self._assigned_collection_to_response(c) for c in assigned],
            sources=[self._corpus_source_to_response(cs) for cs in (corpus.sources or [])],
            documents=[self._document_to_response(d) for d in docs],
        )

    def _assigned_collection_to_response(self, collection: Collection) -> CorpusCollectionRead:
        """Convertit une collection assignee (via Collection.corpus_id) en reponse API."""
        return CorpusCollectionRead(
            collection_id=collection.id,
            collection_name=collection.name,
            collection_display_name=collection.display_name,
            collection_type=collection.type,
            document_count=collection.document_count,
            chunk_count=collection.chunk_count,
            priority=None,  # Pas de priorite pour les collections assignees directement
        )

    def _member_to_response(self, member: CorpusCollection) -> CorpusCollectionRead:
        """Convertit une liaison CorpusCollection (table N-N) en reponse API."""
        collection = member.collection
        return CorpusCollectionRead(
            collection_id=collection.id,
            collection_name=collection.name,
            collection_display_name=collection.display_name,
            collection_type=collection.type,
            document_count=collection.document_count,
            chunk_count=collection.chunk_count,
            priority=member.priority,
        )

    def _corpus_source_to_response(self, corpus_source: CorpusSource) -> CorpusSourceRead:
        """Convertit une liaison corpus-source en reponse API."""
        source = corpus_source.source
        return CorpusSourceRead(
            id=corpus_source.id,
            source_id=source.id,
            source_name=source.name,
            source_display_name=source.display_name,
            source_type=source.source_type,
            priority=corpus_source.priority,
            is_enabled=corpus_source.is_enabled,
            source_health_status=source.health_status,
            source_chunk_count=source.chunk_count or 0,
            created_at=corpus_source.created_at,
        )

    def _document_to_response(self, document: Document) -> CorpusDocumentRead:
        """Convertit un document en reponse API."""
        return CorpusDocumentRead(
            id=document.id,
            filename=document.filename,
            file_type=document.file_type,
            file_size=document.file_size,
            chunk_count=document.chunk_count,
            visibility=document.visibility.value,
            is_indexed=document.is_indexed,
            username=document.user.username if document.user else None,
            created_at=document.created_at,
        )

    # =========================================================================
    # Gestion des documents du corpus
    # =========================================================================

    async def list_corpus_documents(
        self, corpus_id: UUID, provider_filter: Optional[str] = None
    ) -> CorpusDocumentsListResponse:
        """Liste les documents d'un corpus.

        Args:
            corpus_id: ID du corpus
            provider_filter: Si fourni, filtre par indexed_provider = provider OR IS NULL
        """
        from sqlalchemy import or_

        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        query = (
            select(Document)
            .join(CorpusDocument, CorpusDocument.document_id == Document.id)
            .options(selectinload(Document.user))
            .where(CorpusDocument.corpus_id == corpus_id)
        )

        # Filtre par provider courant
        if provider_filter:
            query = query.where(
                or_(
                    Document.indexed_provider == provider_filter,
                    Document.indexed_provider.is_(None)
                )
            )

        query = query.order_by(desc(Document.created_at))
        result = await self.session.execute(query)
        documents = result.scalars().all()

        return CorpusDocumentsListResponse(
            corpus_id=corpus.id,
            corpus_name=corpus.name,
            documents=[self._document_to_response(d) for d in documents],
            total=len(documents),
        )

    async def list_available_documents(self, corpus_id: UUID) -> List[AvailableDocumentRead]:
        """Liste les documents non encore dans ce corpus (appartenant a d'autres collections)."""
        # Verifier que le corpus existe
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Documents qui ne sont pas encore dans CE corpus
        # et qui ont le flag is_indexed=True
        subquery = select(CorpusDocument.document_id).where(
            CorpusDocument.corpus_id == corpus_id
        )
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.user), selectinload(Document.collection))
            .where(
                Document.id.notin_(subquery),
                Document.is_indexed == True,
            )
            .order_by(desc(Document.created_at))
        )
        documents = result.scalars().all()

        return [
            AvailableDocumentRead(
                id=d.id,
                filename=d.filename,
                file_type=d.file_type,
                file_size=d.file_size,
                chunk_count=d.chunk_count,
                visibility=d.visibility.value,
                username=d.user.username if d.user else None,
                collection_name=d.collection.display_name if d.collection else None,
            )
            for d in documents
        ]

    async def add_document_to_corpus(
        self, corpus_id: UUID, data: CorpusDocumentAdd
    ) -> CorpusDocumentRead:
        """Ajoute un document a un corpus (le retire de sa collection)."""
        # Verifier corpus
        result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Verifier document
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.user))
            .where(Document.id == data.document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            raise HTTPException(status_code=404, detail="Document non trouve")

        # Verifier que le document n'est pas deja dans ce corpus
        existing = await self.session.execute(
            select(CorpusDocument).where(
                CorpusDocument.corpus_id == corpus_id,
                CorpusDocument.document_id == data.document_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Document deja dans ce corpus")

        # Ajouter le document au corpus via la table pivot
        corpus_doc = CorpusDocument(
            corpus_id=corpus_id,
            document_id=data.document_id,
            priority=0
        )
        self.session.add(corpus_doc)

        await self.session.commit()
        await self.session.refresh(document)

        logger.info(f"Document {document.filename} ajoute au corpus {corpus.name}")
        return self._document_to_response(document)

    async def remove_document_from_corpus(self, corpus_id: UUID, document_id: UUID) -> None:
        """Retire un document d'un corpus."""
        result = await self.session.execute(
            select(CorpusDocument).where(
                CorpusDocument.corpus_id == corpus_id,
                CorpusDocument.document_id == document_id,
            )
        )
        corpus_doc = result.scalar_one_or_none()

        if not corpus_doc:
            raise HTTPException(status_code=404, detail="Document non trouve dans ce corpus")

        # Supprimer l'entrée de la table pivot
        await self.session.delete(corpus_doc)
        await self.session.commit()

        logger.info(f"Document {document_id} retire du corpus {corpus_id}")

    async def bulk_add_documents(
        self, corpus_id: UUID, data: BulkDocumentsAddRequest
    ) -> BulkOperationResult:
        """Ajoute plusieurs documents a un corpus."""
        success_count = 0
        errors = []

        for document_id in data.document_ids:
            try:
                add_data = CorpusDocumentAdd(document_id=document_id)
                await self.add_document_to_corpus(corpus_id, add_data)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Document {document_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Document {document_id}: {str(e)}")

        logger.info(f"Bulk add documents: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    async def bulk_remove_documents(
        self, corpus_id: UUID, data: BulkDocumentsRemoveRequest
    ) -> BulkOperationResult:
        """Retire plusieurs documents d'un corpus."""
        success_count = 0
        errors = []

        for document_id in data.document_ids:
            try:
                await self.remove_document_from_corpus(corpus_id, document_id)
                success_count += 1
            except HTTPException as e:
                errors.append(f"Document {document_id}: {e.detail}")
            except Exception as e:
                errors.append(f"Document {document_id}: {str(e)}")

        logger.info(f"Bulk remove documents: {success_count} succes, {len(errors)} erreurs")
        return BulkOperationResult(
            success_count=success_count,
            error_count=len(errors),
            errors=errors
        )

    # =========================================================================
    # Réindexation du corpus
    # =========================================================================

    async def get_corpus_reindex_items(self, corpus_id: UUID) -> dict:
        """
        Récupère tous les éléments à réindexer pour un corpus.

        Returns:
            dict avec corpus, document_ids, source_ids
        """
        # Récupérer le corpus avec ses relations
        result = await self.session.execute(
            select(Corpus)
            .options(
                selectinload(Corpus.assigned_collections),  # Relation directe vers Collection
                selectinload(Corpus.sources).selectinload(CorpusSource.source),
                selectinload(Corpus.corpus_documents).selectinload(CorpusDocument.document),
            )
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one_or_none()

        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouvé")

        # Collecter tous les IDs de documents
        document_ids = set()

        # 1. Documents directement liés au corpus
        for doc in corpus.documents:
            if doc.is_indexed:
                document_ids.add(doc.id)

        # 2. Documents des collections du corpus (assigned_collections retourne des Collection)
        for collection in corpus.assigned_collections:
            # Récupérer les documents de cette collection
            doc_result = await self.session.execute(
                select(Document.id)
                .where(
                    Document.collection_id == collection.id,
                    Document.is_indexed == True
                )
            )
            for (doc_id,) in doc_result.fetchall():
                document_ids.add(doc_id)

        # 3. Sources du corpus (actives uniquement)
        source_ids = [
            cs.source_id
            for cs in corpus.sources
            if cs.is_enabled and cs.source.is_enabled
        ]

        return {
            "corpus": corpus,
            "document_ids": list(document_ids),
            "source_ids": source_ids,
        }
