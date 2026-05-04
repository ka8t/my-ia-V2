"""
Service Admin Documents - Logique métier pour l'administration des documents.

Ce service permet aux administrateurs de gérer tous les documents du système.
"""

import logging
from typing import AsyncIterator, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.errors import ErrorCode, not_found, api_error
from app.common.storage.service import StorageService
from app.common.utils.query import paginate_query
from app.common.utils.rag_config import get_rag_config
from app.core.config import settings
from app.core.deps import get_ingestion_pipeline
from app.models import Collection, Corpus, CorpusDocument, Document, DocumentVersion, DocumentVisibility, User, UserQuota
from app.features.admin.documents.schemas import (
    AdminBulkOperationResponse,
    AdminDocumentDetailResponse,
    AdminDocumentListResponse,
    AdminDocumentResponse,
    AdminDocumentVersionResponse,
    AdminReindexResponse,
    AdminStorageStatsResponse,
    AdminUserQuotaResponse,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Suivi de progression en mémoire - Utilise le module partagé ReindexManager
# ============================================================================

from app.common.utils.reindex import (
    ReindexManager,
    get_doc_reindex_progress,
    set_doc_reindex_progress,
    clear_doc_reindex_progress,
    request_doc_cancel,
    is_doc_cancel_requested,
    clear_doc_cancel_flag,
    request_source_cancel,
    is_source_cancel_requested,
    clear_source_cancel_flag,
)


class AdminDocumentService:
    """Service d'administration des documents."""

    def __init__(
        self,
        session: AsyncSession,
        storage_service: StorageService,
        chroma_client=None,
    ):
        self.session = session
        self.storage = storage_service
        self.chroma = chroma_client

    # === List & Search ===

    async def list_all_documents(
        self,
        user_id: Optional[UUID] = None,
        collection_id: Optional[UUID] = None,
        corpus_id: Optional[UUID] = None,
        visibility: Optional[str] = None,
        file_type: Optional[str] = None,
        is_indexed: Optional[bool] = None,
        search: Optional[str] = None,
        provider_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AdminDocumentListResponse:
        """Liste tous les documents avec filtres admin.

        Args:
            provider_filter: Si fourni, filtre par indexed_provider = provider OR IS NULL
        """
        from sqlalchemy import or_

        from app.models import CorpusDocument, Corpus

        query = select(Document).options(
            selectinload(Document.user),
            selectinload(Document.collection),
            selectinload(Document.corpus_memberships).selectinload(CorpusDocument.corpus)
        )

        # Filtres
        if user_id:
            query = query.where(Document.user_id == user_id)
        if collection_id:
            query = query.where(Document.collection_id == collection_id)
        if corpus_id:
            # Filtrer par corpus via la table pivot
            subquery = select(CorpusDocument.document_id).where(
                CorpusDocument.corpus_id == corpus_id
            )
            query = query.where(Document.id.in_(subquery))
        if visibility:
            query = query.where(Document.visibility == visibility)
        if file_type:
            query = query.where(Document.file_type == file_type)
        if is_indexed is not None:
            query = query.where(Document.is_indexed == is_indexed)
        if search:
            query = query.where(Document.filename.ilike(f"%{search}%"))

        # Filtre par provider courant (inclut les documents non encore indexés)
        if provider_filter:
            query = query.where(
                or_(
                    Document.indexed_provider == provider_filter,
                    Document.indexed_provider.is_(None)
                )
            )

        # Pagination
        query = query.order_by(desc(Document.updated_at))
        documents, pagination = await paginate_query(
            self.session, query, page=page, page_size=page_size
        )

        # Charger le modele d'embedding actuel depuis la config RAG
        rag_config = await get_rag_config(self.session)

        return AdminDocumentListResponse(
            documents=[
                AdminDocumentResponse(
                    id=doc.id,
                    user_id=doc.user_id,
                    username=doc.user.username if doc.user else None,
                    corpus_count=len(doc.corpus_memberships),
                    corpus_names=[cm.corpus.display_name for cm in doc.corpus_memberships if cm.corpus],
                    collection_id=doc.collection_id,
                    collection_name=doc.collection.display_name if doc.collection else None,
                    collection_embedding_model=doc.collection.embedding_model if doc.collection else None,
                    filename=doc.filename,
                    file_hash=doc.file_hash,
                    file_size=doc.file_size,
                    file_type=doc.file_type,
                    file_path=doc.file_path,
                    chunk_count=doc.chunk_count,
                    embedding_count=doc.embedding_count,
                    indexed_provider=doc.indexed_provider,
                    current_version=doc.current_version or 1,
                    visibility=doc.visibility.value,
                    is_indexed=doc.is_indexed,
                    created_at=doc.created_at,
                    updated_at=doc.updated_at,
                )
                for doc in documents
            ],
            total=pagination.total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=pagination.total_pages,
            current_embedding_model=rag_config.embedding_model,
        )

    async def get_document(self, document_id: UUID) -> AdminDocumentDetailResponse:
        """Récupère un document avec détails admin."""
        result = await self.session.execute(
            select(Document)
            .options(
                selectinload(Document.user),
                selectinload(Document.collection),
                selectinload(Document.corpus_memberships).selectinload(CorpusDocument.corpus),
                selectinload(Document.versions)
            )
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Récupérer les usernames des créateurs de versions
        versions = []
        for v in document.versions:
            creator_username = None
            if v.created_by:
                creator_result = await self.session.execute(
                    select(User.username).where(User.id == v.created_by)
                )
                creator_username = creator_result.scalar_one_or_none()

            versions.append(
                AdminDocumentVersionResponse(
                    id=v.id,
                    document_id=v.document_id,
                    version_number=v.version_number,
                    file_path=v.file_path,
                    file_size=v.file_size,
                    file_hash=v.file_hash,
                    chunk_count=v.chunk_count,
                    comment=v.comment,
                    created_at=v.created_at,
                    created_by=v.created_by,
                    created_by_username=creator_username,
                )
            )

        return AdminDocumentDetailResponse(
            id=document.id,
            user_id=document.user_id,
            username=document.user.username if document.user else None,
            corpus_count=len(document.corpus_memberships) if document.corpus_memberships else 0,
            corpus_names=[cm.corpus.display_name for cm in (document.corpus_memberships or []) if cm.corpus],
            collection_id=document.collection_id,
            collection_name=document.collection.display_name if document.collection else None,
            filename=document.filename,
            file_hash=document.file_hash,
            file_size=document.file_size,
            file_type=document.file_type,
            file_path=document.file_path,
            chunk_count=document.chunk_count,
            embedding_count=document.embedding_count,
            current_version=document.current_version or 1,
            visibility=document.visibility.value,
            is_indexed=document.is_indexed,
            created_at=document.created_at,
            updated_at=document.updated_at,
            versions=versions,
        )

    async def get_document_file(self, document_id: UUID) -> Optional[AsyncIterator[bytes]]:
        """Récupère le contenu binaire d'un document pour téléchargement."""
        result = await self.session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document or not document.file_path:
            return None

        try:
            file_content = await self.storage.download(document.file_path)
            if file_content is None:
                return None

            async def file_iterator():
                yield file_content

            return file_iterator()
        except Exception as e:
            logger.error(f"Erreur lecture fichier {document_id}: {e}")
            return None

    # === Update ===

    async def update_document(
        self,
        document_id: UUID,
        visibility: Optional[str] = None,
        is_indexed: Optional[bool] = None,
        filename: Optional[str] = None,
    ) -> AdminDocumentResponse:
        """Met à jour un document (admin) avec synchronisation ChromaDB si is_indexed change."""
        result = await self.session.execute(
            select(Document)
            .options(
                selectinload(Document.user),
                selectinload(Document.collection),
                selectinload(Document.corpus_memberships).selectinload(CorpusDocument.corpus)
            )
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        if visibility:
            document.visibility = DocumentVisibility(visibility)
        if filename:
            document.filename = filename

        # Gestion du changement d'indexation avec sync ChromaDB
        if is_indexed is not None and is_indexed != document.is_indexed:
            old_indexed = document.is_indexed

            if is_indexed and not old_indexed:
                # Activer l'indexation : réindexer le document AVANT de changer le flag
                try:
                    reindex_result = await self._reindex_document_internal(document)
                    if reindex_result["success"]:
                        document.is_indexed = True
                        logger.info(f"Document {document_id} indexé ({reindex_result['new_chunk_count']} chunks)")
                    else:
                        # Échec de réindexation : lever une erreur
                        raise api_error(500, ErrorCode.INGESTION_FAILED, reindex_result['message'])
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"Erreur réindexation {document_id}: {e}")
                    raise api_error(500, ErrorCode.INGESTION_FAILED, str(e))
            elif not is_indexed and old_indexed:
                # Désactiver l'indexation : supprimer de ChromaDB
                document.is_indexed = False
                await self._delete_from_chroma(document)
                document.chunk_count = 0
                document.embedding_count = 0
                logger.info(f"Document {document_id} désindexé (chunks supprimés de ChromaDB)")

        await self.session.flush()
        await self.session.commit()

        # Re-récupérer le document avec les relations pour éviter les lazy loads
        result = await self.session.execute(
            select(Document)
            .options(
                selectinload(Document.user),
                selectinload(Document.collection),
                selectinload(Document.corpus_memberships).selectinload(CorpusDocument.corpus)
            )
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        return AdminDocumentResponse(
            id=document.id,
            user_id=document.user_id,
            username=document.user.username if document.user else None,
            corpus_count=len(document.corpus_memberships) if document.corpus_memberships else 0,
            corpus_names=[cm.corpus.display_name for cm in (document.corpus_memberships or []) if cm.corpus],
            collection_id=document.collection_id,
            collection_name=document.collection.display_name if document.collection else None,
            filename=document.filename,
            file_hash=document.file_hash,
            file_size=document.file_size,
            file_type=document.file_type,
            file_path=document.file_path,
            chunk_count=document.chunk_count,
            embedding_count=document.embedding_count,
            indexed_provider=document.indexed_provider,
            current_version=document.current_version or 1,
            visibility=document.visibility.value,
            is_indexed=document.is_indexed,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    async def clear_document_index(self, document_id: UUID) -> int:
        """
        Vide uniquement l'index ChromaDB d'un document (sans supprimer le fichier ni la DB).

        Args:
            document_id: ID du document

        Returns:
            Nombre de chunks supprimés
        """
        from app.common.utils.chroma_helpers import clear_document_chunks

        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.collection))
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        if not document.file_hash:
            return 0

        # Déterminer le nom de la collection
        collection_name = await self._get_target_collection_name(document)

        # Supprimer les chunks de ChromaDB (tous les providers)
        deleted = clear_document_chunks(self.chroma, collection_name, document.file_hash)

        # Mettre à jour les compteurs
        old_chunk_count = document.chunk_count or 0
        document.chunk_count = 0
        document.embedding_count = 0
        document.is_indexed = False

        if document.collection:
            document.collection.chunk_count = max(0, (document.collection.chunk_count or 0) - old_chunk_count)

        await self.session.commit()

        logger.info(f"Document {document_id}: index vidé ({deleted} chunks supprimés)")
        return deleted

    async def delete_document(self, document_id: UUID) -> bool:
        """Supprime un document (admin) avec ses embeddings ChromaDB."""
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.collection))
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Sauvegarder les valeurs pour mise à jour des compteurs
        chunk_count = document.chunk_count or 0
        collection = document.collection

        try:
            # Supprimer du storage
            await self.storage.delete_document(document.user_id, document.id)

            # Supprimer de ChromaDB
            await self._delete_from_chroma(document)

            # Mettre à jour les compteurs de la collection
            if collection:
                collection.document_count = max(0, (collection.document_count or 0) - 1)
                collection.chunk_count = max(0, (collection.chunk_count or 0) - chunk_count)

            # Supprimer de la DB
            await self.session.delete(document)
            await self.session.commit()

            logger.info(f"Admin: Document {document_id} supprimé (storage + ChromaDB + DB, -{chunk_count} chunks)")
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur suppression document: {e}")
            raise api_error(500, ErrorCode.DOC_DELETE_FAILED)

    async def _get_target_collection_name(self, document: Document) -> str:
        """
        Détermine le nom de la collection ChromaDB cible pour un document.

        Ordre de priorité:
        1. document.collection_id → charger et utiliser collection.name
        2. Document dans un corpus → première collection assignée au corpus, sinon corpus.name
        3. Fallback: "default"
        """
        # Note: On évite d'accéder aux relations directement pour éviter
        # le lazy-loading qui échoue en contexte async (greenlet_spawn error)
        if document.collection_id:
            coll_result = await self.session.execute(
                select(Collection).where(Collection.id == document.collection_id)
            )
            collection = coll_result.scalar_one_or_none()
            if collection:
                return collection.name

        # Chercher le premier corpus du document via la table pivot
        corpus_doc_result = await self.session.execute(
            select(CorpusDocument)
            .where(CorpusDocument.document_id == document.id)
            .order_by(CorpusDocument.priority, CorpusDocument.created_at)
            .limit(1)
        )
        corpus_doc = corpus_doc_result.scalar_one_or_none()

        if corpus_doc:
            corpus_result = await self.session.execute(
                select(Corpus)
                .options(selectinload(Corpus.assigned_collections))
                .where(Corpus.id == corpus_doc.corpus_id)
            )
            corpus = corpus_result.unique().scalar_one_or_none()
            if corpus and corpus.assigned_collections:
                return corpus.assigned_collections[0].name
            elif corpus:
                return corpus.name

        return "default"

    async def _delete_from_chroma(
        self, document: Document, provider: Optional[str] = None
    ) -> None:
        """
        Supprime les embeddings d'un document de ChromaDB.

        Args:
            document: Document à supprimer
            provider: Provider spécifique (optionnel). Si non fourni, utilise le provider actif.
        """
        if not self.chroma or not document.file_hash:
            return

        try:
            # Récupérer le nom de base de la collection ChromaDB
            base_collection_name = await self._get_target_collection_name(document)

            # Déterminer le provider effectif
            if provider:
                effective_provider = provider
            else:
                effective_provider = settings.llm_provider

            # Nom complet avec suffix provider
            full_collection_name = f"{base_collection_name}_{effective_provider}"

            # Liste des collections à nettoyer
            collections_to_clean = [full_collection_name]
            # Aussi essayer le nom de base pour rétrocompatibilité
            collections_to_clean.append(base_collection_name)
            if base_collection_name != "default":
                collections_to_clean.append("default")

            for coll_name in collections_to_clean:
                try:
                    chroma_collection = self.chroma.get_collection(name=coll_name)
                    chroma_collection.delete(where={"document_hash": document.file_hash})
                    logger.debug(f"ChromaDB: chunks supprimés de {coll_name} pour {document.filename}")
                except Exception:
                    # Collection n'existe pas ou pas de chunks, ignorer
                    pass

            logger.info(f"ChromaDB: embeddings supprimés pour {document.filename} (provider={effective_provider})")

        except Exception as e:
            logger.warning(f"Erreur suppression ChromaDB pour {document.id}: {e}")

    # === Bulk Operations ===

    async def bulk_update_visibility(
        self, document_ids: List[UUID], visibility: str
    ) -> AdminBulkOperationResponse:
        """Change la visibilité de plusieurs documents."""
        success_count = 0
        errors = []

        for doc_id in document_ids:
            try:
                result = await self.session.execute(
                    select(Document).where(Document.id == doc_id)
                )
                document = result.scalar_one_or_none()

                if document:
                    document.visibility = DocumentVisibility(visibility)
                    success_count += 1
                else:
                    errors.append(f"Document {doc_id} non trouvé")

            except Exception as e:
                errors.append(f"Document {doc_id}: {str(e)}")

        await self.session.commit()

        return AdminBulkOperationResponse(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )

    async def bulk_delete(
        self, document_ids: List[UUID]
    ) -> AdminBulkOperationResponse:
        """Supprime plusieurs documents avec leurs embeddings ChromaDB."""
        success_count = 0
        errors = []
        # Compteurs par collection pour mise à jour groupée
        collection_deltas: dict[UUID, dict] = {}

        for doc_id in document_ids:
            try:
                result = await self.session.execute(
                    select(Document)
                    .options(selectinload(Document.collection))
                    .where(Document.id == doc_id)
                )
                document = result.scalar_one_or_none()

                if document:
                    # Sauvegarder pour mise à jour des compteurs
                    if document.collection_id:
                        if document.collection_id not in collection_deltas:
                            collection_deltas[document.collection_id] = {"docs": 0, "chunks": 0}
                        collection_deltas[document.collection_id]["docs"] += 1
                        collection_deltas[document.collection_id]["chunks"] += document.chunk_count or 0

                    # Supprimer du storage
                    await self.storage.delete_document(document.user_id, document.id)
                    # Supprimer de ChromaDB
                    await self._delete_from_chroma(document)
                    # Supprimer de la DB
                    await self.session.delete(document)
                    success_count += 1
                else:
                    errors.append(f"Document {doc_id} non trouvé")

            except Exception as e:
                errors.append(f"Document {doc_id}: {str(e)}")

        # Mettre à jour les compteurs des collections
        for coll_id, deltas in collection_deltas.items():
            coll_result = await self.session.execute(
                select(Collection).where(Collection.id == coll_id)
            )
            collection = coll_result.scalar_one_or_none()
            if collection:
                collection.document_count = max(0, (collection.document_count or 0) - deltas["docs"])
                collection.chunk_count = max(0, (collection.chunk_count or 0) - deltas["chunks"])

        await self.session.commit()

        return AdminBulkOperationResponse(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )

    async def bulk_toggle_indexing(
        self, document_ids: List[UUID], is_indexed: bool
    ) -> AdminBulkOperationResponse:
        """Active/désactive l'indexation de plusieurs documents avec sync ChromaDB."""
        success_count = 0
        errors = []

        for doc_id in document_ids:
            try:
                result = await self.session.execute(
                    select(Document)
                    .options(selectinload(Document.collection))
                    .where(Document.id == doc_id)
                )
                document = result.scalar_one_or_none()

                if document:
                    old_indexed = document.is_indexed
                    document.is_indexed = is_indexed

                    # Synchroniser ChromaDB
                    if is_indexed and not old_indexed:
                        # Réindexer le document
                        try:
                            reindex_result = await self._reindex_document_internal(document)
                            if not reindex_result["success"]:
                                errors.append(f"Document {doc_id}: {reindex_result['message']}")
                                continue
                        except Exception as e:
                            errors.append(f"Document {doc_id}: Erreur réindexation - {str(e)}")
                            continue
                    elif not is_indexed and old_indexed:
                        # Supprimer de ChromaDB
                        await self._delete_from_chroma(document)
                        document.chunk_count = 0
                        document.embedding_count = 0

                    success_count += 1
                else:
                    errors.append(f"Document {doc_id} non trouvé")

            except Exception as e:
                errors.append(f"Document {doc_id}: {str(e)}")

        await self.session.commit()

        return AdminBulkOperationResponse(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )

    # === Réindexation ===

    async def reindex_document(self, document_id: UUID) -> AdminReindexResponse:
        """
        Réindexe un document dans ChromaDB.

        Supprime les anciens chunks et réingère le document avec les paramètres RAG actuels.
        """
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.collection))
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        old_chunk_count = document.chunk_count

        reindex_result = await self._reindex_document_internal(document)

        await self.session.commit()

        return AdminReindexResponse(
            document_id=document.id,
            filename=document.filename,
            old_chunk_count=old_chunk_count,
            new_chunk_count=reindex_result["new_chunk_count"],
            success=reindex_result["success"],
            message=reindex_result["message"],
        )

    async def bulk_reindex(
        self, document_ids: List[UUID]
    ) -> AdminBulkOperationResponse:
        """Réindexe plusieurs documents dans ChromaDB."""
        success_count = 0
        errors = []

        for doc_id in document_ids:
            try:
                result = await self.session.execute(
                    select(Document)
                    .options(selectinload(Document.collection))
                    .where(Document.id == doc_id)
                )
                document = result.scalar_one_or_none()

                if not document:
                    errors.append(f"Document {doc_id} non trouvé")
                    continue

                if not document.is_indexed:
                    errors.append(f"Document {doc_id}: indexation désactivée")
                    continue

                reindex_result = await self._reindex_document_internal(document)

                if reindex_result["success"]:
                    success_count += 1
                else:
                    errors.append(f"Document {doc_id}: {reindex_result['message']}")

            except Exception as e:
                errors.append(f"Document {doc_id}: {str(e)}")

        await self.session.commit()

        return AdminBulkOperationResponse(
            success_count=success_count,
            error_count=len(errors),
            errors=errors,
        )

    async def _reindex_document_internal(
        self,
        document: Document,
        track_progress: bool = False,
        cancel_check: Optional[callable] = None,
        provider: Optional[str] = None
    ) -> dict:
        """
        Logique interne de réindexation d'un document.

        Args:
            document: Le document à réindexer
            track_progress: Si True, met à jour _doc_reindex_progress en mémoire
            cancel_check: Callback optionnel qui retourne True si l'annulation est demandée
            provider: Provider LLM cible (optionnel, pour réindexation multi-provider)

        Returns:
            Dict avec success, message, new_chunk_count, cancelled
        """
        doc_id_str = str(document.id)

        def _update(progress: int, message: str) -> None:
            if track_progress:
                set_doc_reindex_progress(doc_id_str, progress, message)

        def _is_cancelled() -> bool:
            return cancel_check() if cancel_check else False

        try:
            # Vérifier annulation
            if _is_cancelled():
                return {"success": False, "message": "Annulé", "new_chunk_count": 0, "cancelled": True}

            # Supprimer les anciens chunks de ChromaDB (pour le provider cible)
            _update(10, "deleting_old_chunks")
            await self._delete_from_chroma(document, provider=provider)
            old_chunks = document.chunk_count

            # Vérifier annulation
            if _is_cancelled():
                return {"success": False, "message": "Annulé", "new_chunk_count": 0, "cancelled": True}

            # Mettre à jour les compteurs de la collection (soustraire les anciens)
            if document.collection and old_chunks > 0:
                document.collection.chunk_count = max(0, document.collection.chunk_count - old_chunks)

            # Réingérer via le pipeline
            _update(20, "loading_config")
            pipeline = get_ingestion_pipeline()
            if not pipeline:
                return {
                    "success": False,
                    "message": "Pipeline d'ingestion non disponible",
                    "new_chunk_count": 0
                }

            # Vérifier annulation
            if _is_cancelled():
                return {"success": False, "message": "Annulé", "new_chunk_count": 0, "cancelled": True}

            # Charger la configuration RAG
            rag_config = await get_rag_config(self.session)

            # Construire le chemin complet
            full_path = f"{settings.storage_local_path}/{document.file_path}"

            # Récupérer le nom de la collection cible (via corpus si pas de collection directe)
            collection_name = await self._get_target_collection_name(document)

            # Vérifier annulation avant l'étape longue
            if _is_cancelled():
                return {"success": False, "message": "Annulé", "new_chunk_count": 0, "cancelled": True}

            # Callback de progression pour les embeddings (30% -> 85%)
            async def embedding_progress_callback(current: int, total: int) -> None:
                # Progression de 30% à 85% pendant l'embedding
                progress = 30 + int((current / total) * 55) if total > 0 else 30
                _update(progress, "embedding")

            # Appeler le pipeline (étape la plus longue)
            _update(30, "ingesting_file")
            result = await pipeline.ingest_file(
                file_path=full_path,
                parsing_strategy="auto",
                skip_duplicates=False,
                user_id=str(document.user_id),
                visibility=document.visibility.value,
                collection_name=collection_name,
                chunk_size=rag_config.chunk_size,
                chunk_overlap=rag_config.chunk_overlap,
                chunking_strategy=rag_config.chunking_strategy,
                provider=provider,
                progress_callback=embedding_progress_callback,
                original_filename=document.filename,
            )

            # Vérifier annulation après l'ingestion
            if _is_cancelled():
                return {"success": False, "message": "Annulé", "new_chunk_count": 0, "cancelled": True}

            if result["status"] == "success":
                _update(90, "updating_counters")
                new_chunk_count = result.get("chunks_indexed", 0)

                # Déterminer le provider utilisé
                used_provider = provider
                if not used_provider:
                    from app.features.system.service import SystemConfigService
                    config_service = SystemConfigService(self.session)
                    used_provider = await config_service.get("llm.provider", "ollama")

                # Mettre à jour les compteurs et le provider
                document.chunk_count = new_chunk_count
                document.embedding_count = new_chunk_count
                document.indexed_provider = used_provider

                # Mettre à jour les compteurs de la collection (ajouter les nouveaux)
                if document.collection:
                    document.collection.chunk_count += new_chunk_count
                    document.collection.embedding_model = rag_config.embedding_model

                logger.info(f"Document {document.id} réindexé: {new_chunk_count} chunks")

                return {
                    "success": True,
                    "message": f"Réindexé avec {new_chunk_count} chunks",
                    "new_chunk_count": new_chunk_count
                }
            else:
                return {
                    "success": False,
                    "message": result.get("reason", "Erreur inconnue"),
                    "new_chunk_count": 0
                }

        except Exception as e:
            logger.error(f"Erreur réindexation document {document.id}: {e}")
            return {
                "success": False,
                "message": str(e),
                "new_chunk_count": 0
            }

    # === Quotas ===

    async def get_user_quota(self, user_id: UUID) -> AdminUserQuotaResponse:
        """Récupère le quota d'un utilisateur."""
        # Vérifier que l'utilisateur existe
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.unique().scalar_one_or_none()
        if not user:
            raise not_found(ErrorCode.USER_NOT_FOUND)

        # Quota personnalisé?
        quota_result = await self.session.execute(
            select(UserQuota).where(UserQuota.user_id == user_id)
        )
        user_quota = quota_result.scalar_one_or_none()

        # Stats de stockage
        stats = await self.storage.get_user_stats(
            user_id, user_quota.quota_bytes if user_quota else None
        )

        return AdminUserQuotaResponse(
            user_id=user_id,
            username=user.username,
            used_bytes=stats.used_bytes,
            quota_bytes=stats.quota_bytes or self.storage.config.default_quota_bytes,
            quota_used_percent=stats.quota_used_percent,
            file_count=stats.file_count,
            is_custom_quota=user_quota is not None,
        )

    async def set_user_quota(
        self, user_id: UUID, quota_bytes: int, admin_id: UUID
    ) -> AdminUserQuotaResponse:
        """Définit le quota d'un utilisateur."""
        # Vérifier que l'utilisateur existe
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.unique().scalar_one_or_none()
        if not user:
            raise not_found(ErrorCode.USER_NOT_FOUND)

        # Chercher quota existant
        quota_result = await self.session.execute(
            select(UserQuota).where(UserQuota.user_id == user_id)
        )
        user_quota = quota_result.scalar_one_or_none()

        if user_quota:
            user_quota.quota_bytes = quota_bytes
            user_quota.updated_by = admin_id
        else:
            user_quota = UserQuota(
                user_id=user_id,
                quota_bytes=quota_bytes,
                updated_by=admin_id,
            )
            self.session.add(user_quota)

        await self.session.commit()

        logger.info(f"Admin {admin_id}: Quota de {user_id} mis à {quota_bytes} bytes")

        return await self.get_user_quota(user_id)

    async def delete_user_quota(self, user_id: UUID) -> bool:
        """Supprime le quota personnalisé (retour au défaut)."""
        result = await self.session.execute(
            select(UserQuota).where(UserQuota.user_id == user_id)
        )
        user_quota = result.scalar_one_or_none()

        if not user_quota:
            raise not_found(ErrorCode.DOC_NO_CUSTOM_QUOTA)

        await self.session.delete(user_quota)
        await self.session.commit()

        return True

    # === Storage Stats ===

    async def get_storage_stats(self) -> AdminStorageStatsResponse:
        """Récupère les statistiques globales de stockage."""
        # Stats du backend
        backend_stats = await self.storage.get_global_stats()

        # Nombre d'utilisateurs avec fichiers
        users_count_result = await self.session.execute(
            select(func.count(func.distinct(Document.user_id)))
        )
        users_with_files = users_count_result.scalar() or 0

        # Nombre total de fichiers
        files_count_result = await self.session.execute(
            select(func.count(Document.id))
        )
        total_files = files_count_result.scalar() or 0

        # Taille moyenne
        avg_size = backend_stats.total_bytes / total_files if total_files > 0 else 0

        # Top utilisateurs par usage
        top_users_query = (
            select(
                Document.user_id,
                User.username,
                func.sum(Document.file_size).label("total_size"),
                func.count(Document.id).label("file_count"),
            )
            .join(User, Document.user_id == User.id)
            .group_by(Document.user_id, User.username)
            .order_by(desc("total_size"))
            .limit(10)
        )
        top_users_result = await self.session.execute(top_users_query)
        top_users_rows = top_users_result.all()

        top_users = []
        for row in top_users_rows:
            # Récupérer quota personnalisé
            quota_result = await self.session.execute(
                select(UserQuota.quota_bytes).where(UserQuota.user_id == row.user_id)
            )
            custom_quota = quota_result.scalar_one_or_none()
            quota = custom_quota or self.storage.config.default_quota_bytes

            top_users.append(
                AdminUserQuotaResponse(
                    user_id=row.user_id,
                    username=row.username,
                    used_bytes=row.total_size or 0,
                    quota_bytes=quota,
                    quota_used_percent=(
                        (row.total_size / quota * 100) if quota > 0 else 0
                    ),
                    file_count=row.file_count,
                    is_custom_quota=custom_quota is not None,
                )
            )

        return AdminStorageStatsResponse(
            total_bytes=backend_stats.total_bytes,
            used_bytes=backend_stats.used_bytes,
            free_bytes=backend_stats.free_bytes,
            total_files=total_files,
            total_users=users_with_files,
            avg_file_size=avg_size,
            top_users=top_users,
        )
