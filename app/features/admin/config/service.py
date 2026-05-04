"""
Service Admin Config

Logique métier pour la gestion de la configuration système.
La configuration RAG est persistée en base de données (table system_configs).
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, AsyncGenerator

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import aiofiles
import httpx

from app.core.config import settings
from app.features.admin.config.schemas import (
    SystemConfigRead, RAGConfigRead, RAGConfigUpdate,
    TimeoutsConfigRead, TimeoutsConfigUpdate,
    RateLimitsConfigRead, RateLimitsConfigUpdate,
    SpeechConfigRead, SpeechConfigUpdate,
    SourcesIndexationConfigRead, SourcesIndexationConfigUpdate,
    ChatConfigRead, ChatConfigUpdate,
    DebugConfigRead, DebugConfigUpdate,
    LoggingConfigRead, LoggingConfigUpdate,
    NotificationConfigRead, NotificationConfigUpdate,
    SmtpConfigRead, SmtpConfigUpdate, SmtpTestResponse,
    LLMProviderConfigRead, LLMProviderConfigUpdate,
    ModelInfo, ModelsListResponse,
    LlamaCppParamsUpdate, OllamaConfigUpdate,
    RAGTestRequest, RAGTestResponse, RAGTestChunk, RAGStatsResponse,
    GeoConfigRead, GeoConfigUpdate
)
from app.features.system.service import SystemConfigService
from app.common.utils.security_logger import log_config_change

logger = logging.getLogger(__name__)

# Stockage des overrides runtime (en mémoire, perdus au redémarrage)
_runtime_overrides: Dict[str, Any] = {}

# Stockage des tâches de téléchargement GGUF en cours (pour polling)
_download_tasks: Dict[str, Dict[str, Any]] = {}
# Signaux d'annulation pour les tâches GGUF
_download_cancellations: Dict[str, bool] = {}

# Stockage des tâches de pull Ollama en cours (pour polling)
_ollama_pull_tasks: Dict[str, Dict[str, Any]] = {}
# Signaux d'annulation pour les tâches Ollama
_ollama_pull_cancellations: Dict[str, bool] = {}


def _apply_log_level(verbose: bool) -> str:
    """
    Change le niveau de log du root logger et des librairies externes en runtime.

    Args:
        verbose: True pour DEBUG, False pour revenir au niveau configuré

    Returns:
        Le nouveau niveau de log appliqué (ex: "DEBUG", "INFO")
    """
    if verbose:
        new_level = "DEBUG"
    else:
        new_level = settings.log_level

    # Appliquer au root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(new_level)
    for handler in root_logger.handlers:
        handler.setLevel(new_level)

    # Ajuster les loggers externes
    external_loggers = ["httpx", "httpcore", "chromadb", "sqlalchemy", "uvicorn.access"]
    if verbose:
        for name in external_loggers:
            logging.getLogger(name).setLevel(logging.DEBUG)
    else:
        for name in external_loggers:
            logging.getLogger(name).setLevel(logging.WARNING)

    logger.info(f"Log level changed to {new_level} (verbose={verbose})")
    return new_level


class ConfigService:
    """Service pour la gestion de la configuration"""

    # ========================================================================
    # LECTURE CONFIGURATION
    # ========================================================================

    @staticmethod
    async def get_system_config(db: AsyncSession) -> SystemConfigRead:
        """
        Récupère la configuration système complète.

        Args:
            db: Session de base de données

        Returns:
            SystemConfigRead avec toutes les configurations
        """
        rag_config = await ConfigService.get_rag_config(db)
        timeouts_config = await ConfigService.get_timeouts_config(db)
        rate_limits_config = await ConfigService.get_rate_limits_config(db)
        return SystemConfigRead(
            app_name=settings.app_name,
            app_version=settings.app_version,
            environment=settings.environment,
            debug=bool(_runtime_overrides.get('debug_endpoints_enabled', False)),
            rag=rag_config,
            timeouts=timeouts_config,
            rate_limits=rate_limits_config,
            ollama_host=f"{settings.ollama_host}:{settings.ollama_port}",
            ollama_model=settings.llm_model,
            chroma_host=f"{settings.chroma_host}:{settings.chroma_port}",
            collection_name=settings.collection_name
        )

    @staticmethod
    async def get_rag_config(
        db: AsyncSession,
        provider: Optional[str] = None
    ) -> RAGConfigRead:
        """
        Récupère la configuration RAG depuis la base de données.

        Les paramètres RAG sont spécifiques à chaque provider :
        - Si provider=ollama : rag.ollama.top_k, rag.ollama.temperature, etc.
        - Si provider=llamacpp : rag.llamacpp.top_k, rag.llamacpp.temperature, etc.

        Les modèles sont également provider-specific :
        - Si provider=ollama : llm.ollama.llm_model, llm.ollama.embedding_model
        - Si provider=llamacpp : llm.llamacpp.llm_model, llm.llamacpp.embedding_model

        Fallback sur clés globales (rag.*) pour rétrocompatibilité.

        Args:
            db: Session de base de données
            provider: Provider spécifique (optionnel, sinon utilise le provider actif)

        Returns:
            Configuration RAG pour le provider demandé
        """
        config_service = SystemConfigService(db)

        # Déterminer le provider (paramètre ou actif)
        if provider is None:
            provider = await config_service.get("llm.provider", settings.llm_provider)

        # Helper pour lire avec fallback: provider-specific → global
        async def get_rag_value(key: str, default):
            # 1. Essayer la clé provider-specific
            value = await config_service.get(f"rag.{provider}.{key}", None)
            if value is not None:
                return value
            # 2. Fallback vers clé globale
            return await config_service.get(f"rag.{key}", default)

        # Lire les modèles depuis le provider actif avec fallback sur anciennes clés
        if provider == "llamacpp":
            llm_model = await config_service.get("llm.llamacpp.llm_model", "")
            embedding_model = await config_service.get("llm.llamacpp.embedding_model", "")
        else:
            # Ollama (défaut)
            llm_model = await config_service.get("llm.ollama.llm_model", None)
            embedding_model = await config_service.get("llm.ollama.embedding_model", None)

        # Fallback sur anciennes clés rag.* pour rétrocompatibilité
        if not llm_model:
            llm_model = await config_service.get("rag.llm_model", settings.llm_model)
        if not embedding_model:
            embedding_model = await config_service.get("rag.embedding_model", settings.embedding_model)

        # Récupérer les paramètres RAG (provider-specific avec fallback global)
        top_k = await get_rag_value("top_k", settings.top_k)
        similarity_threshold = await get_rag_value("similarity_threshold", 0.7)
        temperature = await get_rag_value("temperature", 0.7)
        chunk_size = await get_rag_value("chunk_size", settings.chunk_size)
        chunk_overlap = await get_rag_value("chunk_overlap", settings.chunk_overlap)
        chunking_strategy = await get_rag_value("chunking_strategy", settings.chunking_strategy)
        # Recherche hybride
        min_chunk_length = await get_rag_value("min_chunk_length", 50)
        keyword_boost = await get_rag_value("keyword_boost", 0.15)
        stopwords_language = await get_rag_value("stopwords_language", "fr")
        # Corpus de sources (activé par défaut)
        use_corpus = await get_rag_value("use_corpus", True)
        # Comportement sans sources (désactivé par défaut)
        require_sources = await get_rag_value("require_sources", False)

        # max_context_items reste global (non provider-specific)
        max_context_items = await config_service.get("sources.max_context_items", 10)

        return RAGConfigRead(
            top_k=int(top_k),
            max_context_items=int(max_context_items),
            similarity_threshold=float(similarity_threshold),
            temperature=float(temperature),
            llm_model=str(llm_model),
            embedding_model=str(embedding_model),
            chunk_size=int(chunk_size),
            chunk_overlap=int(chunk_overlap),
            chunking_strategy=str(chunking_strategy),
            # Recherche hybride
            min_chunk_length=int(min_chunk_length),
            keyword_boost=float(keyword_boost),
            stopwords_language=str(stopwords_language),
            # Corpus de sources
            use_corpus=bool(use_corpus),
            # Comportement sans sources
            require_sources=bool(require_sources)
        )

    # ========================================================================
    # TEST ET STATISTIQUES RAG
    # ========================================================================

    @staticmethod
    async def test_rag_search(
        db: AsyncSession,
        request: "RAGTestRequest"
    ) -> "RAGTestResponse":
        """
        Teste la configuration RAG avec une requête sample.

        Args:
            db: Session de base de données
            request: Requête de test avec query et overrides optionnels

        Returns:
            RAGTestResponse avec les chunks, stats et config utilisée
        """
        import time
        from app.common.utils.chroma import get_chroma_client

        start_time = time.time()

        # Charger la config RAG actuelle
        rag_config = await ConfigService.get_rag_config(db)

        # Appliquer les overrides de la requête
        top_k = request.top_k or rag_config.top_k
        similarity_threshold = request.similarity_threshold or rag_config.similarity_threshold
        embedding_model = rag_config.embedding_model

        # Générer les embeddings de la query
        try:
            from app.common.llm import get_provider
            provider = get_provider()
            embedding_response = await provider.get_embeddings(request.query)
            query_embedding = embedding_response.embedding  # Extraire la liste de floats
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            return RAGTestResponse(
                query=request.query,
                chunks=[],
                stats={"error": str(e), "latency_ms": int((time.time() - start_time) * 1000)},
                config_used={
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                    "embedding_model": embedding_model
                }
            )

        # Recherche dans ChromaDB
        chunks = []
        total_found = 0
        filtered_count = 0

        try:
            chroma_client = get_chroma_client()

            # Déterminer les collections à interroger
            if request.collection_id:
                # Collection spécifique
                from sqlalchemy import select
                from app.models import Collection
                result = await db.execute(
                    select(Collection).where(Collection.id == request.collection_id)
                )
                collection = result.scalar_one_or_none()
                if collection:
                    collection_names = [collection.chroma_name]
                else:
                    collection_names = []
            else:
                # Toutes les collections
                chroma_collections = chroma_client.list_collections()
                collection_names = [c.name for c in chroma_collections]

            # Rechercher dans chaque collection
            for coll_name in collection_names:
                try:
                    chroma_coll = chroma_client.get_collection(coll_name)
                    results = chroma_coll.query(
                        query_embeddings=[query_embedding],
                        n_results=top_k * 2,  # Récupérer plus pour filtrer ensuite
                        include=["documents", "metadatas", "distances"]
                    )

                    if results and results.get("documents"):
                        docs = results["documents"][0]
                        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
                        distances = results["distances"][0] if results.get("distances") else [0] * len(docs)

                        for i, doc in enumerate(docs):
                            # Convertir distance en score (cosine: 1 - distance)
                            score = 1 - distances[i] if distances[i] < 1 else 0
                            total_found += 1

                            if score >= similarity_threshold:
                                metadata = metadatas[i] if i < len(metadatas) else {}
                                source = metadata.get("source", metadata.get("filename", coll_name))
                                chunks.append(RAGTestChunk(
                                    content=doc[:500] + ("..." if len(doc) > 500 else ""),
                                    score=round(score, 4),
                                    source=source,
                                    metadata=metadata
                                ))
                            else:
                                filtered_count += 1

                except Exception as coll_error:
                    logger.warning(f"Error querying collection {coll_name}: {coll_error}")
                    continue

            # Trier par score et limiter à top_k
            chunks.sort(key=lambda c: c.score, reverse=True)
            chunks = chunks[:top_k]

        except Exception as e:
            logger.error(f"Error searching ChromaDB: {e}")
            return RAGTestResponse(
                query=request.query,
                chunks=[],
                stats={"error": str(e), "latency_ms": int((time.time() - start_time) * 1000)},
                config_used={
                    "top_k": top_k,
                    "similarity_threshold": similarity_threshold,
                    "embedding_model": embedding_model
                }
            )

        latency_ms = int((time.time() - start_time) * 1000)

        return RAGTestResponse(
            query=request.query,
            chunks=chunks,
            stats={
                "total_found": total_found,
                "filtered_by_threshold": filtered_count,
                "final_count": len(chunks),
                "latency_ms": latency_ms,
                "collections_searched": len(collection_names)
            },
            config_used={
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
                "embedding_model": embedding_model
            }
        )

    @staticmethod
    async def get_rag_stats(db: AsyncSession) -> "RAGStatsResponse":
        """
        Récupère les statistiques RAG globales.

        Args:
            db: Session de base de données

        Returns:
            RAGStatsResponse avec les statistiques
        """
        from sqlalchemy import select, func
        from app.models import Collection, Document
        from app.common.utils.chroma import get_chroma_client

        config_service = SystemConfigService(db)

        # Récupérer le modèle d'embedding actif
        provider = await config_service.get("llm.provider", settings.llm_provider)
        if provider == "llamacpp":
            embedding_model = await config_service.get("llm.llamacpp.embedding_model", "")
        else:
            embedding_model = await config_service.get("llm.ollama.embedding_model", None)
            if not embedding_model:
                embedding_model = await config_service.get("rag.embedding_model", settings.embedding_model)

        # Compter les collections
        result = await db.execute(select(func.count(Collection.id)))
        collections_count = result.scalar() or 0

        # Compter les documents
        result = await db.execute(select(func.count(Document.id)))
        documents_count = result.scalar() or 0

        # Dernière indexation (document le plus récemment mis à jour)
        result = await db.execute(
            select(Document.updated_at)
            .where(Document.updated_at.isnot(None))
            .order_by(Document.updated_at.desc())
            .limit(1)
        )
        last_indexation_row = result.scalar_one_or_none()
        last_indexation = last_indexation_row.isoformat() if last_indexation_row else None

        # Compter les chunks dans ChromaDB
        chunks_count = 0
        avg_chunk_size = 0

        try:
            chroma_client = get_chroma_client()
            chroma_collections = chroma_client.list_collections()

            total_chars = 0
            for coll in chroma_collections:
                try:
                    chroma_coll = chroma_client.get_collection(coll.name)
                    count = chroma_coll.count()
                    chunks_count += count

                    # Échantillonner pour calculer la taille moyenne
                    if count > 0:
                        sample = chroma_coll.peek(limit=min(10, count))
                        if sample and sample.get("documents"):
                            for doc in sample["documents"]:
                                total_chars += len(doc)
                except Exception as e:
                    logger.warning(f"Error counting collection {coll.name}: {e}")
                    continue

            if chunks_count > 0 and total_chars > 0:
                # Estimation basée sur l'échantillon
                sample_size = min(chunks_count, 10 * len(chroma_collections))
                avg_chunk_size = total_chars // sample_size if sample_size > 0 else 0

        except Exception as e:
            logger.error(f"Error getting ChromaDB stats: {e}")

        return RAGStatsResponse(
            collections_count=collections_count,
            documents_count=documents_count,
            chunks_count=chunks_count,
            avg_chunk_size=avg_chunk_size,
            embedding_model=str(embedding_model),
            last_indexation=last_indexation
        )

    # ========================================================================
    # CONFIGURATION LLM PROVIDER
    # ========================================================================

    @staticmethod
    async def get_llm_provider_config(db: AsyncSession) -> LLMProviderConfigRead:
        """
        Récupère la configuration du provider LLM depuis la base de données.
        Inclut le statut de santé du provider actif et les modèles configurés par provider.
        """
        config_service = SystemConfigService(db)

        # Récupérer les valeurs depuis la BDD avec fallback sur settings
        provider = await config_service.get("llm.provider", settings.llm_provider)
        embedding_provider = await config_service.get("llm.embedding_provider", "")
        ollama_host = await config_service.get("llm.ollama_host", settings.ollama_host)
        ollama_port = await config_service.get("llm.ollama_port", settings.ollama_port)
        llamacpp_host = await config_service.get("llm.llamacpp_host", getattr(settings, 'llamacpp_host', 'host.docker.internal'))
        llamacpp_port = await config_service.get("llm.llamacpp_port", getattr(settings, 'llamacpp_port', 8085))

        # Modèles configurés par provider (avec fallback rétrocompatibilité)
        ollama_llm_model = await config_service.get("llm.ollama.llm_model", None)
        ollama_embedding_model = await config_service.get("llm.ollama.embedding_model", None)
        llamacpp_llm_model = await config_service.get("llm.llamacpp.llm_model", "")
        llamacpp_embedding_model = await config_service.get("llm.llamacpp.embedding_model", "")

        # Fallback sur anciennes clés rag.* pour Ollama
        if not ollama_llm_model:
            ollama_llm_model = await config_service.get("rag.llm_model", settings.llm_model)
        if not ollama_embedding_model:
            ollama_embedding_model = await config_service.get("rag.embedding_model", settings.embedding_model)

        # Vérifier le statut du provider actif
        provider_status = "unknown"
        provider_info = {}
        try:
            from app.common.llm import get_provider
            llm_provider = get_provider()
            health = await llm_provider.health_check()
            provider_status = health.get("status", "unknown")
            provider_info = health
        except Exception as e:
            provider_status = "unhealthy"
            provider_info = {"error": str(e)}

        return LLMProviderConfigRead(
            provider=str(provider),
            embedding_provider=str(embedding_provider),
            ollama_host=str(ollama_host),
            ollama_port=int(ollama_port),
            ollama_llm_model=str(ollama_llm_model),
            ollama_embedding_model=str(ollama_embedding_model),
            llamacpp_host=str(llamacpp_host),
            llamacpp_port=int(llamacpp_port),
            llamacpp_llm_model=str(llamacpp_llm_model),
            llamacpp_embedding_model=str(llamacpp_embedding_model),
            provider_status=provider_status,
            provider_info=provider_info
        )

    @staticmethod
    async def update_llm_provider_config(
        db: AsyncSession,
        config: LLMProviderConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> LLMProviderConfigRead:
        """
        Met à jour la configuration du provider LLM en base de données.

        Note: Le changement de provider nécessite un redémarrage de l'application
        pour prendre effet complètement (le provider est un singleton).
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "provider": "llm.provider",
            "embedding_provider": "llm.embedding_provider",
            "ollama_host": "llm.ollama_host",
            "ollama_port": "llm.ollama_port",
            "ollama_llm_model": "llm.ollama.llm_model",
            "ollama_embedding_model": "llm.ollama.embedding_model",
            "llamacpp_host": "llm.llamacpp_host",
            "llamacpp_port": "llm.llamacpp_port",
            "llamacpp_llm_model": "llm.llamacpp.llm_model",
            "llamacpp_embedding_model": "llm.llamacpp.embedding_model",
        }

        provider_changed = False
        embedding_provider_changed = False
        new_provider_name = None
        new_embedding_provider_name = None
        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"LLM provider config updated in DB: {db_key} = {value}")
                if field == "provider":
                    provider_changed = True
                    new_provider_name = value
                if field == "embedding_provider":
                    embedding_provider_changed = True
                    new_embedding_provider_name = value
                # Log de sécurité
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        # Réinitialiser le provider si changé (sera recréé au prochain appel)
        if provider_changed and new_provider_name:
            try:
                from app.common.llm import close_provider, reset_provider, set_provider_override
                # Définir le nouveau provider AVANT le reset
                set_provider_override(new_provider_name)
                await close_provider()
                reset_provider()
                logger.info(f"LLM provider reset to: {new_provider_name}")
            except Exception as e:
                logger.warning(f"Failed to reset LLM provider: {e}")

        # Réinitialiser le provider d'embedding si changé
        if embedding_provider_changed:
            try:
                from app.common.llm import set_embedding_provider_override
                set_embedding_provider_override(new_embedding_provider_name)
                logger.info(f"Embedding provider set to: {new_embedding_provider_name}")
            except Exception as e:
                logger.warning(f"Failed to set embedding provider: {e}")

        return await ConfigService.get_llm_provider_config(db)

    # ========================================================================
    # GESTION DES MODELES PAR PROVIDER
    # ========================================================================

    @staticmethod
    async def list_ollama_models(db: AsyncSession) -> ModelsListResponse:
        """
        Liste les modèles disponibles sur Ollama via l'API /api/tags.

        Returns:
            ModelsListResponse avec la liste des modèles Ollama installés
        """
        config_service = SystemConfigService(db)

        # Modèles actuellement configurés
        current_llm = await config_service.get("llm.ollama.llm_model", None)
        current_embedding = await config_service.get("llm.ollama.embedding_model", None)

        # Fallback sur anciennes clés
        if not current_llm:
            current_llm = await config_service.get("rag.llm_model", settings.llm_model)
        if not current_embedding:
            current_embedding = await config_service.get("rag.embedding_model", settings.embedding_model)

        models: List[ModelInfo] = []

        try:
            ollama_host = await config_service.get("llm.ollama_host", settings.ollama_host)
            ollama_port = await config_service.get("llm.ollama_port", settings.ollama_port)
            ollama_url = f"http://{ollama_host}:{ollama_port}"

            async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
                response = await client.get(f"{ollama_url}/api/tags")
                response.raise_for_status()
                data = response.json()

            for m in data.get("models", []):
                size = m.get("size", 0)
                models.append(ModelInfo(
                    name=m.get("name", ""),
                    size=size,
                    size_human=ConfigService._format_size(size) if size else None,
                    modified_at=m.get("modified_at"),
                    digest=m.get("digest"),
                    path=None
                ))

        except httpx.HTTPError as e:
            logger.warning(f"Cannot connect to Ollama: {e}")
        except Exception as e:
            logger.error(f"Error listing Ollama models: {e}")

        return ModelsListResponse(
            provider="ollama",
            models=models,
            current_llm_model=str(current_llm),
            current_embedding_model=str(current_embedding)
        )

    @staticmethod
    async def list_llamacpp_models(db: AsyncSession) -> ModelsListResponse:
        """
        Liste les fichiers GGUF disponibles dans le dossier models/gguf/.

        Returns:
            ModelsListResponse avec la liste des modèles GGUF trouvés
        """
        config_service = SystemConfigService(db)

        # Modèles actuellement configurés
        current_llm = await config_service.get("llm.llamacpp.llm_model", "")
        current_embedding = await config_service.get("llm.llamacpp.embedding_model", "")

        models: List[ModelInfo] = []

        # Dossier des modèles GGUF
        models_dir = Path("models/gguf")

        if models_dir.exists():
            # Scanner récursivement tous les sous-dossiers (chat/, embedding/, etc.)
            for file in models_dir.glob("**/*.gguf"):
                try:
                    stat = file.stat()
                    # Stocker le chemin relatif pour supporter les sous-dossiers
                    relative_path = file.relative_to(models_dir)
                    models.append(ModelInfo(
                        name=str(relative_path),  # ex: "chat/model.gguf"
                        size=stat.st_size,
                        size_human=ConfigService._format_size(stat.st_size),
                        modified_at=str(stat.st_mtime),
                        digest=None,
                        path=str(file)
                    ))
                except OSError as e:
                    logger.warning(f"Cannot stat file {file}: {e}")

            # Trier par nom
            models.sort(key=lambda m: m.name)
        else:
            logger.info(f"Models directory {models_dir} does not exist")

        return ModelsListResponse(
            provider="llamacpp",
            models=models,
            current_llm_model=str(current_llm),
            current_embedding_model=str(current_embedding)
        )

    @staticmethod
    async def list_models_for_provider(
        db: AsyncSession,
        provider: Optional[str] = None
    ) -> ModelsListResponse:
        """
        Liste les modèles pour un provider spécifique ou le provider actif.

        Args:
            db: Session de base de données
            provider: Provider à utiliser (ollama/llamacpp), ou None pour le provider actif

        Returns:
            ModelsListResponse avec la liste des modèles
        """
        if provider is None:
            config_service = SystemConfigService(db)
            provider = await config_service.get("llm.provider", settings.llm_provider)

        if provider == "llamacpp":
            return await ConfigService.list_llamacpp_models(db)
        else:
            return await ConfigService.list_ollama_models(db)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Formate une taille en bytes en format lisible."""
        if not size_bytes:
            return "0 B"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    # ========================================================================
    # TELECHARGEMENT ET SUPPRESSION DE MODELES
    # ========================================================================

    @staticmethod
    async def download_gguf_stream(
        url: str,
        filename: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Télécharge un fichier GGUF depuis une URL avec streaming de progression.

        Args:
            url: URL du fichier GGUF à télécharger
            filename: Nom du fichier de destination (déduit de l'URL si absent)

        Yields:
            Messages JSON SSE avec la progression du téléchargement
        """
        # Créer le dossier models/gguf si nécessaire
        models_dir = Path("models/gguf")
        models_dir.mkdir(parents=True, exist_ok=True)

        # Déduire le nom de fichier de l'URL si non fourni
        if filename is None:
            filename = url.split("/")[-1].split("?")[0]
            if not filename.endswith(".gguf"):
                filename = f"{filename}.gguf"

        # Validation de sécurité : empêcher path traversal
        if "\\" in filename or ".." in filename:
            yield f"data: {json.dumps({'event': 'error', 'error': 'Nom de fichier invalide'})}\n\n"
            return

        dest_path = models_dir / filename

        # Vérifier que le chemin résolu reste dans models_dir (sécurité path traversal)
        if not os.path.realpath(str(dest_path)).startswith(os.path.realpath(str(models_dir)) + os.sep):
            yield f"data: {json.dumps({'event': 'error', 'error': 'Chemin de fichier invalide'})}\n\n"
            return

        # Vérifier si le fichier existe déjà
        if dest_path.exists():
            yield f"data: {json.dumps({'event': 'error', 'error': f'Le fichier {filename} existe déjà'})}\n\n"
            return

        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'event': 'error', 'error': f'HTTP {response.status_code}: {response.reason_phrase}'})}\n\n"
                        return

                    total = int(response.headers.get("content-length", 0))
                    downloaded = 0

                    # Padding initial pour forcer le navigateur à commencer le streaming
                    # Chrome attend souvent 4KB+ avant de commencer à traiter
                    # Les commentaires SSE (lignes commençant par :) sont ignorés par le parser
                    for _ in range(8):
                        yield ": " + "x" * 512 + "\n"
                    yield "\n"
                    await asyncio.sleep(0.05)

                    # Envoyer le début du téléchargement
                    start_event = json.dumps({
                        'event': 'start',
                        'filename': filename,
                        'total': total,
                        'total_human': ConfigService._format_size(total)
                    })
                    yield f"data: {start_event}\n\n"
                    await asyncio.sleep(0.1)  # Forcer flush du start event

                    last_progress_sent = 0
                    last_event_time = asyncio.get_event_loop().time()

                    async with aiofiles.open(dest_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):  # 1MB chunks
                            await f.write(chunk)
                            downloaded += len(chunk)

                            # Calculer la progression
                            progress = (downloaded / total * 100) if total else 0
                            current_time = asyncio.get_event_loop().time()

                            # Envoyer un événement tous les 1% OU toutes les 200ms minimum
                            if (progress - last_progress_sent >= 1.0 or progress >= 100) and \
                               (current_time - last_event_time >= 0.2 or progress >= 100):
                                last_progress_sent = progress
                                last_event_time = current_time
                                event_data = json.dumps({
                                    'event': 'progress',
                                    'status': 'downloading',
                                    'progress': round(progress, 1),
                                    'downloaded': downloaded,
                                    'downloaded_human': ConfigService._format_size(downloaded),
                                    'total': total,
                                    'total_human': ConfigService._format_size(total)
                                })
                                yield f"data: {event_data}\n\n"
                                # Forcer le flush immédiat
                                await asyncio.sleep(0)

            # Téléchargement terminé
            final_size = dest_path.stat().st_size
            yield f"data: {json.dumps({'event': 'complete', 'success': True, 'status': 'complete', 'filename': filename, 'path': str(dest_path), 'size': final_size, 'size_human': ConfigService._format_size(final_size), 'message': f'Modèle {filename} téléchargé avec succès'})}\n\n"

            logger.info(f"GGUF model downloaded: {filename} ({ConfigService._format_size(final_size)})")

        except httpx.RequestError as e:
            # Supprimer le fichier partiel
            if dest_path.exists():
                dest_path.unlink()
            error_msg = f"Erreur de connexion: {str(e)}"
            logger.error(f"GGUF download failed: {error_msg}")
            yield f"data: {json.dumps({'event': 'error', 'error': error_msg})}\n\n"

        except Exception as e:
            # Supprimer le fichier partiel
            if dest_path.exists():
                dest_path.unlink()
            error_msg = f"Erreur inattendue: {str(e)}"
            logger.error(f"GGUF download failed: {error_msg}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'error': error_msg})}\n\n"

    @staticmethod
    def start_gguf_download(url: str, filename: Optional[str] = None) -> str:
        """
        Démarre un téléchargement GGUF en arrière-plan et retourne un task_id.
        Utiliser get_download_progress() pour suivre la progression.
        """
        import uuid

        # Générer un task_id unique
        task_id = str(uuid.uuid4())[:8]

        # Déduire le nom de fichier
        if filename is None:
            filename = url.split("/")[-1].split("?")[0]
            if not filename.endswith(".gguf"):
                filename = f"{filename}.gguf"

        # Validation de sécurité : empêcher path traversal
        if "\\" in filename or ".." in filename:
            raise ValueError("Nom de fichier invalide")

        models_dir = Path("models/gguf")
        dest_path = models_dir / filename
        if not os.path.realpath(str(dest_path)).startswith(
            os.path.realpath(str(models_dir)) + os.sep
        ):
            raise ValueError("Chemin de fichier invalide")

        # Initialiser l'état de la tâche
        _download_tasks[task_id] = {
            "status": "pending",
            "filename": filename,
            "url": url,
            "progress": 0,
            "downloaded": 0,
            "downloaded_human": "0 B",
            "total": 0,
            "total_human": "0 B",
            "error": None,
            "message": "Initialisation..."
        }

        # Démarrer le téléchargement dans une tâche asyncio
        asyncio.create_task(ConfigService._download_gguf_background(task_id, url, filename))

        return task_id

    @staticmethod
    async def _download_gguf_background(task_id: str, url: str, filename: str):
        """Télécharge un fichier GGUF en arrière-plan avec mise à jour de progression."""
        models_dir = Path("models/gguf")
        models_dir.mkdir(parents=True, exist_ok=True)
        dest_path = models_dir / filename

        # Validation de sécurité : vérifier que le chemin reste dans models_dir
        if not os.path.realpath(str(dest_path)).startswith(
            os.path.realpath(str(models_dir)) + os.sep
        ):
            task = _download_tasks.get(task_id)
            if task:
                task["status"] = "error"
                task["error"] = "Chemin de fichier invalide"
            return

        task = _download_tasks.get(task_id)
        if not task:
            return

        # Vérifier si le fichier existe déjà
        if dest_path.exists():
            task["status"] = "error"
            task["error"] = f"Le fichier {filename} existe déjà"
            return

        try:
            task["status"] = "downloading"
            task["message"] = "Connexion..."

            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        task["status"] = "error"
                        task["error"] = f"HTTP {response.status_code}: {response.reason_phrase}"
                        return

                    total = int(response.headers.get("content-length", 0))
                    task["total"] = total
                    task["total_human"] = ConfigService._format_size(total)
                    task["message"] = f"Téléchargement de {filename}"

                    downloaded = 0
                    async with aiofiles.open(dest_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            # Vérifier l'annulation
                            if _download_cancellations.get(task_id):
                                task["status"] = "cancelled"
                                task["message"] = "Téléchargement annulé"
                                logger.info(f"GGUF download cancelled: {filename}")
                                # Fermer le fichier et le supprimer
                                break

                            await f.write(chunk)
                            downloaded += len(chunk)

                            # Mettre à jour la progression
                            progress = (downloaded / total * 100) if total else 0
                            task["progress"] = round(progress, 1)
                            task["downloaded"] = downloaded
                            task["downloaded_human"] = ConfigService._format_size(downloaded)

            # Vérifier si annulé
            if _download_cancellations.get(task_id):
                if dest_path.exists():
                    dest_path.unlink()
                # Nettoyer le signal d'annulation
                _download_cancellations.pop(task_id, None)
                return

            # Téléchargement terminé
            final_size = dest_path.stat().st_size
            task["status"] = "complete"
            task["progress"] = 100
            task["downloaded"] = final_size
            task["downloaded_human"] = ConfigService._format_size(final_size)
            task["message"] = f"Modèle {filename} téléchargé avec succès"
            logger.info(f"GGUF model downloaded: {filename} ({ConfigService._format_size(final_size)})")

        except httpx.RequestError as e:
            if dest_path.exists():
                dest_path.unlink()
            task["status"] = "error"
            task["error"] = f"Erreur de connexion: {str(e)}"
            logger.error(f"GGUF download failed: {task['error']}")

        except Exception as e:
            if dest_path.exists():
                dest_path.unlink()
            task["status"] = "error"
            task["error"] = f"Erreur inattendue: {str(e)}"
            logger.error(f"GGUF download failed: {task['error']}", exc_info=True)

    @staticmethod
    def get_download_progress(task_id: str) -> Optional[Dict[str, Any]]:
        """Retourne la progression d'un téléchargement en cours."""
        return _download_tasks.get(task_id)

    @staticmethod
    def cancel_download(task_id: str) -> bool:
        """
        Demande l'annulation d'un téléchargement en cours.
        Retourne True si la tâche existe et a été marquée pour annulation.
        """
        task = _download_tasks.get(task_id)
        if not task:
            return False

        if task.get("status") in ("complete", "error", "cancelled"):
            return False  # Déjà terminé

        # Signaler l'annulation
        _download_cancellations[task_id] = True
        logger.info(f"Download cancellation requested for task {task_id}")
        return True

    @staticmethod
    def cleanup_download_task(task_id: str):
        """Supprime une tâche de téléchargement terminée."""
        if task_id in _download_tasks:
            del _download_tasks[task_id]
        if task_id in _download_cancellations:
            del _download_cancellations[task_id]

    # =========================================================================
    # OLLAMA PULL (Polling)
    # =========================================================================

    @staticmethod
    def start_ollama_pull(model_name: str) -> str:
        """
        Démarre un pull Ollama en arrière-plan et retourne un task_id.
        Utiliser get_ollama_pull_progress() pour suivre la progression.
        """
        import uuid

        task_id = str(uuid.uuid4())[:8]

        _ollama_pull_tasks[task_id] = {
            "status": "pending",
            "model_name": model_name,
            "filename": model_name,  # Pour compatibilité avec le frontend
            "progress": 0,
            "downloaded": 0,
            "downloaded_human": "0 B",
            "total": 0,
            "total_human": "0 B",
            "error": None,
            "message": f"Téléchargement de {model_name}"
        }

        asyncio.create_task(ConfigService._pull_ollama_background(task_id, model_name))

        return task_id

    @staticmethod
    async def _pull_ollama_background(task_id: str, model_name: str):
        """
        Pull un modèle Ollama en arrière-plan avec mise à jour de progression.

        Ollama télécharge plusieurs "layers" séquentiellement. Cette implémentation :
        - Cumule les tailles des layers complétées
        - Ne fait jamais baisser la progression (pas de reset)
        - Plafonne à 99% jusqu'au statut "success"
        """
        from app.core.config import settings
        import json as json_lib

        task = _ollama_pull_tasks.get(task_id)
        if not task:
            return

        def format_size(size_bytes):
            if not size_bytes:
                return "0 B"
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

        # État pour progression cumulative (comme GGUF)
        cumulative_downloaded = 0  # Total des layers complétées
        completed_digests = set()  # Digests des layers déjà comptées
        current_digest = None      # Digest de la layer en cours
        max_progress = 0           # Progression max atteinte (ne baisse jamais)

        try:
            task["status"] = "downloading"
            task["message"] = f"Téléchargement de {model_name}"

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{settings.ollama_url}/api/pull",
                    json={"name": model_name, "stream": True}
                ) as response:
                    if response.status_code != 200:
                        task["status"] = "error"
                        task["error"] = f"Ollama returned status {response.status_code}"
                        return

                    async for line in response.aiter_lines():
                        # Vérifier l'annulation
                        if _ollama_pull_cancellations.get(task_id):
                            task["status"] = "cancelled"
                            task["message"] = "Téléchargement annulé"
                            logger.info(f"Ollama pull cancelled: {model_name}")
                            return

                        if not line.strip():
                            continue

                        try:
                            ollama_data = json_lib.loads(line)
                            status = ollama_data.get("status", "")
                            total = ollama_data.get("total", 0)
                            completed = ollama_data.get("completed", 0)

                            # Extraire le digest si c'est un pull de layer
                            digest = None
                            if status.startswith("pulling "):
                                # Format: "pulling sha256:abc123..."
                                parts = status.split(" ", 1)
                                if len(parts) > 1:
                                    digest = parts[1]

                            # Détecter quand une layer est complétée
                            if digest and digest not in completed_digests:
                                if completed == total and total > 0:
                                    # Layer terminée, ajouter au cumul
                                    cumulative_downloaded += total
                                    completed_digests.add(digest)
                                current_digest = digest

                            # Calculer le total téléchargé (cumul + layer en cours)
                            current_downloaded = cumulative_downloaded + completed
                            task["downloaded"] = current_downloaded
                            task["downloaded_human"] = format_size(current_downloaded)

                            # Pour le total, on affiche le cumul actuel (on ne connaît pas le total final)
                            # Quand une layer est en cours, on ajoute son total au cumul pour l'affichage
                            display_total = cumulative_downloaded + total if total > 0 else current_downloaded
                            task["total"] = display_total
                            task["total_human"] = format_size(display_total)

                            # Progression : ne jamais baisser, max 99% jusqu'au success
                            if total > 0:
                                layer_progress = int((completed / total) * 100)
                                # Plafonner à 99% pour éviter les faux 100%
                                layer_progress = min(layer_progress, 99)
                                if layer_progress > max_progress:
                                    max_progress = layer_progress
                                    task["progress"] = max_progress

                            # Messages selon le statut
                            if status == "success":
                                task["status"] = "complete"
                                task["progress"] = 100
                                task["downloaded_human"] = format_size(current_downloaded)
                                task["total_human"] = format_size(current_downloaded)
                                task["message"] = f"Modèle {model_name} téléchargé avec succès"
                                logger.info(f"Ollama model pulled: {model_name} ({format_size(current_downloaded)})")
                                return
                            elif status == "pulling manifest":
                                task["message"] = f"Récupération du manifest..."
                            elif status == "verifying sha256 digest":
                                task["message"] = f"Vérification de {model_name}..."
                            elif status == "writing manifest":
                                task["message"] = f"Finalisation de {model_name}..."
                            elif status == "removing any unused layers":
                                task["message"] = f"Nettoyage..."
                            elif status.startswith("pulling ") or "downloading" in status.lower():
                                task["message"] = f"Téléchargement de {model_name}"
                            # Sinon garder le message précédent

                        except json_lib.JSONDecodeError:
                            continue

        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Ollama: {e}")
            task["status"] = "error"
            task["error"] = "Impossible de contacter Ollama"
        except Exception as e:
            logger.error(f"Error pulling Ollama model {model_name}: {e}")
            task["status"] = "error"
            task["error"] = str(e)

    @staticmethod
    def get_ollama_pull_progress(task_id: str) -> Optional[Dict[str, Any]]:
        """Retourne la progression d'un pull Ollama."""
        return _ollama_pull_tasks.get(task_id)

    @staticmethod
    def cancel_ollama_pull(task_id: str) -> bool:
        """
        Demande l'annulation d'un pull Ollama en cours.
        Retourne True si la tâche existe et a été marquée pour annulation.
        """
        task = _ollama_pull_tasks.get(task_id)
        if not task:
            return False

        if task.get("status") in ("complete", "error", "cancelled"):
            return False

        _ollama_pull_cancellations[task_id] = True
        logger.info(f"Ollama pull cancellation requested for task {task_id}")
        return True

    @staticmethod
    def cleanup_ollama_pull_task(task_id: str):
        """Supprime une tâche de pull Ollama terminée."""
        if task_id in _ollama_pull_tasks:
            del _ollama_pull_tasks[task_id]
        if task_id in _ollama_pull_cancellations:
            del _ollama_pull_cancellations[task_id]

    @staticmethod
    async def delete_gguf_model(filename: str) -> dict:
        """
        Supprime un fichier GGUF du dossier models/gguf/.

        Args:
            filename: Chemin relatif du fichier à supprimer (ex: "chat/model.gguf")

        Returns:
            Dict avec status et message

        Raises:
            FileNotFoundError: Si le fichier n'existe pas
            ValueError: Si le fichier n'est pas un .gguf
        """
        # Validation de sécurité : empêcher path traversal et backslash Windows
        if "\\" in filename or ".." in filename:
            raise ValueError("Nom de fichier invalide")

        if not filename.endswith(".gguf"):
            raise ValueError("Seuls les fichiers .gguf peuvent être supprimés")

        # Construire le chemin complet (supporte les sous-dossiers comme chat/, embedding/)
        models_dir = Path("models/gguf")
        filepath = models_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Modèle non trouvé: {filename}")

        # Vérifier que le fichier est bien dans le dossier models/gguf (sécurité path traversal)
        real_filepath = os.path.realpath(str(filepath))
        real_models_dir = os.path.realpath(str(models_dir))
        if not real_filepath.startswith(real_models_dir + os.sep):
            raise ValueError("Chemin de fichier invalide")

        # Récupérer la taille avant suppression pour le log
        size = filepath.stat().st_size

        filepath.unlink()

        logger.info(f"GGUF model deleted: {filename} ({ConfigService._format_size(size)})")

        return {
            "status": "deleted",
            "provider": "llamacpp",
            "filename": filename,
            "message": f"Modèle {filename} supprimé"
        }

    # ========================================================================
    # CONTROLE LLM PROVIDER (Start/Stop/Status)
    # ========================================================================

    @staticmethod
    async def start_llamacpp(
        db: AsyncSession = None,
        model: Optional[str] = None,
        port: Optional[int] = None,
        ctx_size: Optional[int] = None,
        gpu_layers: Optional[int] = None,
        embedding: Optional[bool] = None
    ) -> dict:
        """
        Démarre llama-server via le script llamacpp.sh.

        Les paramètres non fournis sont lus depuis la BDD (system_configs).

        Args:
            db: Session BDD pour lire les paramètres configurés
            model: Chemin vers le modèle GGUF (relatif à models/gguf/)
            port: Port d'écoute (défaut BDD ou 8085)
            ctx_size: Taille du contexte (défaut BDD ou 4096)
            gpu_layers: Nombre de couches GPU (défaut BDD ou 99)
            embedding: Activer l'endpoint d'embeddings (défaut BDD ou False)

        Returns:
            Dict avec status, message, output, pid
        """
        script_path = Path("scripts/llamacpp.sh")

        if not script_path.exists():
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "Script llamacpp.sh non trouvé",
                "output": None,
                "pid": None
            }

        # Détecter si on est dans Docker (le script ne peut pas contrôler l'hôte depuis Docker)
        in_docker = Path("/.dockerenv").exists() or (
            Path("/proc/1/cgroup").exists() and
            "docker" in Path("/proc/1/cgroup").read_text()
        )
        if in_docker:
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "llama-server tourne sur l'hôte, pas dans Docker. "
                           "Utilisez ./scripts/llamacpp.sh start depuis le terminal de l'hôte.",
                "output": None,
                "pid": None
            }

        # Lire les paramètres depuis la BDD si non fournis
        if db is not None:
            config_service = SystemConfigService(db)
            if model is None:
                model = await config_service.get("llm.llamacpp.llm_model", "")
            if port is None:
                port = int(await config_service.get("llm.llamacpp.port", 8085))
            if ctx_size is None:
                ctx_size = int(await config_service.get("llm.llamacpp.ctx_size", 4096))
            if gpu_layers is None:
                gpu_layers = int(await config_service.get("llm.llamacpp.gpu_layers", 99))
            if embedding is None:
                embedding = str(await config_service.get("llm.llamacpp.embedding_mode", "false")).lower() == "true"
        else:
            # Valeurs par défaut si pas de BDD
            if port is None:
                port = 8085
            if ctx_size is None:
                ctx_size = 4096
            if gpu_layers is None:
                gpu_layers = 99
            if embedding is None:
                embedding = False

        # Construire la commande
        cmd = [str(script_path.absolute()), "start"]

        if model:
            # Si le modèle ne contient pas de chemin, ajouter models/gguf/
            if "/" not in model and not model.startswith("models"):
                model = f"models/gguf/{model}"
            cmd.extend(["--model", model])

        if port:
            cmd.extend(["--port", str(port)])

        if ctx_size:
            cmd.extend(["--ctx-size", str(ctx_size)])

        if gpu_layers is not None:
            cmd.extend(["--gpu-layers", str(gpu_layers)])

        if embedding:
            cmd.append("--embed")

        logger.info(f"Starting llama-server with command: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path.cwd())
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30.0  # 30 secondes max pour démarrer
            )

            output = stdout.decode() + stderr.decode()

            if process.returncode == 0:
                # Essayer de récupérer le PID depuis le fichier
                pid = None
                pid_file = Path(".llamacpp.pid")
                if pid_file.exists():
                    try:
                        pid = int(pid_file.read_text().strip())
                    except (ValueError, OSError):
                        pass

                logger.info(f"llama-server started successfully (PID: {pid})")
                return {
                    "status": "started",
                    "provider": "llamacpp",
                    "message": "llama-server démarré avec succès",
                    "output": output.strip() if output.strip() else None,
                    "pid": pid
                }
            else:
                logger.error(f"llama-server start failed: {output}")
                return {
                    "status": "error",
                    "provider": "llamacpp",
                    "message": f"Erreur au démarrage (code {process.returncode})",
                    "output": output.strip() if output.strip() else None,
                    "pid": None
                }

        except asyncio.TimeoutError:
            logger.error("llama-server start timed out")
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "Timeout au démarrage (30s)",
                "output": None,
                "pid": None
            }
        except Exception as e:
            logger.error(f"llama-server start error: {e}", exc_info=True)
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": f"Erreur: {str(e)}",
                "output": None,
                "pid": None
            }

    @staticmethod
    async def stop_llamacpp() -> dict:
        """
        Arrête llama-server via le script llamacpp.sh.

        Returns:
            Dict avec status, message, output
        """
        script_path = Path("scripts/llamacpp.sh")

        if not script_path.exists():
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "Script llamacpp.sh non trouvé",
                "output": None,
                "pid": None
            }

        # Détecter si on est dans Docker (le script ne peut pas contrôler l'hôte depuis Docker)
        in_docker = Path("/.dockerenv").exists() or (
            Path("/proc/1/cgroup").exists() and
            "docker" in Path("/proc/1/cgroup").read_text()
        )
        if in_docker:
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "llama-server tourne sur l'hôte, pas dans Docker. "
                           "Utilisez ./scripts/llamacpp.sh stop depuis le terminal de l'hôte.",
                "output": None,
                "pid": None
            }

        try:
            process = await asyncio.create_subprocess_exec(
                str(script_path.absolute()), "stop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path.cwd())
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10.0  # 10 secondes max pour arrêter
            )

            output = stdout.decode() + stderr.decode()

            if process.returncode == 0:
                logger.info("llama-server stopped successfully")
                return {
                    "status": "stopped",
                    "provider": "llamacpp",
                    "message": "llama-server arrêté avec succès",
                    "output": output.strip() if output.strip() else None,
                    "pid": None
                }
            else:
                # Code 1 peut signifier "déjà arrêté"
                if "not running" in output.lower() or "pas en cours" in output.lower():
                    return {
                        "status": "already_stopped",
                        "provider": "llamacpp",
                        "message": "llama-server n'était pas en cours d'exécution",
                        "output": output.strip() if output.strip() else None,
                        "pid": None
                    }
                logger.error(f"llama-server stop failed: {output}")
                return {
                    "status": "error",
                    "provider": "llamacpp",
                    "message": f"Erreur à l'arrêt (code {process.returncode})",
                    "output": output.strip() if output.strip() else None,
                    "pid": None
                }

        except asyncio.TimeoutError:
            logger.error("llama-server stop timed out")
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": "Timeout à l'arrêt (10s)",
                "output": None,
                "pid": None
            }
        except Exception as e:
            logger.error(f"llama-server stop error: {e}", exc_info=True)
            return {
                "status": "error",
                "provider": "llamacpp",
                "message": f"Erreur: {str(e)}",
                "output": None,
                "pid": None
            }

    @staticmethod
    async def get_llamacpp_status(db: AsyncSession = None, port: int = None) -> dict:
        """
        Récupère le statut détaillé de llama-server.

        Args:
            db: Session BDD pour lire le port configuré (optionnel)
            port: Port à utiliser pour le health check (optionnel, lu depuis BDD si non fourni)

        Returns:
            Dict avec status, pid, healthy, model_loaded, etc.
        """
        result = {
            "provider": "llamacpp",
            "status": "stopped",
            "healthy": False,
            "pid": None,
            "model_loaded": None,
            "uptime": None,
            "memory_usage": None,
            "gpu_layers": None,
            "ctx_size": None
        }

        # Déterminer le port à utiliser
        if port is None:
            if db is not None:
                config_service = SystemConfigService(db)
                port = int(await config_service.get("llm.llamacpp.port", 8085))
            else:
                port = 8085

        # Vérifier le fichier PID
        pid_file = Path(".llamacpp.pid")
        pid = None

        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # Vérifier si le processus existe
                try:
                    os.kill(pid, 0)  # Signal 0 = vérifier existence
                    result["pid"] = pid
                    result["status"] = "running"
                except OSError:
                    # Processus n'existe plus, nettoyer le fichier PID
                    pid_file.unlink(missing_ok=True)
                    pid = None
            except (ValueError, OSError):
                pid = None

        # Fallback: chercher via pgrep si pas de PID valide
        if pid is None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pgrep", "-o", "llama-server",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                if proc.returncode == 0 and stdout.strip():
                    pid = int(stdout.decode().strip())
                    result["pid"] = pid
                    result["status"] = "running"
                    # Mettre à jour le PID file
                    pid_file.write_text(str(pid))
            except Exception as e:
                logger.debug(f"pgrep fallback failed: {e}")

        # Si un PID existe, vérifier la santé via HTTP
        if result["pid"]:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Essayer l'endpoint /health avec le bon port
                    response = await client.get(f"http://localhost:{port}/health")
                    if response.status_code == 200:
                        result["healthy"] = True
                        # Essayer de parser la réponse
                        try:
                            health_data = response.json()
                            result["model_loaded"] = health_data.get("model")
                            result["ctx_size"] = health_data.get("ctx_size")
                            result["gpu_layers"] = health_data.get("n_gpu_layers")
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"llama-server health check failed on port {port}: {e}")
                result["healthy"] = False

        return result

    @staticmethod
    async def get_llm_status(db: AsyncSession) -> dict:
        """
        Récupère le statut complet du provider LLM actif.

        Pour Ollama : vérifie via l'API Ollama
        Pour llama.cpp : utilise get_llamacpp_status()

        Returns:
            Dict complet avec toutes les informations de statut
        """
        config_service = SystemConfigService(db)

        # Déterminer le provider actif
        provider = await config_service.get("llm.provider", settings.llm_provider)

        if provider == "llamacpp":
            # Statut llama.cpp (passer db pour lire le port depuis la BDD)
            llamacpp_status = await ConfigService.get_llamacpp_status(db=db)

            host = await config_service.get("llm.llamacpp_host", "localhost")
            port = await config_service.get("llm.llamacpp.port", 8085)
            model_configured = await config_service.get("llm.llamacpp.llm_model", "")

            return {
                "provider": "llamacpp",
                "status": llamacpp_status["status"],
                "healthy": llamacpp_status["healthy"],
                "host": str(host),
                "port": int(port),
                "url": f"http://{host}:{port}",
                "model_loaded": llamacpp_status["model_loaded"],
                "model_configured": str(model_configured),
                "pid": llamacpp_status["pid"],
                "uptime": llamacpp_status["uptime"],
                "memory_usage": llamacpp_status["memory_usage"],
                "gpu_layers": llamacpp_status["gpu_layers"],
                "ctx_size": llamacpp_status["ctx_size"]
            }
        else:
            # Statut Ollama (géré par Docker)
            host = await config_service.get("llm.ollama_host", settings.ollama_host)
            port = await config_service.get("llm.ollama_port", settings.ollama_port)
            model_configured = await config_service.get("llm.ollama.llm_model", "")

            # Fallback sur anciennes clés
            if not model_configured:
                model_configured = await config_service.get("rag.llm_model", settings.llm_model)

            healthy = False
            model_loaded = None

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"http://{host}:{port}/api/tags")
                    if response.status_code == 200:
                        healthy = True
            except Exception as e:
                logger.debug(f"Ollama health check failed: {e}")

            return {
                "provider": "ollama",
                "status": "managed",  # Géré par Docker Compose
                "healthy": healthy,
                "host": str(host),
                "port": int(port),
                "url": f"http://{host}:{port}",
                "model_loaded": model_loaded,
                "model_configured": str(model_configured),
                "pid": None,  # Pas applicable (Docker)
                "uptime": None,
                "memory_usage": None,
                "gpu_layers": None,
                "ctx_size": None
            }

    @staticmethod
    async def get_provider_health(db: AsyncSession, provider: str) -> dict:
        """
        Récupère le statut de santé d'un provider spécifique (pas forcément l'actif).

        Args:
            db: Session de base de données
            provider: "ollama" ou "llamacpp"

        Returns:
            Dict avec status, healthy, url, etc.
        """
        config_service = SystemConfigService(db)

        if provider == "llamacpp":
            host = await config_service.get("llm.llamacpp_host", "localhost")
            port = await config_service.get("llm.llamacpp_port", 8085)
            model_configured = await config_service.get("llm.llamacpp.llm_model", "")

            # Vérifier la santé
            healthy = False
            status = "stopped"
            model_loaded = None

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"http://{host}:{port}/health")
                    if response.status_code == 200:
                        data = response.json()
                        healthy = data.get("status") == "ok"
                        status = "running" if healthy else "degraded"
            except Exception as e:
                logger.debug(f"llama.cpp health check failed: {e}")
                status = "stopped"

            return {
                "provider": "llamacpp",
                "status": status,
                "healthy": healthy,
                "host": str(host),
                "port": int(port),
                "url": f"http://{host}:{port}",
                "model_loaded": model_loaded,
                "model_configured": str(model_configured),
                "can_start": True,
                "can_stop": True
            }
        else:
            # Ollama
            host = await config_service.get("llm.ollama_host", settings.ollama_host)
            port = await config_service.get("llm.ollama_port", settings.ollama_port)
            model_configured = await config_service.get("llm.ollama.llm_model", "")

            if not model_configured:
                model_configured = await config_service.get("rag.llm_model", settings.llm_model)

            healthy = False
            models_count = 0

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"http://{host}:{port}/api/tags")
                    if response.status_code == 200:
                        healthy = True
                        data = response.json()
                        models_count = len(data.get("models", []))
            except Exception as e:
                logger.debug(f"Ollama health check failed: {e}")

            return {
                "provider": "ollama",
                "status": "running" if healthy else "stopped",
                "healthy": healthy,
                "host": str(host),
                "port": int(port),
                "url": f"http://{host}:{port}",
                "model_configured": str(model_configured),
                "models_count": models_count,
                "can_start": False,  # Géré par Docker
                "can_stop": False    # Géré par Docker
            }

    # ========================================================================
    # PARAMETRES LLAMA.CPP
    # ========================================================================

    @staticmethod
    async def get_llamacpp_params(db: AsyncSession) -> dict:
        """
        Récupère les paramètres llama.cpp depuis la BDD.

        Returns:
            dict avec tous les paramètres llama.cpp
        """
        config_service = SystemConfigService(db)

        # Lire tous les paramètres avec valeurs par défaut
        return {
            "gpu_layers": int(await config_service.get("llm.llamacpp.gpu_layers", 99)),
            "ctx_size": int(await config_service.get("llm.llamacpp.ctx_size", 4096)),
            "threads": int(await config_service.get("llm.llamacpp.threads", -1)),
            "batch_size": int(await config_service.get("llm.llamacpp.batch_size", 2048)),
            "flash_attn": str(await config_service.get("llm.llamacpp.flash_attn", "auto")),
            "parallel": int(await config_service.get("llm.llamacpp.parallel", -1)),
            "port": int(await config_service.get("llm.llamacpp.port", 8085)),
            "embedding_mode": bool(await config_service.get("llm.llamacpp.embedding_mode", False)),
            "metrics_enabled": bool(await config_service.get("llm.llamacpp.metrics_enabled", False)),
            "mlock": bool(await config_service.get("llm.llamacpp.mlock", False)),
            "mmap": bool(await config_service.get("llm.llamacpp.mmap", True)),
        }

    @staticmethod
    async def update_llamacpp_params(
        db: AsyncSession,
        params: "LlamaCppParamsUpdate",
        updated_by: Optional[UUID] = None
    ) -> dict:
        """
        Met à jour les paramètres llama.cpp en BDD.

        Note: Les changements nécessitent un redémarrage de llama-server.

        Args:
            db: Session de base de données
            params: Paramètres à mettre à jour
            updated_by: UUID de l'utilisateur

        Returns:
            Paramètres mis à jour
        """
        config_service = SystemConfigService(db)
        update_dict = params.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "gpu_layers": "llm.llamacpp.gpu_layers",
            "ctx_size": "llm.llamacpp.ctx_size",
            "threads": "llm.llamacpp.threads",
            "batch_size": "llm.llamacpp.batch_size",
            "flash_attn": "llm.llamacpp.flash_attn",
            "parallel": "llm.llamacpp.parallel",
            "port": "llm.llamacpp.port",
            "embedding_mode": "llm.llamacpp.embedding_mode",
            "metrics_enabled": "llm.llamacpp.metrics_enabled",
            "mlock": "llm.llamacpp.mlock",
            "mmap": "llm.llamacpp.mmap",
        }

        # Mettre à jour chaque paramètre modifié
        for field, value in update_dict.items():
            if field in key_mapping:
                await config_service.set(
                    key=key_mapping[field],
                    value=value,
                    updated_by=updated_by
                )
                log_config_change(key_mapping[field], None, value)

        # Retourner les paramètres mis à jour
        return await ConfigService.get_llamacpp_params(db)

    @staticmethod
    async def get_llamacpp_metrics(db: AsyncSession) -> dict:
        """
        Récupère les métriques Prometheus de llama-server.

        Appelle l'endpoint /metrics de llama-server et parse les valeurs.

        Returns:
            dict: Métriques parsées ou erreur
        """
        import httpx

        config_service = SystemConfigService(db)
        host = await config_service.get("llm.llamacpp_host", settings.llamacpp_host)
        port = await config_service.get("llm.llamacpp_port", settings.llamacpp_port)
        url = f"http://{host}:{port}/metrics"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                metrics_text = response.text

            # Parser les métriques Prometheus
            metrics = {
                "available": True,
                "prompt_tokens_total": 0,
                "tokens_predicted_total": 0,
                "prompt_seconds_total": 0.0,
                "tokens_predicted_seconds_total": 0.0,
                "prompt_tokens_per_second": 0.0,
                "predicted_tokens_per_second": 0.0,
                "n_decode_total": 0,
                "requests_processing": 0,
                "requests_deferred": 0,
                "slots_idle": 0,
                "slots_processing": 0,
                "error": None,
            }

            for line in metrics_text.split("\n"):
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].replace("llamacpp:", "")
                    value = parts[1]
                    if key == "prompt_tokens_total":
                        metrics["prompt_tokens_total"] = int(float(value))
                    elif key == "tokens_predicted_total":
                        metrics["tokens_predicted_total"] = int(float(value))
                    elif key == "prompt_seconds_total":
                        metrics["prompt_seconds_total"] = float(value)
                    elif key == "tokens_predicted_seconds_total":
                        metrics["tokens_predicted_seconds_total"] = float(value)
                    elif key == "prompt_tokens_seconds":
                        metrics["prompt_tokens_per_second"] = float(value)
                    elif key == "predicted_tokens_seconds":
                        metrics["predicted_tokens_per_second"] = float(value)
                    elif key == "n_decode_total":
                        metrics["n_decode_total"] = int(float(value))
                    elif key == "requests_processing":
                        metrics["requests_processing"] = int(float(value))
                    elif key == "requests_deferred":
                        metrics["requests_deferred"] = int(float(value))

            # Récupérer slots depuis /health
            try:
                health_response = await client.get(f"http://{host}:{port}/health")
                if health_response.status_code == 200:
                    health_data = health_response.json()
                    metrics["slots_idle"] = health_data.get("slots_idle", 0)
                    metrics["slots_processing"] = health_data.get("slots_processing", 0)
            except Exception:
                pass

            return metrics

        except httpx.HTTPError as e:
            return {
                "available": False,
                "prompt_tokens_total": 0,
                "tokens_predicted_total": 0,
                "prompt_seconds_total": 0.0,
                "tokens_predicted_seconds_total": 0.0,
                "prompt_tokens_per_second": 0.0,
                "predicted_tokens_per_second": 0.0,
                "n_decode_total": 0,
                "requests_processing": 0,
                "requests_deferred": 0,
                "slots_idle": 0,
                "slots_processing": 0,
                "error": f"HTTP error: {str(e)}",
            }
        except Exception as e:
            return {
                "available": False,
                "prompt_tokens_total": 0,
                "tokens_predicted_total": 0,
                "prompt_seconds_total": 0.0,
                "tokens_predicted_seconds_total": 0.0,
                "prompt_tokens_per_second": 0.0,
                "predicted_tokens_per_second": 0.0,
                "n_decode_total": 0,
                "requests_processing": 0,
                "requests_deferred": 0,
                "slots_idle": 0,
                "slots_processing": 0,
                "error": str(e),
            }

    @staticmethod
    async def restart_llamacpp_server(db: AsyncSession) -> dict:
        """
        Redémarre llama-server avec les paramètres depuis la BDD.

        En environnement Docker local, le script ne peut pas contrôler
        llama-server qui tourne sur l'hôte. Retourne les instructions.

        Returns:
            dict avec success, message, status, command
        """
        import os

        # Détecter si on est dans Docker (fichier /.dockerenv existe)
        in_docker = os.path.exists("/.dockerenv")

        if in_docker:
            # En Docker, on ne peut pas contrôler llama-server sur l'hôte
            # Retourner les instructions pour restart manuel
            logger.info("[llama.cpp] Running in Docker - cannot restart host llama-server")

            # Invalider le cache config pour prendre en compte les nouvelles valeurs
            from app.common.llm import invalidate_llamacpp_config_cache
            invalidate_llamacpp_config_cache()

            return {
                "success": False,
                "manual_restart_required": True,
                "message": "llama-server runs on host, not in Docker. Please restart manually.",
                "command": "./scripts/llamacpp.sh restart --from-db",
                "status": "manual"
            }

        # Hors Docker, exécuter le script directement
        import asyncio
        from pathlib import Path

        script_path = Path(__file__).parents[4] / "scripts" / "llamacpp.sh"

        if not script_path.exists():
            logger.error(f"[llama.cpp] Script not found: {script_path}")
            return {
                "success": False,
                "message": f"Script not found: {script_path}",
                "status": "error"
            }

        try:
            logger.info("[llama.cpp] Restarting server with --from-db...")

            # Exécuter le script de restart
            process = await asyncio.create_subprocess_exec(
                str(script_path), "restart", "--from-db",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60.0  # 60s max pour restart
            )

            if process.returncode == 0:
                # Invalider le cache config
                from app.common.llm import invalidate_llamacpp_config_cache
                invalidate_llamacpp_config_cache()

                logger.info("[llama.cpp] Server restarted successfully")
                return {
                    "success": True,
                    "message": "llama-server restarted successfully",
                    "status": "running",
                    "output": stdout.decode()
                }
            else:
                error_msg = stderr.decode() or stdout.decode()
                logger.error(f"[llama.cpp] Restart failed: {error_msg}")
                return {
                    "success": False,
                    "message": f"Restart failed: {error_msg}",
                    "status": "error"
                }

        except asyncio.TimeoutError:
            logger.error("[llama.cpp] Restart timeout (60s)")
            return {
                "success": False,
                "message": "Restart timeout (60s)",
                "status": "timeout"
            }
        except Exception as e:
            logger.error(f"[llama.cpp] Restart error: {e}")
            return {
                "success": False,
                "message": str(e),
                "status": "error"
            }

    @staticmethod
    async def get_llamacpp_running_config(db: AsyncSession) -> dict:
        """
        Récupère la config du serveur llama-server en cours d'exécution.

        Tente d'abord via /props, puis fallback sur parsing des process args.

        Returns:
            dict avec les paramètres du serveur ou dict vide si non disponible
        """
        import httpx
        import re

        config_service = SystemConfigService(db)
        host = await config_service.get("llm.llamacpp.host", "host.docker.internal")
        port = int(await config_service.get("llm.llamacpp.port", 8085))
        base_url = f"http://{host}:{port}"

        try:
            # Option 1: Essayer /props (endpoint llama-server)
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/props")
                if response.status_code == 200:
                    props = response.json()
                    # n_ctx est dans default_generation_settings
                    default_settings = props.get("default_generation_settings", {})
                    return {
                        "ctx_size": default_settings.get("n_ctx"),
                        "batch_size": None,  # Non exposé par /props
                        "gpu_layers": None,  # Non exposé par /props
                        "parallel": props.get("total_slots"),
                        "threads": None,
                        "model": props.get("model_alias"),
                        "embedding_mode": "nomic" in props.get("model_alias", "").lower() or "embed" in props.get("model_alias", "").lower(),
                    }
        except Exception as e:
            logger.debug(f"[llama.cpp] /props not available: {e}")

        # Option 2: Fallback - parser les arguments du process
        try:
            import asyncio
            process = await asyncio.create_subprocess_exec(
                "pgrep", "-a", "llama-server",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            args = stdout.decode()

            if not args:
                return {}

            # Extraire les valeurs des arguments
            config = {}
            patterns = {
                "ctx_size": r"--ctx-size\s+(\d+)",
                "batch_size": r"--batch-size\s+(\d+)",
                "gpu_layers": r"--n-gpu-layers\s+(\d+)",
                "parallel": r"--parallel\s+(\d+)",
                "threads": r"--threads\s+(\d+)",
            }

            for key, pattern in patterns.items():
                match = re.search(pattern, args)
                if match:
                    config[key] = int(match.group(1))

            config["embedding_mode"] = "--embedding" in args

            return config

        except Exception as e:
            logger.debug(f"[llama.cpp] Process parsing failed: {e}")
            return {}

    @staticmethod
    async def compare_llamacpp_configs(db: AsyncSession) -> dict:
        """
        Compare la configuration BDD avec celle du serveur en cours.

        Returns:
            dict avec:
            - in_sync: bool (True si configs identiques)
            - differences: list de différences détectées
            - db_config: config depuis BDD
            - running_config: config du serveur
            - restart_required: bool
            - server_running: bool
        """
        from app.common.llm import get_llamacpp_config
        from dataclasses import asdict

        # Config depuis BDD
        db_config = await get_llamacpp_config(db)
        db_config_dict = asdict(db_config)

        # Config du serveur en cours
        running_config = await ConfigService.get_llamacpp_running_config(db)

        if not running_config:
            return {
                "in_sync": None,  # Impossible de vérifier
                "differences": [],
                "db_config": db_config_dict,
                "running_config": None,
                "restart_required": False,
                "server_running": False
            }

        # Comparer les valeurs critiques
        differences = []
        critical_keys = [
            ("ctx_size", "ctx_size"),
            ("gpu_layers", "gpu_layers"),
            ("parallel", "parallel"),
            ("batch_size", "batch_size"),
            ("embedding_mode", "embedding_mode"),
        ]

        for db_key, run_key in critical_keys:
            db_val = getattr(db_config, db_key, None)
            run_val = running_config.get(run_key)

            # Ignorer si valeur non disponible du serveur (non exposé par /props)
            if run_val is None:
                continue

            # Normaliser -1 (auto) pour la comparaison
            if db_val == -1:
                continue  # Auto = pas de vérification

            # ctx_size: le serveur peut limiter à la capacité du modèle
            # Si serveur < BDD, c'est OK (limite du modèle)
            if db_key == "ctx_size" and run_val < db_val:
                continue  # Serveur limité par le modèle, pas une erreur

            if db_val != run_val:
                differences.append({
                    "key": db_key,
                    "db_value": db_val,
                    "running_value": run_val
                })

        return {
            "in_sync": len(differences) == 0,
            "differences": differences,
            "db_config": db_config_dict,
            "running_config": running_config,
            "restart_required": len(differences) > 0,
            "server_running": True
        }

    # ========================================================================
    # CONFIGURATION OLLAMA
    # ========================================================================

    @staticmethod
    async def get_ollama_config(db: AsyncSession) -> dict:
        """
        Récupère la configuration Ollama depuis la BDD.

        Ces paramètres sont passés via l'API Ollama à chaque requête.

        Returns:
            dict avec tous les paramètres Ollama
        """
        config_service = SystemConfigService(db)

        return {
            "keep_alive": str(await config_service.get("llm.ollama.keep_alive", "5m")),
            "num_ctx": int(await config_service.get("llm.ollama.num_ctx", 2048)),
            "num_gpu": int(await config_service.get("llm.ollama.num_gpu", 999)),
            "num_parallel": int(await config_service.get("llm.ollama.num_parallel", 1)),
            "auto_preload": bool(await config_service.get("llm.ollama.auto_preload", False)),
        }

    @staticmethod
    async def update_ollama_config(
        db: AsyncSession,
        params: OllamaConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> dict:
        """
        Met à jour les paramètres Ollama en BDD.

        Note: Les changements sont appliqués à la prochaine requête.
        Invalide le cache de config Ollama.

        Args:
            db: Session de base de données
            params: Paramètres à mettre à jour
            updated_by: UUID de l'utilisateur

        Returns:
            Paramètres mis à jour
        """
        from app.common.llm import invalidate_ollama_config_cache

        config_service = SystemConfigService(db)
        update_dict = params.model_dump(exclude_unset=True)

        key_mapping = {
            "keep_alive": "llm.ollama.keep_alive",
            "num_ctx": "llm.ollama.num_ctx",
            "num_gpu": "llm.ollama.num_gpu",
            "auto_preload": "llm.ollama.auto_preload",
        }

        for field, value in update_dict.items():
            if field in key_mapping:
                await config_service.set(
                    key=key_mapping[field],
                    value=value,
                    updated_by=updated_by
                )
                log_config_change(key_mapping[field], None, value)

        # Invalider le cache pour que les changements prennent effet
        invalidate_ollama_config_cache()
        logger.info("Ollama config cache invalidated after update")

        return await ConfigService.get_ollama_config(db)

    @staticmethod
    async def preload_ollama_models(db: AsyncSession) -> dict:
        """
        Précharge les modèles Ollama en mémoire.

        Envoie une requête minimale à Ollama pour chaque modèle configuré
        afin de les charger en VRAM. Utilise keep_alive=-1 pour maintenir
        les modèles en mémoire indéfiniment.

        Returns:
            dict avec le statut du préchargement
        """
        import httpx
        from app.common.llm import get_ollama_config

        config_service = SystemConfigService(db)

        # Récupérer la config
        host = await config_service.get("llm.ollama_host", settings.ollama_host)
        port = await config_service.get("llm.ollama_port", settings.ollama_port)
        llm_model = await config_service.get("llm.ollama.llm_model", None)
        embed_model = await config_service.get("llm.ollama.embedding_model", None)
        ollama_config = await get_ollama_config(db)
        base_url = f"http://{host}:{port}"

        result = {
            "success": True,
            "llm_model": llm_model,
            "embed_model": embed_model,
            "llm_status": None,
            "embed_status": None,
            "error": None,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            # Précharger le modèle LLM
            if llm_model:
                try:
                    response = await client.post(
                        f"{base_url}/api/generate",
                        json={
                            "model": llm_model,
                            "prompt": "test",
                            "keep_alive": -1,  # -1 = maintenir indéfiniment (nombre, pas string)
                            "options": {
                                "num_ctx": ollama_config.num_ctx,
                                "num_gpu": ollama_config.num_gpu,
                                "num_predict": 1,
                            },
                        },
                    )
                    if response.status_code == 200:
                        result["llm_status"] = "loaded"
                        logger.info(f"LLM model {llm_model} preloaded successfully")
                    else:
                        result["llm_status"] = f"error: {response.status_code}"
                        result["success"] = False
                except Exception as e:
                    result["llm_status"] = f"error: {str(e)}"
                    result["success"] = False

            # Précharger le modèle d'embedding
            if embed_model:
                try:
                    response = await client.post(
                        f"{base_url}/api/embeddings",
                        json={
                            "model": embed_model,
                            "prompt": "test",
                            "keep_alive": -1,  # -1 = maintenir indéfiniment (nombre, pas string)
                        },
                    )
                    if response.status_code == 200:
                        result["embed_status"] = "loaded"
                        logger.info(f"Embedding model {embed_model} preloaded successfully")
                    else:
                        result["embed_status"] = f"error: {response.status_code}"
                        result["success"] = False
                except Exception as e:
                    result["embed_status"] = f"error: {str(e)}"
                    result["success"] = False

        return result

    @staticmethod
    async def get_server_hardware(db: AsyncSession) -> dict:
        """
        Détecte le hardware GPU en interrogeant les providers LLM actifs.

        Interroge Ollama et/ou llama.cpp selon la configuration pour détecter
        l'utilisation GPU réelle (VRAM pour NVIDIA, Metal pour Apple Silicon).

        Args:
            db: Session de base de données pour lire la config

        Returns:
            dict avec les informations hardware
        """
        import platform

        result = {
            "has_gpu": False,
            "gpu_type": None,
            "gpu_name": None,
            "gpu_memory": None,
            "os": platform.system(),
            "platform": platform.system().lower(),
            "recommended_preset": "cpu",
            "detection_source": None,  # ollama, llamacpp, ou None
        }

        # Lire la configuration des providers depuis la BDD
        config_service = SystemConfigService(db)
        main_provider = await config_service.get("llm.provider", "ollama")
        embedding_provider = await config_service.get("llm.embedding_provider", None)

        # Collecter les providers à interroger (éviter les doublons)
        providers_to_check = set()
        providers_to_check.add(main_provider)
        if embedding_provider:
            providers_to_check.add(embedding_provider)

        logger.debug(f"[Hardware] Checking providers: {providers_to_check}")

        # Interroger Ollama si actif
        if "ollama" in providers_to_check:
            ollama_result = await ConfigService._detect_gpu_from_ollama(db)
            if ollama_result.get("has_gpu"):
                result.update(ollama_result)
                result["detection_source"] = "ollama"
                logger.info(f"[Hardware] GPU detected via Ollama: {result['gpu_name']}")
                return result

        # Interroger llama.cpp si actif
        if "llamacpp" in providers_to_check:
            llamacpp_result = await ConfigService._detect_gpu_from_llamacpp(db)
            if llamacpp_result.get("has_gpu"):
                result.update(llamacpp_result)
                result["detection_source"] = "llamacpp"
                logger.info(f"[Hardware] GPU detected via llama.cpp: {result['gpu_name']}")
                return result

        # Si Ollama a retourné un résultat (même sans GPU), utiliser ses infos
        if "ollama" in providers_to_check:
            ollama_result = await ConfigService._detect_gpu_from_ollama(db)
            if ollama_result.get("detection_source"):
                result.update(ollama_result)

        logger.info(f"[Hardware] No GPU detected, using CPU mode")
        return result

    @staticmethod
    async def _detect_gpu_from_ollama(db: AsyncSession) -> dict:
        """
        Détecte le GPU via l'API Ollama /api/ps.

        Returns:
            dict avec has_gpu, gpu_type, gpu_name, gpu_memory, recommended_preset
        """
        result = {
            "has_gpu": False,
            "gpu_type": None,
            "gpu_name": None,
            "gpu_memory": None,
            "recommended_preset": "cpu",
            "detection_source": None,
        }

        config_service = SystemConfigService(db)
        ollama_host = await config_service.get("llm.ollama.host", settings.ollama_host)
        ollama_port = await config_service.get("llm.ollama.port", settings.ollama_port)
        base_url = f"http://{ollama_host}:{ollama_port}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Vérifier les modèles chargés via /api/ps
                ps_response = await client.get(f"{base_url}/api/ps")
                if ps_response.status_code == 200:
                    ps_data = ps_response.json()
                    models = ps_data.get("models", [])

                    if models:
                        # Analyser l'utilisation VRAM
                        total_vram = sum(m.get("size_vram", 0) for m in models)
                        total_size = sum(m.get("size", 0) for m in models)

                        if total_vram > 0:
                            result["has_gpu"] = True
                            result["detection_source"] = "ollama"

                            # Déterminer le type de GPU
                            vram_mb = total_vram / 1024 / 1024
                            if vram_mb > 0:
                                result["gpu_memory"] = f"{vram_mb:.0f} MB"

                            # Détecter le type de GPU via la config ou l'hôte Ollama
                            # Si Ollama est sur host.docker.internal, c'est probablement un Mac
                            is_mac_host = "host.docker.internal" in ollama_host or ollama_host == "localhost"

                            # Lire la config hardware si définie
                            hardware_type = await config_service.get("server.hardware_type", "auto")

                            if hardware_type == "mac" or (hardware_type == "auto" and is_mac_host):
                                result["gpu_type"] = "apple"
                                result["gpu_name"] = "Apple Silicon (Metal)"
                                result["recommended_preset"] = "mac"
                            elif hardware_type == "nvidia" or hardware_type == "auto":
                                result["gpu_type"] = "nvidia"
                                result["gpu_name"] = f"GPU (VRAM: {vram_mb:.0f} MB)"
                                if vram_mb >= 16000:
                                    result["recommended_preset"] = "gpu16"
                                elif vram_mb >= 8000:
                                    result["recommended_preset"] = "gpu8"
                                else:
                                    result["recommended_preset"] = "gpu8"
                            elif hardware_type == "amd":
                                result["gpu_type"] = "amd"
                                result["gpu_name"] = f"AMD GPU (VRAM: {vram_mb:.0f} MB)"
                                result["recommended_preset"] = "gpu8"
                            return result
                        else:
                            # Modèles chargés mais pas de VRAM = CPU
                            result["detection_source"] = "ollama"
                            return result

                # 2. Aucun modèle chargé - forcer un mini-test
                embed_model = await config_service.get(
                    "llm.ollama.embed_model",
                    settings.ollama_embed_model
                )
                logger.debug(f"[Hardware] No models loaded, triggering mini-test with {embed_model}")

                try:
                    test_response = await client.post(
                        f"{base_url}/api/embeddings",
                        json={
                            "model": embed_model,
                            "prompt": "GPU test",
                            "keep_alive": "1m"
                        },
                        timeout=30.0
                    )
                    if test_response.status_code == 200:
                        # Re-vérifier /api/ps
                        ps_response = await client.get(f"{base_url}/api/ps")
                        if ps_response.status_code == 200:
                            ps_data = ps_response.json()
                            models = ps_data.get("models", [])
                            if models:
                                total_vram = sum(m.get("size_vram", 0) for m in models)
                                if total_vram > 0:
                                    result["has_gpu"] = True
                                    result["detection_source"] = "ollama"
                                    vram_mb = total_vram / 1024 / 1024
                                    result["gpu_memory"] = f"{vram_mb:.0f} MB"

                                    # Détecter le type via config ou hôte
                                    is_mac_host = "host.docker.internal" in ollama_host or ollama_host == "localhost"
                                    hardware_type = await config_service.get("server.hardware_type", "auto")

                                    if hardware_type == "mac" or (hardware_type == "auto" and is_mac_host):
                                        result["gpu_type"] = "apple"
                                        result["gpu_name"] = "Apple Silicon (Metal)"
                                        result["recommended_preset"] = "mac"
                                    else:
                                        result["gpu_type"] = "nvidia"
                                        result["gpu_name"] = f"GPU (VRAM: {vram_mb:.0f} MB)"
                                        result["recommended_preset"] = "gpu8"
                                else:
                                    result["detection_source"] = "ollama"
                except Exception as e:
                    logger.debug(f"[Hardware] Ollama mini-test failed: {e}")

        except Exception as e:
            logger.debug(f"[Hardware] Could not contact Ollama: {e}")

        return result

    @staticmethod
    async def _detect_gpu_from_llamacpp(db: AsyncSession) -> dict:
        """
        Détecte le GPU via l'API llama.cpp /health ou /props.

        Returns:
            dict avec has_gpu, gpu_type, gpu_name, gpu_memory, recommended_preset
        """
        result = {
            "has_gpu": False,
            "gpu_type": None,
            "gpu_name": None,
            "gpu_memory": None,
            "recommended_preset": "cpu",
            "detection_source": None,
        }

        config_service = SystemConfigService(db)
        llamacpp_host = await config_service.get("llm.llamacpp.host", "localhost")
        llamacpp_port = await config_service.get("llm.llamacpp.port", 8085)
        base_url = f"http://{llamacpp_host}:{llamacpp_port}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Vérifier /health
                health_response = await client.get(f"{base_url}/health")
                if health_response.status_code == 200:
                    result["detection_source"] = "llamacpp"

                    # llama.cpp avec GPU layers > 0 = GPU actif
                    # On suppose GPU si llama.cpp répond (sinon il serait trop lent)
                    gpu_layers = await config_service.get("llm.llamacpp.gpu_layers", 99)

                    if gpu_layers and int(gpu_layers) > 0:
                        result["has_gpu"] = True

                        # Détecter le type via config ou hôte
                        is_mac_host = "host.docker.internal" in llamacpp_host or llamacpp_host == "localhost"
                        hardware_type = await config_service.get("server.hardware_type", "auto")

                        if hardware_type == "mac" or (hardware_type == "auto" and is_mac_host):
                            result["gpu_type"] = "apple"
                            result["gpu_name"] = "Apple Silicon (Metal via llama.cpp)"
                            result["recommended_preset"] = "mac"
                        elif hardware_type == "nvidia" or hardware_type == "auto":
                            result["gpu_type"] = "nvidia"
                            result["gpu_name"] = f"GPU ({gpu_layers} layers offloaded)"
                            result["recommended_preset"] = "gpu8"
                        elif hardware_type == "amd":
                            result["gpu_type"] = "amd"
                            result["gpu_name"] = f"AMD GPU ({gpu_layers} layers offloaded)"
                            result["recommended_preset"] = "gpu8"
                    else:
                        # gpu_layers = 0 = CPU mode
                        result["gpu_name"] = "llama.cpp (CPU mode)"

        except Exception as e:
            logger.debug(f"[Hardware] Could not contact llama.cpp: {e}")

        return result

    @staticmethod
    async def get_timeouts_config(db: AsyncSession) -> TimeoutsConfigRead:
        """
        Récupère la configuration des timeouts depuis la BDD.

        Priorité : BDD > runtime_overrides > settings (.env)
        """
        config_service = SystemConfigService(db)

        # Lire depuis BDD avec fallback sur runtime puis settings
        ollama_timeout = await config_service.get(
            "timeout.ollama",
            _runtime_overrides.get('ollama_timeout', settings.ollama_timeout)
        )
        http_timeout = await config_service.get(
            "timeout.http",
            _runtime_overrides.get('http_timeout', settings.http_timeout)
        )
        health_check_timeout = await config_service.get(
            "timeout.health_check",
            _runtime_overrides.get('health_check_timeout', settings.health_check_timeout)
        )

        return TimeoutsConfigRead(
            ollama_timeout=float(ollama_timeout),
            http_timeout=float(http_timeout),
            health_check_timeout=float(health_check_timeout)
        )

    @staticmethod
    async def get_rate_limits_config(db: AsyncSession) -> RateLimitsConfigRead:
        """
        Récupère la configuration des rate limits depuis la BDD.

        Fallback sur les valeurs .env si non définies en BDD.
        """
        config_service = SystemConfigService(db)

        chat = await config_service.get("ratelimit.chat", settings.rate_limit_chat)
        upload = await config_service.get("ratelimit.upload", settings.rate_limit_upload)
        stream = await config_service.get("ratelimit.stream", getattr(settings, 'rate_limit_stream', '30/minute'))
        admin = await config_service.get("ratelimit.admin", settings.rate_limit_admin)

        return RateLimitsConfigRead(
            chat=str(chat),
            upload=str(upload),
            stream=str(stream),
            admin=str(admin)
        )

    @staticmethod
    async def update_rate_limits_config(
        db: AsyncSession,
        config: RateLimitsConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> RateLimitsConfigRead:
        """
        Met à jour la configuration des rate limits en BDD.

        Note: Les changements nécessitent un redémarrage pour être appliqués
        car SlowAPI initialise les limites au démarrage.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "chat": "ratelimit.chat",
            "upload": "ratelimit.upload",
            "stream": "ratelimit.stream",
            "admin": "ratelimit.admin",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Rate limit config updated in DB: {db_key} = {value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        return await ConfigService.get_rate_limits_config(db)

    # ========================================================================
    # MISE À JOUR CONFIGURATION
    # ========================================================================

    @staticmethod
    async def update_rag_config(
        db: AsyncSession,
        config: RAGConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> RAGConfigRead:
        """
        Met à jour la configuration RAG en base de données.

        Les paramètres RAG sont sauvegardés dans le namespace du provider actif :
        - Si provider=ollama : rag.ollama.top_k, rag.ollama.temperature, etc.
        - Si provider=llamacpp : rag.llamacpp.top_k, rag.llamacpp.temperature, etc.

        Les modèles sont également provider-specific :
        - Si provider=ollama : llm.ollama.llm_model, llm.ollama.embedding_model
        - Si provider=llamacpp : llm.llamacpp.llm_model, llm.llamacpp.embedding_model

        Args:
            db: Session de base de données
            config: Nouvelles valeurs de configuration
            updated_by: UUID de l'utilisateur qui fait la modification

        Returns:
            Configuration RAG mise à jour
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        # Déterminer le provider actif
        provider = await config_service.get("llm.provider", settings.llm_provider)

        # Mapping des champs vers les clés en BDD (provider-specific)
        key_mapping = {
            # Paramètres RAG provider-specific
            "top_k": f"rag.{provider}.top_k",
            "similarity_threshold": f"rag.{provider}.similarity_threshold",
            "temperature": f"rag.{provider}.temperature",
            "chunk_size": f"rag.{provider}.chunk_size",
            "chunk_overlap": f"rag.{provider}.chunk_overlap",
            "chunking_strategy": f"rag.{provider}.chunking_strategy",
            "min_chunk_length": f"rag.{provider}.min_chunk_length",
            "keyword_boost": f"rag.{provider}.keyword_boost",
            "stopwords_language": f"rag.{provider}.stopwords_language",
            "use_corpus": f"rag.{provider}.use_corpus",
            "require_sources": f"rag.{provider}.require_sources",
            # max_context_items reste global (non provider-specific)
            "max_context_items": "sources.max_context_items",
            # Modèles provider-specific
            "llm_model": f"llm.{provider}.llm_model",
            "embedding_model": f"llm.{provider}.embedding_model",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"RAG config updated in DB: {db_key} = {value}")

        return await ConfigService.get_rag_config(db)

    @staticmethod
    async def update_timeouts_config(
        db: AsyncSession,
        config: TimeoutsConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> TimeoutsConfigRead:
        """
        Met à jour la configuration des timeouts en BDD.

        Les valeurs sont persistées en BDD et appliquées immédiatement
        via _runtime_overrides pour la session courante.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "ollama_timeout": "timeout.ollama",
            "http_timeout": "timeout.http",
            "health_check_timeout": "timeout.health_check",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                # Persister en BDD
                await config_service.set(db_key, value, updated_by)
                # Appliquer immédiatement en runtime
                _runtime_overrides[field] = value
                logger.info(f"Timeout config updated in DB: {db_key} = {value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        return await ConfigService.get_timeouts_config(db)

    # ========================================================================
    # RESET CONFIGURATION
    # ========================================================================

    @staticmethod
    async def reload_config(db: AsyncSession) -> SystemConfigRead:
        """
        Recharge la configuration depuis les valeurs par défaut.
        Efface tous les overrides runtime (timeouts uniquement).
        Les valeurs RAG en base de données ne sont pas affectées.

        Args:
            db: Session de base de données

        Returns:
            Configuration système rechargée
        """
        global _runtime_overrides
        _runtime_overrides = {}

        logger.info("Configuration reloaded - runtime overrides cleared (timeouts)")

        return await ConfigService.get_system_config(db)

    @staticmethod
    def get_runtime_overrides() -> Dict[str, Any]:
        """
        Récupère les overrides runtime actuels.

        Returns:
            Dictionnaire des overrides
        """
        return _runtime_overrides.copy()

    # ========================================================================
    # CONFIGURATION SPEECH (Speech-to-Text)
    # ========================================================================

    @staticmethod
    async def get_speech_config(db: AsyncSession) -> SpeechConfigRead:
        """
        Récupère la configuration Speech-to-Text depuis la base de données.
        Inclut les paramètres auto-envoi (STT) et TTS.
        """
        config_service = SystemConfigService(db)

        enabled = await config_service.get("speech.enabled", True)
        model = await config_service.get("speech.model", "small")
        default_language = await config_service.get("speech.default_language", "fr")
        max_duration = await config_service.get("speech.max_duration", 60)
        timeout = await config_service.get("speech.timeout", 120)

        # Auto-envoi (STT)
        auto_send_enabled = await config_service.get("speech.auto_send_enabled", True)
        silence_duration_ms = await config_service.get("speech.silence_duration_ms", 1500)
        silence_threshold = await config_service.get("speech.silence_threshold", 0.01)

        # TTS
        tts_enabled = await config_service.get("speech.tts_enabled", True)
        tts_mode = await config_service.get("speech.tts_mode", "native")
        tts_default_rate = await config_service.get("speech.tts_default_rate", 1.0)

        # Récupérer le modèle actuellement chargé (depuis variable d'env du container)
        import os
        current_model = os.environ.get("WHISPER__MODEL", "unknown")

        # Warning si le modèle configuré diffère du modèle chargé
        warning = None
        if model != current_model and current_model != "unknown":
            warning = f"Le modele configure ({model}) differe du modele charge ({current_model}). Redemarrage du container Whisper necessaire."

        return SpeechConfigRead(
            enabled=bool(enabled),
            model=str(model),
            default_language=str(default_language),
            max_duration=int(max_duration),
            timeout=int(timeout),
            auto_send_enabled=bool(auto_send_enabled),
            silence_duration_ms=int(silence_duration_ms),
            silence_threshold=float(silence_threshold),
            tts_enabled=bool(tts_enabled),
            tts_mode=str(tts_mode),
            tts_default_rate=float(tts_default_rate),
            current_model_loaded=current_model if current_model != "unknown" else None,
            model_change_warning=warning
        )

    @staticmethod
    async def update_speech_config(
        db: AsyncSession,
        config: SpeechConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> SpeechConfigRead:
        """
        Met à jour la configuration Speech-to-Text en base de données.
        Inclut les paramètres auto-envoi et TTS.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "enabled": "speech.enabled",
            "model": "speech.model",
            "default_language": "speech.default_language",
            "max_duration": "speech.max_duration",
            "timeout": "speech.timeout",
            # Auto-envoi (STT)
            "auto_send_enabled": "speech.auto_send_enabled",
            "silence_duration_ms": "speech.silence_duration_ms",
            "silence_threshold": "speech.silence_threshold",
            # TTS
            "tts_enabled": "speech.tts_enabled",
            "tts_mode": "speech.tts_mode",
            "tts_default_rate": "speech.tts_default_rate",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Speech config updated in DB: {db_key} = {value}")

        # Invalider le cache du SpeechService
        from app.features.speech.service import SpeechService
        SpeechService.invalidate_cache()

        return await ConfigService.get_speech_config(db)

    # ========================================================================
    # CONFIGURATION SOURCES INDEXATION
    # ========================================================================

    @staticmethod
    async def get_sources_indexation_config(db: AsyncSession) -> SourcesIndexationConfigRead:
        """
        Récupère la configuration d'indexation des sources depuis la base de données.
        """
        config_service = SystemConfigService(db)

        # Scheduler
        scheduler_enabled = await config_service.get("sources.scheduler_enabled", True)
        scheduler_check_interval = await config_service.get("sources.scheduler_check_interval_minutes", 15)
        scheduler_cleanup_docs = await config_service.get("sources.scheduler_cleanup_docs_interval_hours", 1)
        scheduler_cleanup_logs = await config_service.get("sources.scheduler_cleanup_logs_interval_days", 1)

        # Retention
        log_retention = await config_service.get("sources.log_retention_days", 30)

        # Freshness thresholds
        freshness_warning = await config_service.get("sources.freshness_warning_percent", 30)
        freshness_expired = await config_service.get("sources.freshness_expired_percent", 0)

        # Récupérer le statut du scheduler
        try:
            from app.features.sources.scheduler import get_scheduler_status
            scheduler_status = get_scheduler_status()
        except Exception:
            scheduler_status = {"running": False, "jobs": []}

        return SourcesIndexationConfigRead(
            scheduler_enabled=bool(scheduler_enabled),
            scheduler_check_interval_minutes=int(scheduler_check_interval),
            scheduler_cleanup_docs_interval_hours=int(scheduler_cleanup_docs),
            scheduler_cleanup_logs_interval_days=int(scheduler_cleanup_logs),
            log_retention_days=int(log_retention),
            freshness_warning_percent=int(freshness_warning),
            freshness_expired_percent=int(freshness_expired),
            scheduler_status=scheduler_status
        )

    @staticmethod
    async def update_sources_indexation_config(
        db: AsyncSession,
        config: SourcesIndexationConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> SourcesIndexationConfigRead:
        """
        Met à jour la configuration d'indexation des sources en base de données.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "scheduler_enabled": "sources.scheduler_enabled",
            "scheduler_check_interval_minutes": "sources.scheduler_check_interval_minutes",
            "scheduler_cleanup_docs_interval_hours": "sources.scheduler_cleanup_docs_interval_hours",
            "scheduler_cleanup_logs_interval_days": "sources.scheduler_cleanup_logs_interval_days",
            "log_retention_days": "sources.log_retention_days",
            "freshness_warning_percent": "sources.freshness_warning_percent",
            "freshness_expired_percent": "sources.freshness_expired_percent",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Sources indexation config updated in DB: {db_key} = {value}")

        # Recharger le scheduler si nécessaire
        if "scheduler_enabled" in update_dict:
            try:
                from app.features.sources.scheduler import start_scheduler, stop_scheduler
                if update_dict["scheduler_enabled"]:
                    start_scheduler()
                    logger.info("Scheduler started")
                else:
                    stop_scheduler()
                    logger.info("Scheduler stopped")
            except Exception as e:
                logger.error(f"Error toggling scheduler: {e}")

        return await ConfigService.get_sources_indexation_config(db)

    # ========================================================================
    # CONFIGURATION CHAT (MÉMOIRE CONVERSATIONNELLE)
    # ========================================================================

    @staticmethod
    async def get_chat_config(db: AsyncSession) -> ChatConfigRead:
        """
        Récupère la configuration chat (mémoire conversationnelle) depuis la BDD.

        Les 9 paramètres sont persistés en BDD via SystemConfig.
        """
        config_service = SystemConfigService(db)

        return ChatConfigRead(
            history_enabled=await config_service.get("chat.history_enabled", True),
            history_max_turns=await config_service.get("chat.history_max_turns", 5),
            history_max_tokens=await config_service.get("chat.history_max_tokens", 4096),
            topic_detection_enabled=await config_service.get("chat.topic_detection_enabled", True),
            topic_similarity_threshold=await config_service.get("chat.topic_similarity_threshold", 0.3),
            summary_enabled=await config_service.get("chat.summary_enabled", True),
            summary_trigger_messages=await config_service.get("chat.summary_trigger_messages", 10),
            rag_reinjection_enabled=await config_service.get("chat.rag_reinjection_enabled", True),
            contextualization_enabled=await config_service.get("chat.contextualization_enabled", True),
        )

    @staticmethod
    async def update_chat_config(
        db: AsyncSession,
        config: ChatConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> ChatConfigRead:
        """
        Met à jour la configuration chat (mémoire conversationnelle).

        Les paramètres sont persistés en BDD et pris en compte immédiatement
        (lecture dynamique par le service de chat, pas de cache).
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "history_enabled": "chat.history_enabled",
            "history_max_turns": "chat.history_max_turns",
            "history_max_tokens": "chat.history_max_tokens",
            "topic_detection_enabled": "chat.topic_detection_enabled",
            "topic_similarity_threshold": "chat.topic_similarity_threshold",
            "summary_enabled": "chat.summary_enabled",
            "summary_trigger_messages": "chat.summary_trigger_messages",
            "rag_reinjection_enabled": "chat.rag_reinjection_enabled",
            "contextualization_enabled": "chat.contextualization_enabled",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Chat config persisted in DB: {db_key} = {value}")

        return await ConfigService.get_chat_config(db)

    # ========================================================================
    # CONFIGURATION DEBUG
    # ========================================================================

    @staticmethod
    async def get_debug_config(db: AsyncSession) -> DebugConfigRead:
        """
        Récupère la configuration debug depuis la BDD.

        Les 3 paramètres sont persistés en BDD et appliqués en runtime.
        Fallback sur les variables d'environnement si absent en BDD.
        """
        config_service = SystemConfigService(db)

        # Lire les 3 valeurs depuis la BDD avec fallback
        verbose_logging = await config_service.get("debug.verbose_logging", False)
        timing_headers = await config_service.get("debug.timing_headers_enabled", False)

        # Endpoints debug : exclusivement depuis la BDD
        db_endpoints = await config_service.get("debug.endpoints_enabled", False)
        debug_endpoints = bool(db_endpoints)

        # Niveau de log effectif
        current_level = logging.getLogger().getEffectiveLevel()
        current_log_level = logging.getLevelName(current_level)

        return DebugConfigRead(
            verbose_logging=bool(verbose_logging),
            timing_headers_enabled=bool(timing_headers),
            debug_endpoints_enabled=debug_endpoints,
            current_log_level=current_log_level
        )

    @staticmethod
    async def update_debug_config(
        db: AsyncSession,
        config: DebugConfigUpdate,
        updated_by: Optional[UUID] = None
    ) -> DebugConfigRead:
        """
        Met à jour la configuration debug.

        Les 3 paramètres sont persistés en BDD et appliqués en runtime.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "verbose_logging": "debug.verbose_logging",
            "timing_headers_enabled": "debug.timing_headers_enabled",
            "debug_endpoints_enabled": "debug.endpoints_enabled",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Debug config persisted in DB: {db_key} = {value}")
                # Log de sécurité pour changements de config sensible
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        # Appliquer en runtime
        if 'verbose_logging' in update_dict:
            _runtime_overrides['debug_verbose_logging'] = update_dict['verbose_logging']
            _apply_log_level(update_dict['verbose_logging'])

        if 'timing_headers_enabled' in update_dict:
            _runtime_overrides['debug_timing_headers'] = update_dict['timing_headers_enabled']
            logger.info(f"Debug timing headers applied: {update_dict['timing_headers_enabled']}")

        if 'debug_endpoints_enabled' in update_dict:
            _runtime_overrides['debug_endpoints_enabled'] = update_dict['debug_endpoints_enabled']
            logger.info(f"Debug endpoints applied: {update_dict['debug_endpoints_enabled']}")

        return await ConfigService.get_debug_config(db)

    @staticmethod
    async def apply_debug_config_from_db(db: AsyncSession) -> None:
        """
        Restaure la configuration debug depuis la BDD au démarrage.

        Lit les 3 paramètres persistés et les applique en runtime
        (_runtime_overrides + log level).
        """
        config_service = SystemConfigService(db)

        verbose_logging = await config_service.get("debug.verbose_logging", False)
        timing_headers = await config_service.get("debug.timing_headers_enabled", False)
        debug_endpoints = await config_service.get("debug.endpoints_enabled", None)

        _runtime_overrides['debug_verbose_logging'] = bool(verbose_logging)
        _runtime_overrides['debug_timing_headers'] = bool(timing_headers)
        if debug_endpoints is not None:
            _runtime_overrides['debug_endpoints_enabled'] = bool(debug_endpoints)

        # Appliquer le log level si verbose activé en BDD
        if bool(verbose_logging):
            _apply_log_level(True)

        logger.info(
            f"Debug config restored from DB: verbose={verbose_logging}, "
            f"timing_headers={timing_headers}, endpoints={debug_endpoints}"
        )

    # ========================================================================
    # CONFIGURATION LOGGING STRUCTURÉ
    # ========================================================================

    @staticmethod
    async def get_logging_config(db: AsyncSession) -> LoggingConfigRead:
        """
        Récupère la configuration logging structuré depuis la BDD.

        Retourne les niveaux par catégorie, l'état de la persistance BDD
        et les durées de rétention.
        """
        config_service = SystemConfigService(db)

        return LoggingConfigRead(
            log_level_technical=str(await config_service.get("logging.level_technical", "INFO")),
            log_level_access=str(await config_service.get("logging.level_access", "INFO")),
            log_level_audit=str(await config_service.get("logging.level_audit", "INFO")),
            log_level_security=str(await config_service.get("logging.level_security", "INFO")),
            log_level_infra=str(await config_service.get("logging.level_infra", "INFO")),
            log_db_enabled=bool(await config_service.get("logging.db_enabled", True)),
            log_retention_technical_days=int(await config_service.get("logging.retention_technical_days", 30)),
            log_retention_access_days=int(await config_service.get("logging.retention_access_days", 30)),
            log_retention_audit_days=int(await config_service.get("logging.retention_audit_days", 365)),
            log_retention_security_days=int(await config_service.get("logging.retention_security_days", 365)),
            log_retention_infra_days=int(await config_service.get("logging.retention_infra_days", 14)),
            alert_cooldown_minutes=int(await config_service.get("logging.alert_cooldown_minutes", 15)),
        )

    @staticmethod
    async def update_logging_config(
        db: AsyncSession,
        config: LoggingConfigUpdate,
        updated_by: Optional[UUID] = None,
    ) -> LoggingConfigRead:
        """
        Met à jour la configuration logging en BDD et applique immédiatement.

        Les niveaux par catégorie sont persistés en BDD et appliqués
        au handler BDD via _runtime_overrides.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "log_level_technical": "logging.level_technical",
            "log_level_access": "logging.level_access",
            "log_level_audit": "logging.level_audit",
            "log_level_security": "logging.level_security",
            "log_level_infra": "logging.level_infra",
            "log_db_enabled": "logging.db_enabled",
            "log_retention_technical_days": "logging.retention_technical_days",
            "log_retention_access_days": "logging.retention_access_days",
            "log_retention_audit_days": "logging.retention_audit_days",
            "log_retention_security_days": "logging.retention_security_days",
            "log_retention_infra_days": "logging.retention_infra_days",
            "alert_cooldown_minutes": "logging.alert_cooldown_minutes",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Logging config updated in DB: {db_key} = {value}")
                # Log de sécurité
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        # Appliquer les niveaux au handler BDD si disponible
        _apply_logging_levels(update_dict)

        return await ConfigService.get_logging_config(db)

    # ========================================================================
    # NOTIFICATIONS
    # ========================================================================

    @staticmethod
    async def get_notification_config(db: AsyncSession) -> NotificationConfigRead:
        """
        Récupère la configuration des notifications depuis la BDD.

        Retourne l'état de chaque canal (email, Slack, webhook)
        et leurs paramètres de connexion.
        """
        config_service = SystemConfigService(db)

        return NotificationConfigRead(
            email_enabled=bool(await config_service.get("notification.email_enabled", False)),
            email_smtp_host=str(await config_service.get("notification.email_smtp_host", "")),
            email_smtp_port=int(await config_service.get("notification.email_smtp_port", 587)),
            email_smtp_user=str(await config_service.get("notification.email_smtp_user", "")),
            email_smtp_password=str(await config_service.get("notification.email_smtp_password", "")),
            email_smtp_tls=bool(await config_service.get("notification.email_smtp_tls", True)),
            email_from_address=str(await config_service.get("notification.email_from_address", "")),
            email_to_addresses=str(await config_service.get("notification.email_to_addresses", "")),
            slack_enabled=bool(await config_service.get("notification.slack_enabled", False)),
            slack_webhook_url=str(await config_service.get("notification.slack_webhook_url", "")),
            webhook_enabled=bool(await config_service.get("notification.webhook_enabled", False)),
            webhook_url=str(await config_service.get("notification.webhook_url", "")),
            webhook_secret=str(await config_service.get("notification.webhook_secret", "")),
        )

    @staticmethod
    async def update_notification_config(
        db: AsyncSession,
        config: NotificationConfigUpdate,
        updated_by: Optional[UUID] = None,
    ) -> NotificationConfigRead:
        """
        Met à jour la configuration des notifications en BDD.
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        key_mapping = {
            "email_enabled": "notification.email_enabled",
            "email_smtp_host": "notification.email_smtp_host",
            "email_smtp_port": "notification.email_smtp_port",
            "email_smtp_user": "notification.email_smtp_user",
            "email_smtp_password": "notification.email_smtp_password",
            "email_smtp_tls": "notification.email_smtp_tls",
            "email_from_address": "notification.email_from_address",
            "email_to_addresses": "notification.email_to_addresses",
            "slack_enabled": "notification.slack_enabled",
            "slack_webhook_url": "notification.slack_webhook_url",
            "webhook_enabled": "notification.webhook_enabled",
            "webhook_url": "notification.webhook_url",
            "webhook_secret": "notification.webhook_secret",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                # Ne pas logger les valeurs sensibles
                log_value = "***" if "password" in field or "secret" in field else str(value)
                logger.info(f"Notification config updated: {db_key} = {log_value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=log_value,
                )

        return await ConfigService.get_notification_config(db)

    # ========================================================================
    # SMTP (Email Service)
    # ========================================================================

    @staticmethod
    async def get_smtp_config(db: AsyncSession) -> SmtpConfigRead:
        """
        Récupère la configuration SMTP depuis la BDD.

        Les secrets (password, API keys) ne sont pas retournés,
        seul leur état de configuration est indiqué.
        """
        config_service = SystemConfigService(db)

        # Vérifier si les secrets sont configurés (sans les exposer)
        password = await config_service.get("smtp.password", "")
        sendgrid_key = await config_service.get("smtp.sendgrid_api_key", "")
        mailjet_key = await config_service.get("smtp.mailjet_api_key", "")

        return SmtpConfigRead(
            provider=str(await config_service.get("smtp.provider", "smtp")),
            enabled=bool(await config_service.get("smtp.enabled", False)),
            host=str(await config_service.get("smtp.host", "")),
            port=int(await config_service.get("smtp.port", 587)),
            username=str(await config_service.get("smtp.username", "")),
            use_tls=bool(await config_service.get("smtp.use_tls", True)),
            use_ssl=bool(await config_service.get("smtp.use_ssl", False)),
            password_configured=bool(password),
            from_email=str(await config_service.get("smtp.from_email", "")),
            from_name=str(await config_service.get("smtp.from_name", "MY-IA")),
            reply_to=str(await config_service.get("smtp.reply_to", "")),
            sendgrid_configured=bool(sendgrid_key),
            mailjet_configured=bool(mailjet_key),
            last_test_at=await config_service.get("smtp.last_test_at", None),
            last_test_success=await config_service.get("smtp.last_test_success", None),
        )

    @staticmethod
    async def update_smtp_config(
        db: AsyncSession,
        config: SmtpConfigUpdate,
        updated_by: Optional[UUID] = None,
    ) -> SmtpConfigRead:
        """
        Met à jour la configuration SMTP en BDD.

        Les secrets sont chiffrés avant stockage.
        """
        from app.common.utils.crypto import encrypt_secret

        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "provider": "smtp.provider",
            "enabled": "smtp.enabled",
            "host": "smtp.host",
            "port": "smtp.port",
            "username": "smtp.username",
            "password": "smtp.password",
            "use_tls": "smtp.use_tls",
            "use_ssl": "smtp.use_ssl",
            "from_email": "smtp.from_email",
            "from_name": "smtp.from_name",
            "reply_to": "smtp.reply_to",
            "sendgrid_api_key": "smtp.sendgrid_api_key",
            "mailjet_api_key": "smtp.mailjet_api_key",
            "mailjet_secret_key": "smtp.mailjet_secret_key",
        }

        # Champs sensibles à chiffrer
        sensitive_fields = {"password", "sendgrid_api_key", "mailjet_api_key", "mailjet_secret_key"}

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                is_sensitive = field in sensitive_fields

                # Chiffrer les secrets
                if is_sensitive and value:
                    value = encrypt_secret(value)

                await config_service.set(
                    db_key, value, updated_by,
                    is_sensitive=is_sensitive
                )

                # Log sans exposer les valeurs sensibles
                log_value = "***" if field in sensitive_fields else str(value)
                logger.info(f"SMTP config updated: {db_key} = {log_value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=log_value,
                )

        return await ConfigService.get_smtp_config(db)

    @staticmethod
    async def test_smtp_connection(
        db: AsyncSession,
        recipient_email: str,
        admin_user_email: str,
    ) -> SmtpTestResponse:
        """
        Teste la connexion SMTP en envoyant un email de test.

        Args:
            db: Session de base de données
            recipient_email: Email destinataire (ou email de l'admin si vide)
            admin_user_email: Email de l'admin connecté (fallback)

        Returns:
            SmtpTestResponse avec le résultat du test
        """
        import time
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from app.common.utils.crypto import decrypt_secret, is_encrypted

        config_service = SystemConfigService(db)
        start_time = time.time()

        # Récupérer la config
        provider = str(await config_service.get("smtp.provider", "smtp"))
        enabled = bool(await config_service.get("smtp.enabled", False))

        if not enabled:
            return SmtpTestResponse(
                success=False,
                message="Le service email n'est pas activé",
                provider=provider,
                recipient=recipient_email or admin_user_email,
                duration_ms=0,
            )

        recipient = recipient_email or admin_user_email

        try:
            if provider == "smtp":
                # Configuration SMTP
                host = str(await config_service.get("smtp.host", ""))
                port = int(await config_service.get("smtp.port", 587))
                username = str(await config_service.get("smtp.username", ""))
                password_raw = str(await config_service.get("smtp.password", ""))
                use_tls = bool(await config_service.get("smtp.use_tls", True))
                use_ssl = bool(await config_service.get("smtp.use_ssl", False))
                from_email = str(await config_service.get("smtp.from_email", ""))
                from_name = str(await config_service.get("smtp.from_name", "MY-IA"))

                if not host or not from_email:
                    return SmtpTestResponse(
                        success=False,
                        message="Configuration SMTP incomplète (host ou from_email manquant)",
                        provider=provider,
                        recipient=recipient,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )

                # Déchiffrer le mot de passe si nécessaire
                password = decrypt_secret(password_raw) if is_encrypted(password_raw) else password_raw

                # Créer le message de test
                msg = MIMEMultipart()
                msg["From"] = f"{from_name} <{from_email}>"
                msg["To"] = recipient
                msg["Subject"] = "[MY-IA] Test de configuration SMTP"

                body = """
                <html>
                <body style="font-family: Arial, sans-serif; padding: 20px;">
                    <h2 style="color: #1e3a5f;">Test SMTP réussi</h2>
                    <p>Ce message confirme que la configuration SMTP de MY-IA fonctionne correctement.</p>
                    <hr style="border: 1px solid #eee;">
                    <p style="color: #666; font-size: 12px;">
                        Envoyé depuis le backoffice MY-IA
                    </p>
                </body>
                </html>
                """
                msg.attach(MIMEText(body, "html"))

                # Envoyer via aiosmtplib
                await aiosmtplib.send(
                    msg,
                    hostname=host,
                    port=port,
                    username=username if username else None,
                    password=password if password else None,
                    use_tls=use_ssl,  # SSL = connexion chiffrée directe
                    start_tls=use_tls and not use_ssl,  # STARTTLS = upgrade
                    timeout=30,
                )

                duration_ms = int((time.time() - start_time) * 1000)

                # Enregistrer le succès du test
                await config_service.set("smtp.last_test_at", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
                await config_service.set("smtp.last_test_success", True)

                return SmtpTestResponse(
                    success=True,
                    message=f"Email de test envoyé avec succès à {recipient}",
                    provider=provider,
                    recipient=recipient,
                    duration_ms=duration_ms,
                )

            else:
                # SendGrid ou Mailjet (à implémenter dans Phase 3)
                return SmtpTestResponse(
                    success=False,
                    message=f"Provider '{provider}' non encore implémenté",
                    provider=provider,
                    recipient=recipient,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            await config_service.set("smtp.last_test_at", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
            await config_service.set("smtp.last_test_success", False)
            return SmtpTestResponse(
                success=False,
                message="Échec d'authentification SMTP. Vérifiez le nom d'utilisateur et le mot de passe.",
                provider=provider,
                recipient=recipient,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        except aiosmtplib.SMTPConnectError as e:
            logger.error(f"SMTP connection failed: {e}")
            await config_service.set("smtp.last_test_at", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
            await config_service.set("smtp.last_test_success", False)
            return SmtpTestResponse(
                success=False,
                message=f"Impossible de se connecter au serveur SMTP. Vérifiez l'hôte et le port.",
                provider=provider,
                recipient=recipient,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.error(f"SMTP test failed: {e}", exc_info=True)
            await config_service.set("smtp.last_test_at", time.strftime("%Y-%m-%dT%H:%M:%SZ"))
            await config_service.set("smtp.last_test_success", False)
            return SmtpTestResponse(
                success=False,
                message=f"Erreur lors du test: {str(e)}",
                provider=provider,
                recipient=recipient,
                duration_ms=int((time.time() - start_time) * 1000),
            )

    # =========================================================================
    # GEO CONFIG
    # =========================================================================

    @staticmethod
    async def get_geo_config(db: AsyncSession) -> GeoConfigRead:
        """
        Récupère la configuration géographique depuis la BDD.

        Retourne:
        - default_country: Code pays par défaut
        - require_city: Exiger une ville
        - allow_change: Permettre le changement
        """
        config_service = SystemConfigService(db)

        return GeoConfigRead(
            default_country=str(await config_service.get("geo.default_country", "FR")),
            require_city=bool(await config_service.get("geo.require_city", False)),
            allow_change=bool(await config_service.get("geo.allow_change", True)),
        )

    @staticmethod
    async def update_geo_config(
        db: AsyncSession,
        config: GeoConfigUpdate,
        updated_by: Optional[UUID] = None,
    ) -> GeoConfigRead:
        """
        Met à jour la configuration géographique.

        Args:
            db: Session de base de données
            config: Nouvelles valeurs
            updated_by: UUID de l'admin effectuant la modification

        Returns:
            GeoConfigRead avec la nouvelle configuration
        """
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "default_country": "geo.default_country",
            "require_city": "geo.require_city",
            "allow_change": "geo.allow_change",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Geo config updated: {db_key} = {value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        return await ConfigService.get_geo_config(db)

    # =========================================================================
    # APPEARANCE CONFIG
    # =========================================================================

    @staticmethod
    async def get_appearance_config(db: AsyncSession) -> "AppearanceConfigRead":
        """
        Récupère la configuration d'apparence depuis la BDD.

        Retourne:
        - global_theme: Thème global (default, corporate, nature, sunset, royal)
        """
        from app.features.admin.config.schemas import AppearanceConfigRead
        config_service = SystemConfigService(db)

        return AppearanceConfigRead(
            global_theme=str(await config_service.get("appearance.global_theme", "default")),
        )

    @staticmethod
    async def update_appearance_config(
        db: AsyncSession,
        config: "AppearanceConfigUpdate",
        updated_by: Optional[UUID] = None,
    ) -> "AppearanceConfigRead":
        """
        Met à jour la configuration d'apparence.

        Args:
            db: Session de base de données
            config: Nouvelles valeurs
            updated_by: UUID de l'admin effectuant la modification

        Returns:
            AppearanceConfigRead avec la nouvelle configuration
        """
        from app.features.admin.config.schemas import AppearanceConfigUpdate
        config_service = SystemConfigService(db)
        update_dict = config.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "global_theme": "appearance.global_theme",
        }

        for field, value in update_dict.items():
            db_key = key_mapping.get(field)
            if db_key:
                await config_service.set(db_key, value, updated_by)
                logger.info(f"Appearance config updated: {db_key} = {value}")
                log_config_change(
                    admin_id=str(updated_by) if updated_by else "system",
                    config_key=db_key,
                    new_value=str(value),
                )

        return await ConfigService.get_appearance_config(db)


# Mapping des niveaux texte vers les constantes logging
_LEVEL_MAP = {
    "TRACE": 5,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "FATAL": logging.CRITICAL,
}


def _apply_logging_levels(update_dict: Dict[str, Any]) -> None:
    """
    Applique les niveaux de logging par catégorie au handler BDD.

    Appelé après mise à jour de la config via l'admin UI.
    """
    from app.core.logging import _db_handler, LogCategory

    if _db_handler is None:
        return

    category_map = {
        "log_level_technical": LogCategory.TECHNICAL.value,
        "log_level_access": LogCategory.ACCESS.value,
        "log_level_audit": LogCategory.AUDIT.value,
        "log_level_security": LogCategory.SECURITY.value,
        "log_level_infra": LogCategory.INFRA.value,
    }

    for field, category in category_map.items():
        if field in update_dict:
            level_name = update_dict[field]
            level = _LEVEL_MAP.get(level_name, logging.INFO)
            _db_handler._db_levels[category] = level
            logger.info(f"DB log level for {category} set to {level_name}")
