"""
Service Admin Collections - Gestion des collections ChromaDB.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.utils.chroma_helpers import safe_chroma_delete, safe_chroma_clear
from app.common.utils.query import paginate_query
from app.common.utils.rag_config import get_rag_config
from app.features.system.service import SystemConfigService
from app.core.config import settings
from app.models import Collection, CollectionSource, ContextSource, CorpusSource, CorpusDocument, Conversation, Document, User, Corpus, CorpusCollection
from app.features.admin.collections.schemas import (
    CollectionCreateRequest,
    CollectionUpdateRequest,
    CollectionResponse,
    CollectionDetailResponse,
    CollectionListResponse,
    CollectionPeekResponse,
    CollectionStatsResponse,
    CollectionTypeEnum,
    CollectionSourceCreate,
    CollectionSourceUpdate,
    CollectionSourceRead,
    CollectionSourcesListResponse,
    ProviderIndexStatus,
    CollectionIndexStatusResponse,
    ReindexResponse,
)

logger = logging.getLogger(__name__)


class AdminCollectionService:
    """Service d'administration des collections ChromaDB."""

    def __init__(self, session: AsyncSession, chroma_client=None, storage=None):
        self.session = session
        self.chroma = chroma_client
        self.storage = storage

    async def _get_chroma_collection_name(self, base_name: str) -> str:
        """
        Retourne le nom ChromaDB suffixé avec le provider actif.

        Args:
            base_name: Nom de base de la collection (ex: "public_sales")

        Returns:
            Nom suffixé (ex: "public_sales_ollama")
        """
        config_service = SystemConfigService(self.session)
        provider = await config_service.get("llm.provider", settings.llm_provider)
        return f"{base_name}_{provider}"

    # === CRUD Collections ===

    async def list_collections(
        self,
        type_filter: Optional[CollectionTypeEnum] = None,
        search: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> CollectionListResponse:
        """Liste toutes les collections avec filtres."""
        query = select(Collection).options(
            selectinload(Collection.owner),
            selectinload(Collection.corpus)
        )

        if type_filter:
            query = query.where(Collection.type == type_filter.value)
        if search:
            query = query.where(
                Collection.display_name.ilike(f"%{search}%") |
                Collection.name.ilike(f"%{search}%")
            )

        # Pagination
        query = query.order_by(Collection.type, desc(Collection.created_at))
        collections, pagination = await paginate_query(
            self.session, query,
            page=page, page_size=page_size,
            limit=limit, offset=offset
        )

        # Charger le modele d'embedding actuel depuis la config RAG
        rag_config = await get_rag_config(self.session)

        # Récupérer le provider actif
        config_service = SystemConfigService(self.session)
        active_provider = await config_service.get("llm.provider", settings.llm_provider)

        # Calculer les stats des corpus pour les collections qui en ont un
        corpus_stats = await self._get_corpus_stats_for_collections(collections)

        return CollectionListResponse(
            collections=[self._to_response(c, corpus_stats.get(c.corpus_id)) for c in collections],
            total=pagination.total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=pagination.total_pages,
            current_embedding_model=rag_config.embedding_model,
            active_provider=active_provider,
        )

    async def create_public_collection(
        self, data: CollectionCreateRequest
    ) -> CollectionDetailResponse:
        """
        Cree une nouvelle collection publique.

        La collection ChromaDB est suffixée avec le provider LLM actif
        pour éviter les conflits de dimension entre embeddings.
        Le nom en DB reste sans suffix pour la transparence UI.
        """
        full_name = f"public_{data.name}"

        # Verifier unicite
        existing = await self.session.execute(
            select(Collection).where(Collection.name == full_name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Collection '{full_name}' existe deja")

        # Déterminer le provider actif
        config_service = SystemConfigService(self.session)
        provider = await config_service.get("llm.provider", settings.llm_provider)
        chroma_collection_name = f"{full_name}_{provider}"

        # Creer dans ChromaDB avec distance cosine (nom suffixé avec provider)
        if self.chroma:
            try:
                self.chroma.get_or_create_collection(
                    name=chroma_collection_name,
                    metadata={
                        "type": "public",
                        "display_name": data.display_name,
                        "provider": provider,
                        "base_name": full_name,
                        "hnsw:space": "cosine",           # Distance cosine pour similarité
                        "hnsw:M": 16,                     # Connexions par noeud
                        "hnsw:construction_ef": 100,      # Qualité construction index
                        "hnsw:search_ef": 50              # Qualité recherche (équilibre)
                    }
                )
                logger.debug(f"ChromaDB collection created: {chroma_collection_name}")
            except Exception as e:
                logger.error(f"Erreur creation ChromaDB: {e}")
                raise HTTPException(status_code=500, detail="Erreur creation collection ChromaDB")

        # Creer en DB
        collection = Collection(
            name=full_name,
            display_name=data.display_name,
            description=data.description,
            type="public",
            owner_id=None,
            space=data.space.value,
        )
        self.session.add(collection)
        await self.session.commit()
        await self.session.refresh(collection)

        logger.info(f"Collection publique creee: {full_name}")
        return await self.get_collection(collection.id)

    async def get_collection(self, collection_id: UUID) -> CollectionDetailResponse:
        """Recupere une collection avec stats live ChromaDB."""
        result = await self.session.execute(
            select(Collection)
            .options(
                selectinload(Collection.owner),
                selectinload(Collection.corpus)
            )
            .where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # Stats ChromaDB live (avec fallback sur nom de base pour rétrocompatibilité)
        chroma_count = 0
        chroma_available = False
        if self.chroma:
            chroma_name = await self._get_chroma_collection_name(collection.name)
            try:
                chroma_coll = self.chroma.get_collection(name=chroma_name)
                chroma_count = chroma_coll.count()
                chroma_available = True
            except Exception:
                # Fallback: essayer le nom de base (collections existantes sans suffix)
                try:
                    chroma_coll = self.chroma.get_collection(name=collection.name)
                    chroma_count = chroma_coll.count()
                    chroma_available = True
                except Exception as e:
                    logger.warning(f"ChromaDB non accessible pour {collection.name}: {e}")

        # Stats du corpus si assigne
        corpus_stats = None
        if collection.corpus_id:
            stats = await self._get_corpus_stats_for_collections([collection])
            corpus_stats = stats.get(collection.corpus_id)

        base_response = self._to_response(collection, corpus_stats)
        return CollectionDetailResponse(
            **base_response.model_dump(),
            chroma_count=chroma_count,
            chroma_available=chroma_available,
        )

    async def update_collection(
        self, collection_id: UUID, data: CollectionUpdateRequest
    ) -> CollectionDetailResponse:
        """Modifie une collection (display_name, description, corpus_id)."""
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        if data.display_name:
            collection.display_name = data.display_name
        if data.description is not None:
            collection.description = data.description

        # Gestion du corpus_id (si le champ est present dans la requete)
        if 'corpus_id' in data.model_fields_set:
            if data.corpus_id is not None:
                # Verifier que le corpus existe
                from app.models import Corpus
                corpus_result = await self.session.execute(
                    select(Corpus).where(Corpus.id == data.corpus_id)
                )
                corpus = corpus_result.scalar_one_or_none()
                if not corpus:
                    raise HTTPException(status_code=404, detail="Corpus non trouve")
                collection.corpus_id = data.corpus_id
                logger.info(f"Collection {collection.name} assignee au corpus {corpus.name}")
            else:
                # Retirer le corpus
                collection.corpus_id = None
                logger.info(f"Collection {collection.name} retiree de son corpus")

        await self.session.commit()
        await self.session.refresh(collection)

        logger.info(f"Collection modifiee: {collection.name}")
        return await self.get_collection(collection.id)

    async def delete_collection(self, collection_id: UUID) -> bool:
        """
        Supprime une collection (ChromaDB → fichiers → conversations → documents → DB).

        Fonctionne pour les collections publiques et privées.
        ChromaDB est supprimé en premier. Si ça échoue, rien d'autre n'est touché.
        """
        from sqlalchemy import delete as sql_delete

        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # 1. Supprimer de ChromaDB EN PREMIER (toutes les variantes provider)
        if self.chroma:
            # Supprimer les collections de tous les providers
            for provider in ["ollama", "llamacpp"]:
                safe_chroma_delete(self.chroma, f"{collection.name}_{provider}")
            # Supprimer aussi le nom de base (rétrocompatibilité)
            safe_chroma_delete(self.chroma, collection.name)

        # 2. Supprimer les conversations liées (messages cascade automatiquement)
        conv_result = await self.session.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.collection_id == collection_id
            )
        )
        conv_count = conv_result.scalar() or 0
        if conv_count > 0:
            await self.session.execute(
                sql_delete(Conversation).where(Conversation.collection_id == collection_id)
            )
            logger.info(f"Suppression de {conv_count} conversation(s) de la collection {collection.name}")

        # 3. Récupérer les documents pour supprimer les fichiers du disque
        docs_result = await self.session.execute(
            select(Document).where(Document.collection_id == collection_id)
        )
        documents = docs_result.scalars().all()
        doc_count = len(documents)

        # 4. Supprimer les fichiers du disque
        if self.storage and documents:
            for doc in documents:
                try:
                    await self.storage.delete_document(doc.user_id, doc.id)
                except Exception as e:
                    logger.warning(f"Erreur suppression fichier {doc.id}: {e}")

        # 5. Supprimer les documents PostgreSQL
        if doc_count > 0:
            await self.session.execute(
                sql_delete(Document).where(Document.collection_id == collection_id)
            )
            logger.info(f"Suppression de {doc_count} document(s) de la collection {collection.name}")

        # 6. Supprimer la collection de la DB
        await self.session.delete(collection)
        await self.session.commit()

        logger.info(f"Collection supprimee: {collection.name} ({doc_count} documents, {conv_count} conversations)")
        return True

    # === Operations sur les documents ===

    async def peek_collection(
        self, collection_id: UUID, limit: int = 10
    ) -> CollectionPeekResponse:
        """Apercu des premiers documents d'une collection."""
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        samples = []
        total = 0

        if self.chroma:
            chroma_name = await self._get_chroma_collection_name(collection.name)
            chroma_coll = None
            try:
                chroma_coll = self.chroma.get_collection(name=chroma_name)
            except Exception:
                # Fallback: essayer le nom de base
                try:
                    chroma_coll = self.chroma.get_collection(name=collection.name)
                except Exception as e:
                    logger.warning(f"Collection ChromaDB non trouvée: {e}")

            if chroma_coll:
                try:
                    total = chroma_coll.count()
                    if total > 0:
                        peek_result = chroma_coll.peek(limit=limit)
                        ids = peek_result.get("ids", [])
                        documents = peek_result.get("documents", [])
                        metadatas = peek_result.get("metadatas", [])

                        for i, doc_id in enumerate(ids):
                            samples.append({
                                "id": doc_id,
                                "document": documents[i] if documents and i < len(documents) else None,
                                "metadata": metadatas[i] if metadatas and i < len(metadatas) else None,
                            })
                except Exception as e:
                    logger.error(f"Erreur peek ChromaDB: {e}")

        return CollectionPeekResponse(
            collection_id=collection.id,
            collection_name=collection.name,
            total_chunks=total,
            samples=samples,
        )

    async def clear_collection_index(self, collection_id: UUID) -> int:
        """
        Vide uniquement l'index ChromaDB d'une collection (sans supprimer fichiers ni DB).

        Vide les collections pour tous les providers (ollama, llamacpp).
        Met à jour les compteurs de chunks dans la DB.

        Args:
            collection_id: ID de la collection

        Returns:
            Nombre de chunks supprimés
        """
        from app.common.utils.chroma_helpers import clear_collection_all_providers

        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # 1. Supprimer de ChromaDB (tous les providers)
        total_deleted = 0
        if self.chroma:
            total_deleted = clear_collection_all_providers(self.chroma, collection.name)

        # 2. Mettre à jour les compteurs des documents
        docs_result = await self.session.execute(
            select(Document).where(Document.collection_id == collection_id)
        )
        documents = docs_result.scalars().all()
        for doc in documents:
            doc.chunk_count = 0
            doc.embedding_count = 0
            doc.is_indexed = False

        # 3. Reset compteur collection
        collection.chunk_count = 0
        await self.session.commit()

        logger.info(f"Collection {collection.name}: index vidé ({total_deleted} chunks)")
        return total_deleted

    async def clear_collection_documents(self, collection_id: UUID) -> int:
        """
        Vide tous les documents d'une collection (ChromaDB → fichiers → PostgreSQL).

        ChromaDB est vidé en premier. Si ça échoue, rien d'autre n'est touché.
        Vide les collections pour tous les providers (ollama, llamacpp).
        """
        from sqlalchemy import delete as sql_delete

        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # 1. Supprimer de ChromaDB EN PREMIER (pour tous les providers)
        total_chroma_deleted = 0
        if self.chroma:
            for provider in ["ollama", "llamacpp"]:
                chroma_name = f"{collection.name}_{provider}"
                deleted = safe_chroma_clear(self.chroma, chroma_name)
                total_chroma_deleted += deleted
                if deleted > 0:
                    logger.info(f"ChromaDB {chroma_name}: {deleted} chunks supprimés")

        # 2. Récupérer les documents pour supprimer les fichiers du disque
        docs_result = await self.session.execute(
            select(Document).where(Document.collection_id == collection_id)
        )
        documents = docs_result.scalars().all()
        deleted_count = len(documents)

        # 3. Supprimer les fichiers du disque
        if self.storage and documents:
            for doc in documents:
                try:
                    await self.storage.delete_document(doc.user_id, doc.id)
                except Exception as e:
                    logger.warning(f"Erreur suppression fichier {doc.id}: {e}")

        # 4. Supprimer les documents PostgreSQL
        if deleted_count > 0:
            await self.session.execute(
                sql_delete(Document).where(Document.collection_id == collection_id)
            )

        # 5. Reset compteurs DB
        collection.document_count = 0
        collection.chunk_count = 0
        await self.session.commit()

        logger.info(f"Collection {collection.name} videe: {deleted_count} documents supprimes")
        return deleted_count

    # === Stats globales ===

    async def get_global_stats(self) -> CollectionStatsResponse:
        """Statistiques globales des collections."""
        # Counts DB
        total = (await self.session.execute(
            select(func.count(Collection.id))
        )).scalar() or 0

        public_count = (await self.session.execute(
            select(func.count(Collection.id)).where(Collection.type == "public")
        )).scalar() or 0

        private_count = total - public_count

        # Stats ChromaDB
        chroma_version = "unknown"
        heartbeat = 0
        total_chunks = 0

        if self.chroma:
            try:
                chroma_version = self.chroma.get_version()
                heartbeat = self.chroma.heartbeat()

                # Compter chunks dans toutes les collections
                collections = self.chroma.list_collections()
                for coll in collections:
                    total_chunks += coll.count()
            except Exception as e:
                logger.warning(f"Erreur stats ChromaDB: {e}")

        return CollectionStatsResponse(
            total_collections=total,
            public_collections=public_count,
            private_collections=private_count,
            total_chunks=total_chunks,
            chroma_version=chroma_version,
            chroma_heartbeat=heartbeat,
        )

    # === Collection utilisateur ===

    async def get_user_collection(self, user_id: UUID) -> CollectionDetailResponse:
        """Recupere la collection privee d'un utilisateur."""
        result = await self.session.execute(
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(Collection.owner_id == user_id, Collection.type == "private")
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection utilisateur non trouvee")

        return await self.get_collection(collection.id)

    async def create_user_collection(self, user_id: UUID) -> dict:
        """
        Crée ou restaure la collection privée d'un utilisateur.

        Vérifie les orphelins dans PostgreSQL et ChromaDB.

        Returns:
            Dict avec details de la création et orphelins trouvés
        """
        from app.core.deps import get_chroma_client
        from app.features.collections.chroma import create_user_collection as create_chroma_collection

        # Vérifier que l'utilisateur existe
        user_result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.unique().scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

        # Vérifier si une collection privée existe déjà
        existing_result = await self.session.execute(
            select(Collection).where(
                Collection.owner_id == user_id,
                Collection.type == "private"
            )
        )
        existing_collection = existing_result.scalar_one_or_none()

        if existing_collection:
            raise HTTPException(
                status_code=409,
                detail=f"Collection privée existe déjà: {existing_collection.name}"
            )

        collection_name = f"user_{user_id}"
        orphans_found = {
            "documents_without_collection": 0,
            "documents_reassigned": 0,
            "chroma_collection_existed": False,
            "chroma_chunks_found": 0
        }

        # 1. Vérifier s'il existe des documents orphelins pour cet utilisateur
        # (documents dont la collection_id pointe vers une collection inexistante)
        orphan_docs_result = await self.session.execute(
            select(func.count(Document.id)).where(
                Document.user_id == user_id,
                ~Document.collection_id.in_(
                    select(Collection.id)
                )
            )
        )
        orphans_found["documents_without_collection"] = orphan_docs_result.scalar() or 0

        # 2. Vérifier si la collection existe déjà dans ChromaDB
        chroma_client = get_chroma_client()
        if chroma_client:
            try:
                existing_chroma = chroma_client.get_collection(name=collection_name)
                if existing_chroma:
                    orphans_found["chroma_collection_existed"] = True
                    orphans_found["chroma_chunks_found"] = existing_chroma.count()
            except Exception:
                # Collection n'existe pas dans ChromaDB, c'est OK
                pass

        # 3. Créer la collection dans ChromaDB
        try:
            create_chroma_collection(str(user_id))
            logger.info(f"ChromaDB collection created/verified: {collection_name}")
        except Exception as e:
            logger.warning(f"ChromaDB creation warning: {e}")

        # 4. Créer la collection en DB PostgreSQL
        new_collection = Collection(
            name=collection_name,
            display_name="Ma bibliothèque",
            type="private",
            owner_id=user_id,
            space="cosine"
        )
        self.session.add(new_collection)
        await self.session.flush()  # Pour obtenir l'ID

        # 5. Réassocier les documents orphelins de cet utilisateur
        if orphans_found["documents_without_collection"] > 0:
            # Trouver les documents avec collection_id invalide
            orphan_docs = await self.session.execute(
                select(Document).where(
                    Document.user_id == user_id,
                    ~Document.collection_id.in_(
                        select(Collection.id)
                    )
                )
            )
            docs_to_reassign = orphan_docs.scalars().all()

            for doc in docs_to_reassign:
                doc.collection_id = new_collection.id
                orphans_found["documents_reassigned"] += 1

        await self.session.commit()

        logger.info(
            f"Collection privée créée pour {user.email}: {collection_name}, "
            f"orphelins réassignés: {orphans_found['documents_reassigned']}"
        )

        return {
            "collection_id": str(new_collection.id),
            "collection_name": collection_name,
            "user_email": user.email,
            "orphans": orphans_found,
            "message": "Collection privée créée avec succès"
        }

    # === Helpers ===

    async def _get_corpus_stats_for_collections(
        self, collections: List[Collection]
    ) -> dict:
        """
        Calcule les stats des corpus pour une liste de collections.

        Returns:
            Dict[corpus_id, {"document_count": int, "source_count": int, "chunk_count": int}]
        """
        # Recuperer les IDs des corpus uniques
        corpus_ids = {c.corpus_id for c in collections if c.corpus_id}
        if not corpus_ids:
            return {}

        stats = {}

        # Calculer les stats pour chaque corpus
        for corpus_id in corpus_ids:
            # Nombre de documents et chunks documents (via table pivot corpus_documents)
            doc_result = await self.session.execute(
                select(
                    func.count(Document.id),
                    func.coalesce(func.sum(Document.chunk_count), 0)
                )
                .select_from(Document)
                .join(CorpusDocument, CorpusDocument.document_id == Document.id)
                .where(CorpusDocument.corpus_id == corpus_id)
            )
            doc_row = doc_result.one()
            doc_count = doc_row[0] or 0
            doc_chunks = doc_row[1] or 0

            # Nombre de sources et chunks sources
            source_result = await self.session.execute(
                select(
                    func.count(CorpusSource.id),
                    func.coalesce(func.sum(ContextSource.chunk_count), 0)
                )
                .select_from(CorpusSource)
                .join(ContextSource, CorpusSource.source_id == ContextSource.id)
                .where(CorpusSource.corpus_id == corpus_id)
            )
            source_row = source_result.one()
            source_count = source_row[0] or 0
            source_chunks = source_row[1] or 0

            stats[corpus_id] = {
                "document_count": doc_count,
                "source_count": source_count,
                "chunk_count": int(doc_chunks) + int(source_chunks),
            }

        return stats

    def _to_response(
        self, collection: Collection, corpus_stats: Optional[dict] = None
    ) -> CollectionResponse:
        """Convertit un model en response."""
        # Relation 1-1 : corpus assigne via Collection.corpus_id
        corpus = collection.corpus if hasattr(collection, 'corpus') else None

        return CollectionResponse(
            id=collection.id,
            name=collection.name,
            display_name=collection.display_name,
            description=collection.description,
            type=CollectionTypeEnum(collection.type),
            owner_id=collection.owner_id,
            owner_username=collection.owner.username if collection.owner else None,
            space=collection.space,
            document_count=collection.document_count,
            chunk_count=collection.chunk_count,
            embedding_model=collection.embedding_model,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            corpus_id=collection.corpus_id,
            corpus_name=corpus.name if corpus else None,
            corpus_display_name=corpus.display_name if corpus else None,
            # Stats du corpus
            corpus_document_count=corpus_stats["document_count"] if corpus_stats else None,
            corpus_source_count=corpus_stats["source_count"] if corpus_stats else None,
            corpus_chunk_count=corpus_stats["chunk_count"] if corpus_stats else None,
        )

    # ========================================================================
    # BULK OPERATIONS
    # ========================================================================

    async def bulk_delete_collections(self, collection_ids: List[UUID]) -> dict:
        """
        Supprime plusieurs collections en masse (publiques et privées).

        Ordre par collection : ChromaDB → Storage docs → conversations → DB docs → DB collection.
        Si ChromaDB échoue pour une collection, celle-ci est marquée failed.

        Args:
            collection_ids: Liste des IDs a supprimer

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        from sqlalchemy import delete as sql_delete

        success_count = 0
        failed_ids = []

        logger.info(f"Bulk delete collections: {len(collection_ids)} collections")

        for coll_id in collection_ids:
            try:
                result = await self.session.execute(
                    select(Collection).where(Collection.id == coll_id)
                )
                collection = result.scalar_one_or_none()

                if not collection:
                    failed_ids.append(coll_id)
                    logger.warning(f"Bulk delete: collection {coll_id} non trouvee")
                    continue

                # 1. Supprimer de ChromaDB EN PREMIER (toutes les variantes provider)
                if self.chroma:
                    try:
                        # Supprimer les collections de tous les providers
                        for provider in ["ollama", "llamacpp"]:
                            safe_chroma_delete(self.chroma, f"{collection.name}_{provider}")
                        # Supprimer aussi le nom de base (rétrocompatibilité)
                        safe_chroma_delete(self.chroma, collection.name)
                    except RuntimeError:
                        failed_ids.append(coll_id)
                        continue

                # 2. Supprimer les conversations liées (messages cascade automatiquement)
                await self.session.execute(
                    sql_delete(Conversation).where(Conversation.collection_id == coll_id)
                )

                # 3. Récupérer et supprimer les fichiers du disque
                docs_result = await self.session.execute(
                    select(Document).where(Document.collection_id == coll_id)
                )
                documents = docs_result.scalars().all()

                if self.storage and documents:
                    for doc in documents:
                        try:
                            await self.storage.delete_document(doc.user_id, doc.id)
                        except Exception as e:
                            logger.warning(f"Erreur suppression fichier {doc.id}: {e}")

                # 4. Supprimer les documents PostgreSQL
                if documents:
                    await self.session.execute(
                        sql_delete(Document).where(Document.collection_id == coll_id)
                    )

                # 5. Supprimer la collection de la DB
                await self.session.delete(collection)
                await self.session.commit()
                success_count += 1

            except Exception as e:
                await self.session.rollback()
                failed_ids.append(coll_id)
                logger.error(f"Bulk delete: erreur pour {coll_id}: {e}")

        logger.info(f"Bulk delete termine: {success_count} succes, {len(failed_ids)} echecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    async def bulk_clear_collections(self, collection_ids: List[UUID]) -> dict:
        """
        Vide l'index ChromaDB de plusieurs collections (sans supprimer fichiers ni DB).

        Met à jour les compteurs de chunks dans la DB.
        Si ChromaDB échoue pour une collection, celle-ci est marquée failed.

        Args:
            collection_ids: Liste des IDs a vider

        Returns:
            Dict avec success_count, failed_count, failed_ids, total_deleted_chunks
        """
        from app.common.utils.chroma_helpers import clear_collection_all_providers

        success_count = 0
        failed_ids = []
        total_deleted_chunks = 0

        logger.info(f"Bulk clear index: {len(collection_ids)} collections")

        for coll_id in collection_ids:
            try:
                result = await self.session.execute(
                    select(Collection)
                    .options(selectinload(Collection.documents))
                    .where(Collection.id == coll_id)
                )
                collection = result.unique().scalar_one_or_none()

                if not collection:
                    failed_ids.append(coll_id)
                    logger.warning(f"Bulk clear: collection {coll_id} non trouvee")
                    continue

                # 1. Vider ChromaDB (tous les providers)
                deleted_chunk_count = 0
                if self.chroma:
                    try:
                        deleted_chunk_count = clear_collection_all_providers(self.chroma, collection.name)
                        total_deleted_chunks += deleted_chunk_count
                    except RuntimeError:
                        failed_ids.append(coll_id)
                        continue

                # 2. Mettre à jour les compteurs des documents
                for doc in (collection.documents or []):
                    doc.chunk_count = 0
                    doc.embedding_count = 0
                    doc.is_indexed = False

                # 3. Reset compteur collection
                collection.chunk_count = 0
                await self.session.commit()

                success_count += 1
                logger.info(f"Collection {collection.name}: index vidé ({deleted_chunk_count} chunks)")

            except Exception as e:
                await self.session.rollback()
                failed_ids.append(coll_id)
                logger.error(f"Bulk clear: erreur pour {coll_id}: {e}")

        logger.info(f"Bulk clear termine: {success_count} succes, {len(failed_ids)} echecs, {total_deleted_chunks} chunks supprimes")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids,
            "total_deleted_chunks": total_deleted_chunks
        }

    # ========================================================================
    # SYNC OPERATIONS - Synchronisation des compteurs
    # ========================================================================

    async def sync_collection(self, collection_id: UUID) -> dict:
        """
        Synchronise les compteurs d'une collection avec les données réelles.

        - Recompte les documents dans PostgreSQL
        - Recompte les chunks dans ChromaDB
        - Met à jour les compteurs de la collection

        Args:
            collection_id: ID de la collection à synchroniser

        Returns:
            Dict avec anciens/nouveaux compteurs
        """
        # Récupérer la collection
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        old_doc_count = collection.document_count
        old_chunk_count = collection.chunk_count

        # Compter les documents PostgreSQL liés à cette collection
        doc_count_result = await self.session.execute(
            select(func.count(Document.id)).where(Document.collection_id == collection_id)
        )
        new_doc_count = doc_count_result.scalar() or 0

        # Compter les chunks dans ChromaDB (avec fallback sur nom de base)
        new_chunk_count = 0
        if self.chroma:
            chroma_name = await self._get_chroma_collection_name(collection.name)
            chroma_coll = None
            try:
                chroma_coll = self.chroma.get_collection(name=chroma_name)
            except Exception:
                # Fallback: essayer le nom de base
                try:
                    chroma_coll = self.chroma.get_collection(name=collection.name)
                except Exception:
                    pass
            if chroma_coll:
                try:
                    new_chunk_count = chroma_coll.count()
                except Exception as e:
                    logger.warning(f"Sync: impossible de compter les chunks ChromaDB pour {collection.name}: {e}")

        # Mettre à jour les compteurs
        collection.document_count = new_doc_count
        collection.chunk_count = new_chunk_count
        await self.session.commit()

        logger.info(
            f"Collection {collection.name} synchronisée: "
            f"docs {old_doc_count} -> {new_doc_count}, "
            f"chunks {old_chunk_count} -> {new_chunk_count}"
        )

        return {
            "collection_id": collection_id,
            "collection_name": collection.name,
            "old_document_count": old_doc_count,
            "new_document_count": new_doc_count,
            "old_chunk_count": old_chunk_count,
            "new_chunk_count": new_chunk_count,
            "synced": True
        }

    async def sync_all_collections(self) -> dict:
        """
        Synchronise les compteurs de toutes les collections.

        Returns:
            Dict avec statistiques de synchronisation
        """
        # Récupérer toutes les collections
        result = await self.session.execute(select(Collection))
        collections = list(result.scalars().all())

        synced_count = 0
        failed_count = 0
        failed_ids = []
        total_docs_delta = 0
        total_chunks_delta = 0

        for collection in collections:
            try:
                sync_result = await self.sync_collection(collection.id)
                synced_count += 1
                total_docs_delta += sync_result["new_document_count"] - sync_result["old_document_count"]
                total_chunks_delta += sync_result["new_chunk_count"] - sync_result["old_chunk_count"]
            except Exception as e:
                failed_count += 1
                failed_ids.append(collection.id)
                logger.error(f"Sync all: erreur pour {collection.name}: {e}")

        logger.info(
            f"Sync all terminé: {synced_count} synchronisées, {failed_count} échecs, "
            f"delta docs: {total_docs_delta:+d}, delta chunks: {total_chunks_delta:+d}"
        )

        return {
            "synced_count": synced_count,
            "failed_count": failed_count,
            "failed_ids": failed_ids,
            "total_documents_delta": total_docs_delta,
            "total_chunks_delta": total_chunks_delta,
            "message": f"{synced_count} collections synchronisées"
        }

    # ========================================================================
    # COLLECTION SOURCES - Gestion des liaisons sources <-> collections
    # ========================================================================

    async def list_collection_sources(
        self, collection_id: UUID
    ) -> CollectionSourcesListResponse:
        """
        Liste toutes les sources assignées à une collection.

        Args:
            collection_id: ID de la collection

        Returns:
            CollectionSourcesListResponse avec la liste des sources
        """
        # Vérifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        # Récupérer les liaisons avec les sources
        result = await self.session.execute(
            select(CollectionSource, ContextSource)
            .join(ContextSource, CollectionSource.source_id == ContextSource.id)
            .where(CollectionSource.collection_id == collection_id)
            .order_by(CollectionSource.priority, ContextSource.display_name)
        )
        rows = result.all()

        sources = []
        for link, source in rows:
            sources.append(CollectionSourceRead(
                id=link.id,
                collection_id=link.collection_id,
                source_id=link.source_id,
                source_name=source.name,
                source_display_name=source.display_name,
                source_type=source.source_type,
                priority=link.priority,
                is_enabled=link.is_enabled,
                source_health_status=source.health_status,
                created_at=link.created_at,
            ))

        return CollectionSourcesListResponse(
            collection_id=collection.id,
            collection_name=collection.name,
            sources=sources,
            total=len(sources),
        )

    async def add_source_to_collection(
        self, collection_id: UUID, data: CollectionSourceCreate
    ) -> CollectionSourceRead:
        """
        Ajoute une source à une collection.

        Args:
            collection_id: ID de la collection
            data: CollectionSourceCreate avec source_id, priority, is_enabled

        Returns:
            CollectionSourceRead de la liaison créée
        """
        # Vérifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        # Vérifier que la source existe
        source_result = await self.session.execute(
            select(ContextSource).where(ContextSource.id == data.source_id)
        )
        source = source_result.scalar_one_or_none()
        if not source:
            raise HTTPException(status_code=404, detail="Source non trouvée")

        # Vérifier que la liaison n'existe pas déjà
        existing = await self.session.execute(
            select(CollectionSource).where(
                CollectionSource.collection_id == collection_id,
                CollectionSource.source_id == data.source_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"La source '{source.display_name}' est déjà assignée à cette collection"
            )

        # Créer la liaison
        link = CollectionSource(
            collection_id=collection_id,
            source_id=data.source_id,
            priority=data.priority,
            is_enabled=data.is_enabled,
        )
        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)

        logger.info(
            f"Source '{source.name}' ajoutée à collection '{collection.name}' "
            f"(priorité: {data.priority}, activée: {data.is_enabled})"
        )

        return CollectionSourceRead(
            id=link.id,
            collection_id=link.collection_id,
            source_id=link.source_id,
            source_name=source.name,
            source_display_name=source.display_name,
            source_type=source.source_type,
            priority=link.priority,
            is_enabled=link.is_enabled,
            source_health_status=source.health_status,
            created_at=link.created_at,
        )

    async def remove_source_from_collection(
        self, collection_id: UUID, source_id: UUID
    ) -> bool:
        """
        Retire une source d'une collection.

        Args:
            collection_id: ID de la collection
            source_id: ID de la source à retirer

        Returns:
            True si supprimé
        """
        # Trouver la liaison
        result = await self.session.execute(
            select(CollectionSource).where(
                CollectionSource.collection_id == collection_id,
                CollectionSource.source_id == source_id
            )
        )
        link = result.scalar_one_or_none()

        if not link:
            raise HTTPException(
                status_code=404,
                detail="Liaison source-collection non trouvée"
            )

        await self.session.delete(link)
        await self.session.commit()

        logger.info(f"Source {source_id} retirée de collection {collection_id}")
        return True

    async def update_collection_source(
        self, collection_id: UUID, source_id: UUID, data: CollectionSourceUpdate
    ) -> CollectionSourceRead:
        """
        Met à jour une liaison source-collection (priorité, activation).

        Args:
            collection_id: ID de la collection
            source_id: ID de la source
            data: CollectionSourceUpdate avec priority et/ou is_enabled

        Returns:
            CollectionSourceRead mis à jour
        """
        # Trouver la liaison avec la source
        result = await self.session.execute(
            select(CollectionSource, ContextSource)
            .join(ContextSource, CollectionSource.source_id == ContextSource.id)
            .where(
                CollectionSource.collection_id == collection_id,
                CollectionSource.source_id == source_id
            )
        )
        row = result.one_or_none()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Liaison source-collection non trouvée"
            )

        link, source = row

        # Mettre à jour les champs fournis
        if data.priority is not None:
            link.priority = data.priority
        if data.is_enabled is not None:
            link.is_enabled = data.is_enabled

        await self.session.commit()
        await self.session.refresh(link)

        logger.info(
            f"Liaison source '{source.name}' -> collection {collection_id} mise à jour: "
            f"priorité={link.priority}, activée={link.is_enabled}"
        )

        return CollectionSourceRead(
            id=link.id,
            collection_id=link.collection_id,
            source_id=link.source_id,
            source_name=source.name,
            source_display_name=source.display_name,
            source_type=source.source_type,
            priority=link.priority,
            is_enabled=link.is_enabled,
            source_health_status=source.health_status,
            created_at=link.created_at,
        )

    async def list_available_sources_for_collection(
        self, collection_id: UUID
    ) -> List[dict]:
        """
        Liste les sources NON assignées à une collection (disponibles pour ajout).

        Args:
            collection_id: ID de la collection

        Returns:
            Liste de sources disponibles
        """
        # Vérifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        if not coll_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        # Récupérer les IDs des sources déjà assignées
        assigned_result = await self.session.execute(
            select(CollectionSource.source_id).where(
                CollectionSource.collection_id == collection_id
            )
        )
        assigned_ids = {row[0] for row in assigned_result.all()}

        # Récupérer toutes les sources actives non assignées
        sources_result = await self.session.execute(
            select(ContextSource)
            .where(ContextSource.is_enabled == True)
            .order_by(ContextSource.display_name)
        )
        all_sources = sources_result.scalars().all()

        available = []
        for source in all_sources:
            if source.id not in assigned_ids:
                available.append({
                    "id": str(source.id),
                    "name": source.name,
                    "display_name": source.display_name,
                    "source_type": source.source_type,
                    "health_status": source.health_status,
                })

        return available

    # ========================================================================
    # COLLECTION CORPUS - Gestion des corpus auxquels appartient la collection
    # ========================================================================

    async def list_collection_corpus(self, collection_id: UUID) -> List[dict]:
        """
        Liste tous les corpus auxquels appartient une collection.

        Args:
            collection_id: ID de la collection

        Returns:
            Liste des corpus avec priorite
        """
        # Verifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # Recuperer les corpus de cette collection
        result = await self.session.execute(
            select(CorpusCollection, Corpus)
            .join(Corpus, CorpusCollection.corpus_id == Corpus.id)
            .where(CorpusCollection.collection_id == collection_id)
            .order_by(CorpusCollection.priority, Corpus.display_name)
        )
        rows = result.all()

        corpus_list = []
        for membership, corpus in rows:
            corpus_list.append({
                "id": str(corpus.id),
                "name": corpus.name,
                "display_name": corpus.display_name,
                "description": corpus.description,
                "is_active": corpus.is_active,
                "priority": membership.priority,
                "membership_id": str(membership.id),
                "created_at": membership.created_at.isoformat(),
            })

        return corpus_list

    async def list_available_corpus_for_collection(self, collection_id: UUID) -> List[dict]:
        """
        Liste les corpus NON assignes a une collection (disponibles pour ajout).

        Args:
            collection_id: ID de la collection

        Returns:
            Liste de corpus disponibles
        """
        # Verifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        if not coll_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # Recuperer les IDs des corpus deja assignes
        assigned_result = await self.session.execute(
            select(CorpusCollection.corpus_id).where(
                CorpusCollection.collection_id == collection_id
            )
        )
        assigned_ids = {row[0] for row in assigned_result.all()}

        # Recuperer tous les corpus actifs non assignes
        corpus_result = await self.session.execute(
            select(Corpus)
            .where(Corpus.is_active == True)
            .order_by(Corpus.display_name)
        )
        all_corpus = corpus_result.scalars().all()

        available = []
        for corpus in all_corpus:
            if corpus.id not in assigned_ids:
                available.append({
                    "id": str(corpus.id),
                    "name": corpus.name,
                    "display_name": corpus.display_name,
                    "description": corpus.description,
                })

        return available

    async def add_collection_to_corpus(
        self, collection_id: UUID, corpus_id: UUID, priority: int = 100
    ) -> dict:
        """
        Ajoute une collection a un corpus.

        Args:
            collection_id: ID de la collection
            corpus_id: ID du corpus
            priority: Priorite (1=haute, 1000=basse)

        Returns:
            Dict avec details de la liaison
        """
        # Verifier que la collection existe
        coll_result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = coll_result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvee")

        # Verifier que le corpus existe
        corpus_result = await self.session.execute(
            select(Corpus).where(Corpus.id == corpus_id)
        )
        corpus = corpus_result.scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouve")

        # Verifier que la liaison n'existe pas deja
        existing = await self.session.execute(
            select(CorpusCollection).where(
                CorpusCollection.collection_id == collection_id,
                CorpusCollection.corpus_id == corpus_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"La collection '{collection.display_name}' est deja dans le corpus '{corpus.display_name}'"
            )

        # Creer la liaison
        membership = CorpusCollection(
            collection_id=collection_id,
            corpus_id=corpus_id,
            priority=priority,
        )
        self.session.add(membership)
        await self.session.commit()
        await self.session.refresh(membership)

        logger.info(
            f"Collection '{collection.name}' ajoutee au corpus '{corpus.name}' "
            f"(priorite: {priority})"
        )

        return {
            "id": str(membership.id),
            "collection_id": str(collection_id),
            "corpus_id": str(corpus_id),
            "corpus_name": corpus.name,
            "corpus_display_name": corpus.display_name,
            "priority": priority,
            "created_at": membership.created_at.isoformat(),
        }

    async def remove_collection_from_corpus(
        self, collection_id: UUID, corpus_id: UUID
    ) -> bool:
        """
        Retire une collection d'un corpus.

        Args:
            collection_id: ID de la collection
            corpus_id: ID du corpus

        Returns:
            True si supprime
        """
        # Trouver la liaison
        result = await self.session.execute(
            select(CorpusCollection).where(
                CorpusCollection.collection_id == collection_id,
                CorpusCollection.corpus_id == corpus_id
            )
        )
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=404,
                detail="Liaison collection-corpus non trouvee"
            )

        await self.session.delete(membership)
        await self.session.commit()

        logger.info(f"Collection {collection_id} retiree du corpus {corpus_id}")
        return True

    async def bulk_add_collection_to_corpus(
        self, collection_id: UUID, corpus_ids: List[UUID], priority: int = 100
    ) -> dict:
        """
        Ajoute une collection a plusieurs corpus en masse.

        Args:
            collection_id: ID de la collection
            corpus_ids: Liste des IDs de corpus
            priority: Priorite pour tous

        Returns:
            Dict avec success_count, error_count, errors
        """
        success_count = 0
        error_count = 0
        errors = []

        for corpus_id in corpus_ids:
            try:
                await self.add_collection_to_corpus(collection_id, corpus_id, priority)
                success_count += 1
            except HTTPException as e:
                error_count += 1
                errors.append(f"{corpus_id}: {e.detail}")
            except Exception as e:
                error_count += 1
                errors.append(f"{corpus_id}: {str(e)}")

        return {
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors,
        }

    async def bulk_remove_collection_from_corpus(
        self, collection_id: UUID, corpus_ids: List[UUID]
    ) -> dict:
        """
        Retire une collection de plusieurs corpus en masse.

        Args:
            collection_id: ID de la collection
            corpus_ids: Liste des IDs de corpus

        Returns:
            Dict avec success_count, error_count, errors
        """
        success_count = 0
        error_count = 0
        errors = []

        for corpus_id in corpus_ids:
            try:
                await self.remove_collection_from_corpus(collection_id, corpus_id)
                success_count += 1
            except HTTPException as e:
                error_count += 1
                errors.append(f"{corpus_id}: {e.detail}")
            except Exception as e:
                error_count += 1
                errors.append(f"{corpus_id}: {str(e)}")

        return {
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors,
        }

    # === Provider Index Status ===

    async def get_collection_index_status(
        self, collection_id: UUID
    ) -> CollectionIndexStatusResponse:
        """
        Retourne l'état d'indexation d'une collection pour tous les providers.

        Vérifie l'existence et le nombre de chunks dans ChromaDB pour chaque
        provider (ollama, llamacpp).

        Args:
            collection_id: UUID de la collection

        Returns:
            CollectionIndexStatusResponse avec statut par provider
        """
        # Récupérer la collection
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        # Provider actif
        config_service = SystemConfigService(self.session)
        active_provider = await config_service.get("llm.provider", settings.llm_provider)

        providers_status = []
        for provider in ["ollama", "llamacpp"]:
            chroma_name = f"{collection.name}_{provider}"
            chunk_count = 0
            exists = False
            embedding_model = None

            if self.chroma:
                try:
                    coll = self.chroma.get_collection(name=chroma_name)
                    chunk_count = coll.count()
                    exists = True
                    # Récupérer le modèle depuis les métadonnées si disponible
                    metadata = coll.metadata or {}
                    embedding_model = metadata.get("embedding_model")
                except Exception:
                    # Essayer le nom de base pour rétrocompatibilité
                    if provider == active_provider:
                        try:
                            coll = self.chroma.get_collection(name=collection.name)
                            chunk_count = coll.count()
                            exists = True
                        except Exception:
                            pass

            providers_status.append(ProviderIndexStatus(
                provider=provider,
                collection_exists=exists,
                chunk_count=chunk_count,
                embedding_model=embedding_model
            ))

        return CollectionIndexStatusResponse(
            collection_id=collection.id,
            collection_name=collection.name,
            display_name=collection.display_name,
            providers=providers_status,
            active_provider=active_provider
        )

    async def reindex_collection_for_provider(
        self, collection_id: UUID, provider: str, force: bool = False
    ) -> ReindexResponse:
        """
        Alias de prepare_collection_reindex pour compatibilité.
        """
        return await self.prepare_collection_reindex(collection_id, provider, force)

    async def prepare_collection_reindex(
        self, collection_id: UUID, provider: str, force: bool = False
    ) -> ReindexResponse:
        """
        Prépare la réindexation d'une collection pour un provider spécifique.

        Ne fait PAS la réindexation elle-même, mais retourne les IDs des documents
        à réindexer pour que le routeur puisse lancer les tâches de fond.

        Args:
            collection_id: UUID de la collection
            provider: Provider cible ("ollama" ou "llamacpp")
            force: Forcer la réindexation même si déjà indexé

        Returns:
            ReindexResponse avec document_ids pour la réindexation async
        """
        if provider not in ("ollama", "llamacpp"):
            raise HTTPException(
                status_code=400,
                detail=f"Provider invalide: {provider}. Utilisez 'ollama' ou 'llamacpp'."
            )

        # Récupérer la collection
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection non trouvée")

        chroma_name = f"{collection.name}_{provider}"

        # Vérifier si déjà indexé
        if not force and self.chroma:
            try:
                coll = self.chroma.get_collection(name=chroma_name)
                if coll.count() > 0:
                    return ReindexResponse(
                        collection_id=collection.id,
                        collection_name=collection.name,
                        provider=provider,
                        status="skipped",
                        documents_count=0,
                        sources_count=0,
                        message=f"Collection déjà indexée pour {provider} ({coll.count()} chunks). Utilisez force=true pour réindexer.",
                        document_ids=[],
                        source_ids=[]
                    )
            except Exception:
                pass  # Collection n'existe pas, on peut continuer

        # Récupérer tous les documents de la collection
        # Note: Les documents peuvent être liés soit directement à la collection,
        # soit via le corpus de la collection
        documents = []
        sources = []

        # 1. Documents liés directement à la collection
        docs_result = await self.session.execute(
            select(Document).where(Document.collection_id == collection_id)
        )
        documents.extend(docs_result.scalars().all())

        # 2. Documents et sources liés via le corpus de la collection
        if collection.corpus_id:
            # Documents du corpus (via table pivot corpus_documents)
            corpus_docs_result = await self.session.execute(
                select(Document)
                .join(CorpusDocument, CorpusDocument.document_id == Document.id)
                .where(CorpusDocument.corpus_id == collection.corpus_id)
            )
            for doc in corpus_docs_result.scalars().all():
                if doc not in documents:  # Éviter les doublons
                    documents.append(doc)

            # Sources du corpus (via table de liaison corpus_sources)
            sources_result = await self.session.execute(
                select(ContextSource)
                .join(CorpusSource, CorpusSource.source_id == ContextSource.id)
                .where(CorpusSource.corpus_id == collection.corpus_id)
                .where(CorpusSource.is_enabled == True)
            )
            sources = sources_result.scalars().all()

        total_items = len(documents) + len(sources)

        if total_items == 0:
            return ReindexResponse(
                collection_id=collection.id,
                collection_name=collection.name,
                provider=provider,
                status="completed",
                documents_count=0,
                message="Aucun document ni source à indexer dans cette collection",
                document_ids=[],
                source_ids=[]
            )

        # Retourner les IDs pour la réindexation async
        document_ids = [doc.id for doc in documents]
        source_ids = [src.id for src in sources]
        logger.info(
            f"Réindexation préparée pour collection {collection.name} "
            f"vers provider {provider}: {len(documents)} documents, {len(sources)} sources"
        )

        return ReindexResponse(
            collection_id=collection.id,
            collection_name=collection.name,
            provider=provider,
            status="started",
            documents_count=len(documents),
            sources_count=len(sources),
            message=f"Réindexation lancée pour {len(documents)} document(s) et {len(sources)} source(s) vers {provider}",
            document_ids=document_ids,
            source_ids=source_ids
        )
