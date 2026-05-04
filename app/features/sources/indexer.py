"""
Service d'indexation des sources externes dans ChromaDB

Permet de stocker les résultats des sources externes pour éviter
des appels répétés et permettre une recherche sémantique unifiée.
Supporte le chunking pour améliorer la qualité des recherches RAG.
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, Union, Callable, Awaitable
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_chroma_client
from app.common.utils.ollama import get_embeddings
from app.common.utils.rag_config import get_rag_config
from app.features.sources.schemas import ContextResult
from app.features.system.service import SystemConfigService
from app.common.llm import OllamaProvider, LlamaCppProvider

logger = logging.getLogger(__name__)


class SourceIndexer:
    """Service d'indexation des résultats de sources externes dans ChromaDB"""

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[str]:
        """
        Découpe un texte en chunks pour l'indexation.

        Args:
            text: Texte à découper
            chunk_size: Taille maximale d'un chunk en caractères
            chunk_overlap: Chevauchement entre les chunks

        Returns:
            Liste des chunks de texte
        """
        if not text or len(text) <= chunk_size:
            return [text] if text else []

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", ", ", " ", ""]
        )

        chunks = splitter.split_text(text)
        return chunks

    @staticmethod
    async def get_config(db: AsyncSession) -> Dict[str, Any]:
        """Récupère la configuration d'indexation depuis la BDD"""
        config_service = SystemConfigService(db)
        provider = await config_service.get("llm.provider", "ollama")
        base_collection = await config_service.get("sources.collection_name", "external_sources")
        config = {
            "index_results": await config_service.get("sources.index_results", True),
            "index_ttl_hours": await config_service.get("sources.index_ttl_hours", 24),
            "collection_name": f"{base_collection}_{provider}",  # Suffixé avec provider
            "base_collection_name": base_collection,  # Nom de base sans suffix
            "provider": provider,
            "min_context_results": await config_service.get("sources.min_context_results", 3),
            "min_similarity": await config_service.get("sources.min_similarity", 0.6),
        }
        return config

    @staticmethod
    async def get_or_create_collection(collection_name: str = "external_sources"):
        """Récupère ou crée la collection pour les sources externes"""
        chroma_client = get_chroma_client()
        if chroma_client is None:
            logger.error("ChromaDB client not initialized")
            return None

        try:
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "description": "Indexed external sources results",
                    "hnsw:space": "cosine",           # Distance cosine pour similarité
                    "hnsw:M": 16,                     # Connexions par noeud
                    "hnsw:construction_ef": 100,      # Qualité construction index
                    "hnsw:search_ef": 50              # Qualité recherche (équilibre)
                }
            )
            return collection
        except Exception as e:
            logger.error(f"Error getting/creating collection '{collection_name}': {e}")
            return None

    @staticmethod
    async def reset_collection(collection_name: str = "external_sources"):
        """
        Supprime et recrée la collection ChromaDB.

        Nécessaire quand la dimension des embeddings change
        (ex: changement de modèle d'embedding).

        Args:
            collection_name: Nom de la collection à recréer

        Returns:
            La nouvelle collection ChromaDB ou None
        """
        chroma_client = get_chroma_client()
        if chroma_client is None:
            raise RuntimeError("ChromaDB client not initialized")

        try:
            chroma_client.delete_collection(name=collection_name)
            logger.warning(
                f"ChromaDB collection '{collection_name}' deleted (dimension mismatch)"
            )
        except Exception:
            pass  # Collection n'existe peut-être pas

        return await SourceIndexer.get_or_create_collection(collection_name)

    @staticmethod
    async def index_results(
        db: AsyncSession,
        results: List[ContextResult],
        query: str,
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
        provider: Optional[str] = None
    ) -> int:
        """
        Indexe les résultats de sources externes dans ChromaDB avec chunking.

        Args:
            db: Session de base de données
            results: Résultats à indexer
            query: Requête originale qui a généré ces résultats
            progress_callback: Callback async(current, total) pour le suivi de progression
            provider: Provider à utiliser pour les embeddings ('ollama' ou 'llamacpp').
                     Si None, utilise le provider configuré globalement.

        Returns:
            Nombre de chunks indexés
        """
        if not results:
            return 0

        config = await SourceIndexer.get_config(db)

        if not config["index_results"]:
            logger.debug("Indexation des sources désactivée")
            return 0

        collection_name = config["collection_name"]
        ttl_hours = config["index_ttl_hours"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return 0

        # Charger la config RAG pour le modèle d'embedding et les paramètres de chunking
        rag_config = await get_rag_config(db)
        chunk_size = rag_config.chunk_size
        chunk_overlap = rag_config.chunk_overlap

        # Créer une instance du provider spécifié pour les embeddings
        embedding_provider = None
        if provider == "ollama":
            embedding_provider = OllamaProvider()
            logger.info(f"Using Ollama provider for embeddings")
        elif provider == "llamacpp":
            embedding_provider = LlamaCppProvider()
            logger.info(f"Using llama.cpp provider for embeddings")
        else:
            logger.info(f"Using default provider for embeddings")

        chunks_indexed = 0
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=ttl_hours)

        try:
            for result_idx, result in enumerate(results):
                try:
                    # Découper le contenu en chunks
                    chunks = SourceIndexer.chunk_text(
                        result.content,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap
                    )

                    if not chunks:
                        continue

                    # ID de base pour ce document
                    doc_base_id = f"ext_{result.source_name}_{uuid4().hex[:8]}"

                    for chunk_idx, chunk_text in enumerate(chunks):
                        try:
                            # Générer l'embedding du chunk avec le provider spécifié
                            if embedding_provider:
                                response = await embedding_provider.get_embeddings(
                                    chunk_text, model=rag_config.embedding_model
                                )
                                embedding = response.embedding
                            else:
                                embedding = await get_embeddings(chunk_text, model=rag_config.embedding_model)

                            # Créer l'ID unique pour ce chunk
                            chunk_id = f"{doc_base_id}_c{chunk_idx}"

                            # Métadonnées
                            # display_name pour l'affichage UI, source_name pour l'indexation
                            display = result.display_name or result.source_name
                            metadata = {
                                "source_name": result.source_name,
                                "display_name": display,
                                "source_type": result.source_type.value,
                                "source_url": result.source_url or "",
                                "query": query[:500],  # Limiter la taille
                                "indexed_at": now.isoformat(),
                                "expires_at": expires_at.isoformat(),
                                "visibility": "public",  # Sources externes sont publiques
                                "chunk_index": chunk_idx,
                                "total_chunks": len(chunks),
                                "doc_id": doc_base_id,
                            }

                            # Ajouter les métadonnées supplémentaires
                            if result.metadata:
                                for key, value in result.metadata.items():
                                    if isinstance(value, (str, int, float, bool)):
                                        metadata[f"meta_{key}"] = value

                            # Indexer dans ChromaDB (avec gestion du changement de dimension)
                            try:
                                collection.add(
                                    ids=[chunk_id],
                                    embeddings=[embedding],
                                    documents=[chunk_text],
                                    metadatas=[metadata]
                                )
                            except Exception as dim_err:
                                if "dimension" in str(dim_err).lower():
                                    logger.warning(
                                        f"Dimension mismatch detected, resetting collection: {dim_err}"
                                    )
                                    collection = await SourceIndexer.reset_collection(collection_name)
                                    if collection is None:
                                        raise RuntimeError(
                                            "Failed to recreate ChromaDB collection after dimension mismatch"
                                        )
                                    # Retry après reset de la collection
                                    collection.add(
                                        ids=[chunk_id],
                                        embeddings=[embedding],
                                        documents=[chunk_text],
                                        metadatas=[metadata]
                                    )
                                else:
                                    raise

                            chunks_indexed += 1
                            logger.debug(f"Indexed chunk {chunk_idx + 1}/{len(chunks)}: {chunk_id}")

                        except Exception as e:
                            logger.error(f"Error indexing chunk {chunk_idx} from {result.source_name}: {e}")
                            continue

                    # Notifier la progression après chaque résultat traité
                    if progress_callback:
                        await progress_callback(result_idx + 1, len(results))

                except Exception as e:
                    logger.error(f"Error processing result from {result.source_name}: {e}")
                    continue
        finally:
            # Fermer le provider si on l'a créé
            if embedding_provider:
                await embedding_provider.close()

        logger.info(f"Indexed {chunks_indexed} chunks from {len(results)} source results")
        return chunks_indexed

    @staticmethod
    async def search_indexed_sources(
        db: AsyncSession,
        query: str,
        top_k: int = 5,
        similarity_threshold: Optional[float] = None,
        source_names: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Recherche dans les sources externes indexées.

        Args:
            db: Session de base de données
            query: Requête de recherche
            top_k: Nombre de résultats max
            similarity_threshold: Seuil de similarité minimum
            source_names: Liste des noms de sources à filtrer (None = toutes)

        Returns:
            Liste de résultats avec contenu et métadonnées
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        if similarity_threshold is None:
            similarity_threshold = config["min_similarity"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return []

        try:
            # Vérifier si la collection a des documents
            if collection.count() == 0:
                logger.debug("External sources collection is empty")
                return []

            # Charger la config RAG pour le modèle d'embedding
            rag_config = await get_rag_config(db)

            # Générer l'embedding de la requête
            query_embedding = await get_embeddings(query, model=rag_config.embedding_model)

            # Date actuelle pour filtrage d'expiration (en Python, pas ChromaDB)
            now = datetime.now(timezone.utc).isoformat()

            # Construire le filtre ChromaDB - uniquement source_names (filtrage date en Python)
            where_filter: Optional[Dict[str, Any]] = None

            # Filtre par source_names si spécifié
            if source_names and len(source_names) > 0:
                if len(source_names) == 1:
                    where_filter = {"source_name": {"$eq": source_names[0]}}
                else:
                    where_filter = {"source_name": {"$in": source_names}}
                logger.debug(f"Filtering indexed sources by names: {source_names}")

            # Recherche avec filtre source_names (expiration filtrée en Python)
            # Inclure embeddings pour permettre la déduplication sémantique
            try:
                if where_filter:
                    results_data = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=top_k * 3,  # Fetch more to filter expired in Python
                        where=where_filter,
                        include=["documents", "metadatas", "distances", "embeddings"]
                    )
                else:
                    results_data = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=top_k * 3,
                        include=["documents", "metadatas", "distances", "embeddings"]
                    )
            except Exception as e:
                # Fallback sans filtre si erreur
                logger.warning(f"Query with filter failed ({e}), fallback without filter")
                results_data = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k * 3,
                    include=["documents", "metadatas", "distances", "embeddings"]
                )

            results = []
            if results_data.get("documents") and results_data["documents"][0]:
                for i, doc in enumerate(results_data["documents"][0]):
                    metadata = results_data.get("metadatas", [[]])[0][i] if results_data.get("metadatas") else {}
                    distance = results_data.get("distances", [[]])[0][i] if results_data.get("distances") else None
                    embedding = results_data.get("embeddings", [[]])[0][i] if results_data.get("embeddings") else None

                    # Calculer la similarité
                    similarity = 1 - (distance / 2) if distance is not None else 0

                    # Filtrer par seuil
                    if similarity < similarity_threshold:
                        continue

                    # Vérifier l'expiration manuellement
                    expires_at = metadata.get("expires_at")
                    if expires_at and expires_at < now:
                        continue

                    result_item = {
                        "content": doc,
                        "metadata": metadata,
                        "distance": distance,
                        "similarity": similarity,
                        "source_type": "external_indexed"
                    }
                    # Ajouter l'embedding pour la déduplication sémantique
                    if embedding is not None:
                        result_item["embedding"] = embedding

                    results.append(result_item)

                    if len(results) >= top_k:
                        break

            logger.debug(f"Found {len(results)} indexed external source results")
            return results

        except Exception as e:
            logger.error(f"Error searching indexed sources: {e}")
            return []

    @staticmethod
    async def cleanup_expired(db: AsyncSession) -> int:
        """
        Supprime les documents expirés de la collection.

        Args:
            db: Session de base de données

        Returns:
            Nombre de documents supprimés
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return 0

        try:
            now = datetime.now(timezone.utc).isoformat()

            # Récupérer les IDs des documents expirés
            # ChromaDB ne supporte pas bien les requêtes complexes, on fait en 2 temps
            all_docs = collection.get(include=["metadatas"])

            expired_ids = []
            if all_docs.get("ids"):
                for i, doc_id in enumerate(all_docs["ids"]):
                    metadata = all_docs.get("metadatas", [])[i] if all_docs.get("metadatas") else {}
                    expires_at = metadata.get("expires_at")
                    if expires_at and expires_at < now:
                        expired_ids.append(doc_id)

            if expired_ids:
                collection.delete(ids=expired_ids)
                logger.info(f"Cleaned up {len(expired_ids)} expired external source documents")

            return len(expired_ids)

        except Exception as e:
            logger.error(f"Error cleaning up expired sources: {e}")
            return 0

    @staticmethod
    async def get_stats(db: AsyncSession) -> Dict[str, Any]:
        """
        Retourne les statistiques de la collection de sources indexées.

        Args:
            db: Session de base de données

        Returns:
            Dictionnaire avec les statistiques
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return {"error": "Collection not available"}

        try:
            total_count = collection.count()

            # Compter par source_type
            all_docs = collection.get(include=["metadatas"])
            type_counts = {}
            source_counts = {}
            expired_count = 0
            now = datetime.now(timezone.utc).isoformat()

            if all_docs.get("metadatas"):
                for metadata in all_docs["metadatas"]:
                    # Par type
                    source_type = metadata.get("source_type", "unknown")
                    type_counts[source_type] = type_counts.get(source_type, 0) + 1

                    # Par source
                    source_name = metadata.get("source_name", "unknown")
                    source_counts[source_name] = source_counts.get(source_name, 0) + 1

                    # Expirés
                    if metadata.get("expires_at", "") < now:
                        expired_count += 1

            return {
                "collection_name": collection_name,
                "total_documents": total_count,
                "by_type": type_counts,
                "by_source": source_counts,
                "expired_count": expired_count,
                "config": {
                    "index_enabled": config["index_results"],
                    "ttl_hours": config["index_ttl_hours"],
                    "min_similarity": config["min_similarity"],
                }
            }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}

    @staticmethod
    async def get_source_stats(db: AsyncSession, source_name: str) -> Dict[str, Any]:
        """
        Retourne les statistiques d'indexation pour une source spécifique.

        Args:
            db: Session de base de données
            source_name: Nom technique de la source

        Returns:
            Dictionnaire avec les statistiques de la source
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return {
                "source_name": source_name,
                "indexed_count": 0,
                "expired_count": 0,
                "last_indexed_at": None,
                "index_enabled": config["index_results"],
                "ttl_hours": config["index_ttl_hours"]
            }

        try:
            # Récupérer tous les documents de cette source
            all_docs = collection.get(include=["metadatas"])

            indexed_count = 0
            expired_count = 0
            last_indexed_at = None
            now = datetime.now(timezone.utc).isoformat()

            if all_docs.get("metadatas"):
                for metadata in all_docs["metadatas"]:
                    if metadata.get("source_name") == source_name:
                        indexed_count += 1

                        # Vérifier expiration
                        if metadata.get("expires_at", "") < now:
                            expired_count += 1

                        # Trouver la date d'indexation la plus récente
                        indexed_at = metadata.get("indexed_at")
                        if indexed_at:
                            if last_indexed_at is None or indexed_at > last_indexed_at:
                                last_indexed_at = indexed_at

            return {
                "source_name": source_name,
                "indexed_count": indexed_count,
                "valid_count": indexed_count - expired_count,
                "expired_count": expired_count,
                "last_indexed_at": last_indexed_at,
                "index_enabled": config["index_results"],
                "ttl_hours": config["index_ttl_hours"]
            }

        except Exception as e:
            logger.error(f"Error getting source stats for {source_name}: {e}")
            return {
                "source_name": source_name,
                "indexed_count": 0,
                "expired_count": 0,
                "last_indexed_at": None,
                "index_enabled": config["index_results"],
                "ttl_hours": config["index_ttl_hours"],
                "error": str(e)
            }

    @staticmethod
    async def delete_source_documents(db: AsyncSession, source_name: str, max_retries: int = 3) -> int:
        """
        Supprime tous les documents indexés pour une source spécifique.

        Utilise un mécanisme de retry avec backoff exponentiel et
        suppression par batches pour fiabiliser le nettoyage ChromaDB.

        Args:
            db: Session de base de données
            source_name: Nom technique de la source
            max_retries: Nombre maximum de tentatives (défaut: 3)

        Returns:
            Nombre de documents supprimés

        Raises:
            RuntimeError: Si la suppression échoue après toutes les tentatives
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            raise RuntimeError(f"Collection ChromaDB '{collection_name}' inaccessible")

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                # Récupérer les IDs des documents de cette source
                all_docs = collection.get(include=["metadatas"])

                source_ids = []
                if all_docs.get("ids"):
                    for i, doc_id in enumerate(all_docs["ids"]):
                        metadata = all_docs.get("metadatas", [])[i] if all_docs.get("metadatas") else {}
                        if metadata.get("source_name") == source_name:
                            source_ids.append(doc_id)

                if not source_ids:
                    return 0

                # Suppression par batches de 100 (limite ChromaDB)
                batch_size = 100
                for i in range(0, len(source_ids), batch_size):
                    batch = source_ids[i:i + batch_size]
                    collection.delete(ids=batch)

                logger.info(f"Deleted {len(source_ids)} indexed documents for source '{source_name}'")
                return len(source_ids)

            except Exception as e:
                last_error = e
                logger.warning(
                    f"ChromaDB cleanup attempt {attempt}/{max_retries} failed for "
                    f"source '{source_name}': {e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        # Toutes les tentatives ont échoué
        error_msg = (
            f"Échec du nettoyage ChromaDB pour la source '{source_name}' "
            f"après {max_retries} tentatives: {last_error}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    @staticmethod
    async def cleanup_orphaned_documents(db: AsyncSession, existing_source_names: set[str]) -> int:
        """
        Supprime les documents ChromaDB dont le source_name n'existe plus en BDD.

        Compare les source_name présents dans la collection ChromaDB avec
        les noms de sources actives en base. Les documents orphelins sont
        supprimés par batches de 100.

        Args:
            db: Session de base de données
            existing_source_names: Set des noms de sources existantes en BDD

        Returns:
            Nombre de documents orphelins supprimés
        """
        config = await SourceIndexer.get_config(db)
        collection_name = config["collection_name"]

        collection = await SourceIndexer.get_or_create_collection(collection_name)
        if collection is None:
            return 0

        try:
            all_docs = collection.get(include=["metadatas"])
            if not all_docs.get("ids"):
                return 0

            # Identifier les documents orphelins
            orphan_ids = []
            orphan_sources = set()
            for i, doc_id in enumerate(all_docs["ids"]):
                metadata = all_docs.get("metadatas", [])[i] if all_docs.get("metadatas") else {}
                source_name = metadata.get("source_name")
                if source_name and source_name not in existing_source_names:
                    orphan_ids.append(doc_id)
                    orphan_sources.add(source_name)

            if not orphan_ids:
                return 0

            # Suppression par batches de 100
            batch_size = 100
            for i in range(0, len(orphan_ids), batch_size):
                batch = orphan_ids[i:i + batch_size]
                collection.delete(ids=batch)

            logger.info(
                f"Cleaned up {len(orphan_ids)} orphaned documents "
                f"from {len(orphan_sources)} deleted source(s): {', '.join(sorted(orphan_sources))}"
            )
            return len(orphan_ids)

        except Exception as e:
            logger.error(f"Error cleaning up orphaned documents: {e}")
            return 0
