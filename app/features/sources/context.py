"""
Integration des sources externes avec le RAG

Fusionne les resultats des sources externes avec ChromaDB.
Supporte l'indexation des résultats et l'appel conditionnel.
"""
import logging
import asyncio
import time
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.features.sources.repository import SourceRepository
from app.features.sources.service import SourceService
from app.features.sources.schemas import ContextResult
from app.features.sources.indexer import SourceIndexer
from app.features.system.service import SystemConfigService
from app.models import (
    Collection,
    Corpus,
    CorpusCollection,
    CollectionSource,
    ContextSource,
    CorpusSource,
)

logger = logging.getLogger(__name__)


class SourceContextService:
    """Service d'enrichissement du contexte RAG via sources externes"""

    @staticmethod
    async def is_sources_enabled(db: AsyncSession) -> bool:
        """Verifie si les sources sont activees globalement"""
        config_service = SystemConfigService(db)
        return await config_service.get("sources.enabled", False)

    @staticmethod
    async def get_collection_source_ids(
        db: AsyncSession,
        collection_id: str,
        include_global: bool = True
    ) -> List[str]:
        """
        Récupère les IDs des sources assignées à une collection.

        Args:
            db: Session base de données
            collection_id: ID de la collection
            include_global: Inclure les sources non assignées à aucune collection

        Returns:
            Liste des IDs de sources (chaînes)
        """
        from uuid import UUID

        source_ids = []

        # 1. Récupérer les sources explicitement assignées à cette collection
        # Filtre: is_enabled ET chunk_count > 0 (sources indexées uniquement)
        result = await db.execute(
            select(CollectionSource.source_id, ContextSource.name, ContextSource.chunk_count)
            .join(ContextSource, CollectionSource.source_id == ContextSource.id)
            .where(
                CollectionSource.collection_id == UUID(collection_id),
                CollectionSource.is_enabled == True,
                ContextSource.is_enabled == True
            )
            .order_by(CollectionSource.priority)
        )
        rows = result.all()
        assigned_ids = []
        skipped_names = []
        for row in rows:
            if row[2] > 0:  # chunk_count > 0
                assigned_ids.append(str(row[0]))
            else:
                skipped_names.append(row[1])

        if skipped_names:
            logger.warning(
                f"Collection {collection_id}: sources ignorées (non indexées): {', '.join(skipped_names)}"
            )

        source_ids.extend(assigned_ids)

        # 2. Optionnellement inclure les sources globales (non assignées)
        if include_global:
            # Trouver les sources qui ne sont assignées à AUCUNE collection
            assigned_result = await db.execute(
                select(CollectionSource.source_id).distinct()
            )
            all_assigned = {row[0] for row in assigned_result.all()}

            # Filtre: is_enabled ET chunk_count > 0 (sources indexées uniquement)
            global_result = await db.execute(
                select(ContextSource.id, ContextSource.name, ContextSource.chunk_count)
                .where(
                    ContextSource.is_enabled == True,
                    ContextSource.chunk_count > 0,  # Ignorer les sources non indexées
                    ~ContextSource.id.in_(all_assigned) if all_assigned else True
                )
            )
            global_rows = global_result.all()
            global_ids = [str(row[0]) for row in global_rows]

            # Ajouter les globales après les assignées (priorité plus basse)
            for gid in global_ids:
                if gid not in source_ids:
                    source_ids.append(gid)

        logger.debug(
            f"Collection {collection_id}: {len(assigned_ids)} assigned sources, "
            f"{len(source_ids) - len(assigned_ids)} global sources"
        )
        return source_ids

    @staticmethod
    async def get_corpus_source_ids(
        db: AsyncSession,
        corpus_id: str
    ) -> List[str]:
        """
        Récupère les IDs des sources assignées à un corpus.

        Args:
            db: Session base de données
            corpus_id: ID du corpus

        Returns:
            Liste des IDs de sources (chaînes), ordonnée par priorité
        """
        from uuid import UUID

        # Filtre: is_enabled ET chunk_count > 0 (sources indexées uniquement)
        result = await db.execute(
            select(CorpusSource.source_id, ContextSource.name, ContextSource.chunk_count)
            .join(ContextSource, CorpusSource.source_id == ContextSource.id)
            .where(
                CorpusSource.corpus_id == UUID(corpus_id),
                CorpusSource.is_enabled == True,
                ContextSource.is_enabled == True
            )
            .order_by(CorpusSource.priority)
        )
        rows = result.all()
        source_ids = []
        skipped_names = []
        for row in rows:
            if row[2] > 0:  # chunk_count > 0
                source_ids.append(str(row[0]))
            else:
                skipped_names.append(row[1])

        if skipped_names:
            logger.warning(
                f"Corpus {corpus_id}: sources ignorées (non indexées): {', '.join(skipped_names)}"
            )

        logger.debug(f"Corpus {corpus_id}: {len(source_ids)} sources (indexées)")
        return source_ids

    @staticmethod
    async def get_corpus_collection_names(
        db: AsyncSession,
        corpus_id: str
    ) -> List[str]:
        """
        Récupère les noms des collections d'un corpus.

        Args:
            db: Session base de données
            corpus_id: ID du corpus

        Returns:
            Liste des noms de collections, ordonnée par priorité
        """
        from uuid import UUID

        result = await db.execute(
            select(Collection.name)
            .join(CorpusCollection, CorpusCollection.collection_id == Collection.id)
            .where(CorpusCollection.corpus_id == UUID(corpus_id))
            .order_by(CorpusCollection.priority)
        )
        collection_names = [row[0] for row in result.all()]

        logger.debug(f"Corpus {corpus_id}: {len(collection_names)} collections")
        return collection_names

    @staticmethod
    async def get_corpus_by_name(
        db: AsyncSession,
        corpus_name: str
    ) -> Optional[str]:
        """
        Récupère l'ID d'un corpus par son nom.

        Args:
            db: Session base de données
            corpus_name: Nom (slug) du corpus

        Returns:
            ID du corpus ou None si non trouvé
        """
        result = await db.execute(
            select(Corpus.id).where(
                Corpus.name == corpus_name,
                Corpus.is_active == True
            )
        )
        row = result.scalar_one_or_none()
        return str(row) if row else None

    @staticmethod
    async def get_collection_corpus_id(
        db: AsyncSession,
        collection_id: str
    ) -> Optional[str]:
        """
        Récupère l'ID du corpus assigné à une collection.

        Args:
            db: Session base de données
            collection_id: ID de la collection

        Returns:
            ID du corpus ou None si aucun corpus assigné
        """
        from uuid import UUID

        result = await db.execute(
            select(Collection.corpus_id)
            .join(Corpus, Collection.corpus_id == Corpus.id)
            .where(
                Collection.id == UUID(collection_id),
                Corpus.is_active == True
            )
        )
        row = result.scalar_one_or_none()
        return str(row) if row else None

    @staticmethod
    async def resolve_source_ids(
        db: AsyncSession,
        source_ids: Optional[List[str]] = None,
        collection_id: Optional[str] = None
    ) -> Optional[List[str]]:
        """
        Résout les IDs de sources à utiliser selon la configuration.

        Logique de priorité:
        1. Si rag.use_corpus=true ET collection a un corpus assigné:
           -> Utilise les sources du corpus assigné à la collection
        2. Sinon si rag.source_filter_by_collection=true ET collection_id fourni:
           -> Utilise les sources assignées directement à la collection
        3. Sinon:
           -> Utilise source_ids tel quel (sélection manuelle utilisateur)

        Args:
            db: Session base de données
            source_ids: IDs fournis par l'utilisateur (sélection manuelle)
            collection_id: ID de la collection active

        Returns:
            Liste d'IDs de sources à utiliser, ou None si aucune
        """
        config_service = SystemConfigService(db)

        # Mode 1: Corpus (automatique via collection.corpus_id)
        use_corpus = await config_service.get("rag.use_corpus", False)
        if use_corpus and collection_id:
            # Récupérer le corpus assigné à la collection
            corpus_id = await SourceContextService.get_collection_corpus_id(db, collection_id)
            if corpus_id:
                resolved_ids = await SourceContextService.get_corpus_source_ids(db, corpus_id)
                logger.info(
                    f"Source filtering by corpus: {len(resolved_ids)} sources for corpus {corpus_id} (collection {collection_id})"
                )
                return resolved_ids if resolved_ids else None

        # Mode 2: Filtrage par collection (sources assignées directement)
        filter_by_collection = await config_service.get(
            "rag.source_filter_by_collection", False
        )
        if filter_by_collection and collection_id:
            include_global = await config_service.get(
                "rag.include_global_sources", True
            )
            resolved_ids = await SourceContextService.get_collection_source_ids(
                db, collection_id, include_global
            )
            logger.info(
                f"Source filtering by collection: {len(resolved_ids)} sources for collection {collection_id}"
            )
            return resolved_ids if resolved_ids else None

        # Mode 3: Sélection manuelle utilisateur
        return source_ids

    @staticmethod
    async def get_sources_context(
        db: AsyncSession,
        query: str,
        source_ids: Optional[List[str]] = None
    ) -> List[ContextResult]:
        """
        Recupere le contexte depuis les sources selectionnees.

        IMPORTANT: Les sources externes sont OPTIONNELLES par defaut.
        Si source_ids est None ou vide, aucune source externe n'est interrogee.
        L'utilisateur doit explicitement selectionner les sources a utiliser.

        Args:
            db: Session base de donnees
            query: Question de l'utilisateur
            source_ids: Liste des IDs de sources a interroger (None/[] = aucune)

        Returns:
            Liste de resultats de contexte
        """
        # Sources externes optionnelles : si aucune source selectionnee, ne rien faire
        if not source_ids:
            logger.debug("No source_ids provided, skipping external sources (opt-in)")
            return []

        # Verifier si les sources sont activees globalement
        if not await SourceContextService.is_sources_enabled(db):
            return []

        config_service = SystemConfigService(db)
        parallel = await config_service.get("sources.parallel_execution", True)
        global_timeout = await config_service.get("sources.global_timeout", 60)
        max_items = await config_service.get("sources.max_context_items", 10)

        # Recuperer uniquement les sources selectionnees par l'utilisateur
        sources, _ = await SourceRepository.get_all(db, is_enabled=True, source_ids=source_ids)
        if not sources:
            return []

        # Filtrer les sources non indexées (chunk_count = 0) pour éviter les timeouts
        # Ces sources n'ont pas de contenu à rechercher et bloqueraient le système
        indexed_sources = []
        skipped_sources = []
        for source in sources:
            if source.chunk_count > 0:
                indexed_sources.append(source)
            else:
                skipped_sources.append(source.name)

        if skipped_sources:
            logger.warning(
                f"⚠️ Sources ignorées (non indexées, chunk_count=0): {', '.join(skipped_sources)}. "
                f"Veuillez indexer ces sources depuis l'admin ou les désactiver."
            )

        sources = indexed_sources
        if not sources:
            return []

        results: List[ContextResult] = []

        async def query_source(source) -> List[ContextResult]:
            """Interroge une source"""
            try:
                connector = SourceService._get_connector(source)
                return await connector.search(query)
            except asyncio.TimeoutError:
                logger.warning(f"Source {source.name} timeout")
                return []
            except Exception as e:
                logger.error(f"Source {source.name} error: {e}")
                return []

        # Execution parallele ou sequentielle
        try:
            if parallel:
                tasks = [query_source(s) for s in sources]
                all_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=global_timeout
                )
                for result in all_results:
                    if isinstance(result, list):
                        results.extend(result)
            else:
                for source in sources:
                    source_results = await asyncio.wait_for(
                        query_source(source),
                        timeout=source.timeout_seconds
                    )
                    results.extend(source_results)

        except asyncio.TimeoutError:
            logger.warning(f"Global sources timeout after {global_timeout}s")

        # Limiter le nombre de resultats
        return results[:max_items]

    @staticmethod
    def merge_contexts(
        chroma_context: List[Dict[str, Any]],
        sources_context: List[ContextResult]
    ) -> List[Dict[str, Any]]:
        """
        Fusionne les contextes ChromaDB et sources externes.

        Les resultats des sources sont convertis au meme format que ChromaDB.
        """
        merged = list(chroma_context)  # Copie

        for source_result in sources_context:
            # Utiliser display_name si disponible, sinon source_name
            display = source_result.display_name or source_result.source_name
            merged.append({
                "content": source_result.content,
                "metadata": {
                    "source": source_result.source_url or f"Source:{display}",
                    "type": source_result.source_type.value,
                    "source_name": display,  # Nom d'affichage pour l'UI
                    **(source_result.metadata or {})
                },
                "distance": None,
                "similarity": None
            })

        return merged

    @staticmethod
    async def get_smart_context(
        db: AsyncSession,
        query: str,
        chroma_results: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        collection_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère le contexte de manière intelligente.

        IMPORTANT: Les sources externes sont OPTIONNELLES (opt-in).
        Si source_ids est None ou vide, seuls les documents locaux sont utilisés.
        SAUF si:
        - rag.use_corpus=true ET la collection a un corpus assigné: utilise les sources du corpus
        - rag.source_filter_by_collection=true: utilise les sources de la collection

        Comportement quand des sources sont sélectionnées:
        1. Cherche dans les sources indexées (cache)
        2. Appelle TOUJOURS les sources externes sélectionnées en temps réel

        Args:
            db: Session base de données
            query: Question de l'utilisateur
            chroma_results: Résultats déjà obtenus de ChromaDB (documents utilisateur)
            user_id: ID de l'utilisateur (optionnel)
            source_ids: Liste des IDs de sources a interroger (None/[] = aucune)
            collection_name: Nom de la collection active (pour filtrage automatique)

        Returns:
            Liste fusionnée de contextes
        """
        total_start = time.time()

        # Résoudre l'ID de la collection à partir du nom
        collection_id = None
        if collection_name:
            coll_result = await db.execute(
                select(Collection.id).where(Collection.name == collection_name)
            )
            row = coll_result.scalar_one_or_none()
            if row:
                collection_id = str(row)

        # Résoudre les sources à utiliser (corpus automatique via collection, ou manuel)
        resolved_source_ids = await SourceContextService.resolve_source_ids(
            db, source_ids, collection_id
        )

        # Sources externes optionnelles : si aucune source selectionnee, retourner uniquement ChromaDB
        if not resolved_source_ids:
            return chroma_results

        # Vérifier si les sources sont activées globalement
        if not await SourceContextService.is_sources_enabled(db):
            return chroma_results

        # Charger la configuration
        config = await SourceIndexer.get_config(db)
        min_similarity = config["min_similarity"]
        config_service = SystemConfigService(db)
        max_items = await config_service.get("sources.max_context_items", 10)

        logger.debug(
            f"Smart context: {len(chroma_results)} ChromaDB results, "
            f"{len(resolved_source_ids)} sources selected"
        )

        # Récupérer les sources sélectionnées pour le filtrage
        selected_sources, _ = await SourceRepository.get_all(db, is_enabled=True, source_ids=resolved_source_ids)
        source_names = [s.name for s in selected_sources] if selected_sources else None

        # Séparer les sources indexées (utiliser cache) des non-indexées (appel live)
        indexed_sources = [s for s in selected_sources if s.chunk_count > 0]
        live_sources = [s for s in selected_sources if s.chunk_count == 0]

        live_results = []
        indexed_results_converted = []
        live_time = 0
        fresh_results = []

        # Étape 1: Appeler UNIQUEMENT les sources NON indexées en live (API temps réel, etc.)
        # Les sources indexées (chunk_count > 0) utilisent le cache ChromaDB (beaucoup plus rapide)
        if live_sources:
            live_source_ids = [str(s.id) for s in live_sources]
            live_source_names = [s.name for s in live_sources]
            logger.info(
                f"Calling {len(live_source_ids)} NON-indexed external sources live: "
                f"{', '.join(live_source_names)}"
            )

            t0 = time.time()
            fresh_results = await SourceContextService.get_sources_context(db, query, live_source_ids)
            live_time = int((time.time() - t0) * 1000)

            if fresh_results:
                logger.info(f"[TIMING] Live external sources: {live_time}ms -> {len(fresh_results)} results")

                # Convertir les résultats externes (LIVE = priorité maximale)
                for source_result in fresh_results:
                    # Utiliser display_name si disponible, sinon source_name
                    display = source_result.display_name or source_result.source_name
                    live_results.append({
                        "content": source_result.content,
                        "metadata": {
                            "source": source_result.source_url or f"Source:{display}",
                            "type": source_result.source_type.value,
                            "source_name": display,  # Nom d'affichage pour l'UI
                            **(source_result.metadata or {})
                        },
                        "distance": None,
                        "similarity": None,
                        "source_type": "external_live"
                    })

                # Indexer les nouveaux résultats pour les prochaines requêtes
                if config["index_results"]:
                    indexed_count = await SourceIndexer.index_results(db, fresh_results, query)
                    logger.info(f"Indexed {indexed_count} new external source results")
            else:
                logger.info(f"[TIMING] Live external sources: {live_time}ms -> 0 results")
        else:
            # Pas de sources non-indexées - utiliser uniquement le cache
            if indexed_sources:
                indexed_names = [s.name for s in indexed_sources]
                logger.info(
                    f"Using {len(indexed_sources)} INDEXED sources (cache): "
                    f"{', '.join(indexed_names)}"
                )

        # Étape 2: Chercher dans les sources externes indexées (cache) - complément
        t0 = time.time()
        indexed_results = await SourceIndexer.search_indexed_sources(
            db, query, top_k=max_items, similarity_threshold=min_similarity,
            source_names=source_names
        )
        indexed_time = int((time.time() - t0) * 1000)

        if indexed_results:
            logger.info(f"[TIMING] Indexed sources search: {indexed_time}ms -> {len(indexed_results)} results")
            indexed_results_converted.extend(indexed_results)

        # Fusionner avec priorité : CHROMA > LIVE > INDEXED
        # Les documents utilisateur (ChromaDB) sont prioritaires sur les sources externes
        all_results = list(chroma_results) + live_results + indexed_results_converted

        total_time = int((time.time() - total_start) * 1000)
        logger.info(
            f"[TIMING] Smart context total: {total_time}ms "
            f"(live:{live_time}ms, indexed:{indexed_time}ms) "
            f"-> {len(live_results)} live + {len(indexed_results_converted)} indexed + {len(chroma_results)} chroma"
        )

        # Limiter et retourner
        return all_results[:max_items]

    @staticmethod
    async def cleanup_expired_indexed(db: AsyncSession) -> int:
        """
        Nettoie les résultats indexés expirés.

        À appeler périodiquement (tâche cron ou au démarrage).

        Returns:
            Nombre de documents supprimés
        """
        return await SourceIndexer.cleanup_expired(db)

    @staticmethod
    async def get_indexer_stats(db: AsyncSession) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'indexeur de sources.

        Returns:
            Dictionnaire avec les stats
        """
        return await SourceIndexer.get_stats(db)
