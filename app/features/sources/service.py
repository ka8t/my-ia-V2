"""
Service Sources - Logique metier
"""
import logging
import time
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextSource
from app.features.sources.repository import SourceRepository
from app.features.sources.schemas import (
    SourceCreate, SourceUpdate, SourceRead,
    HealthCheckResponse, SourceTestResponse, HealthStatus,
    SourceIndexStats
)
from app.features.sources.connectors import MCPConnector, WebConnector, DatabaseConnector, ApiConnector
from app.features.sources.indexer import SourceIndexer

logger = logging.getLogger(__name__)


class SourceService:
    """Service pour la gestion des sources de contexte"""

    CONNECTOR_MAP = {
        'mcp': MCPConnector,
        'web': WebConnector,
        'database': DatabaseConnector,
        'api': ApiConnector
    }

    @staticmethod
    def _to_source_read(source: ContextSource, include_corpus: bool = False) -> SourceRead:
        """Convertit un modèle ContextSource en SourceRead"""
        corpus_count = 0
        corpus_names = []
        if include_corpus and hasattr(source, 'corpus_sources') and source.corpus_sources:
            corpus_count = len(source.corpus_sources)
            corpus_names = [cs.corpus.display_name for cs in source.corpus_sources if cs.corpus]
        return SourceRead(
            id=source.id,
            name=source.name,
            display_name=source.display_name,
            description=source.description,
            source_type=source.source_type,
            config=source.config,
            is_enabled=source.is_enabled,
            timeout_seconds=source.timeout_seconds,
            max_results=source.max_results,
            priority=source.priority,
            health_status=source.health_status,
            last_health_check=source.last_health_check,
            last_latency_ms=source.last_latency_ms,
            index_enabled=source.index_enabled,
            index_ttl_hours=source.index_ttl_hours,
            auto_refresh=source.auto_refresh,
            refresh_interval_hours=source.refresh_interval_hours,
            replace_on_refresh=source.replace_on_refresh,
            last_indexed_at=source.last_indexed_at,
            last_content_hash=source.last_content_hash,
            chunk_count=source.chunk_count,
            indexed_provider=source.indexed_provider,
            corpus_count=corpus_count,
            corpus_names=corpus_names,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )

    @staticmethod
    def _get_connector(source: ContextSource):
        """Retourne le connecteur approprie pour une source"""
        connector_class = SourceService.CONNECTOR_MAP.get(source.source_type)
        if not connector_class:
            raise ValueError(f"Type de source inconnu: {source.source_type}")
        return connector_class(
            config=source.config,
            timeout=source.timeout_seconds,
            max_results=source.max_results,
            source_name=source.name,
            display_name=source.display_name
        )

    @staticmethod
    async def list_sources(
        db: AsyncSession,
        is_enabled: Optional[bool] = None,
        source_type: Optional[str] = None,
        search: Optional[str] = None,
        provider_filter: Optional[str] = None,
        limit: int = 25,
        offset: int = 0
    ) -> tuple[List[SourceRead], int]:
        """Liste toutes les sources avec pagination

        Args:
            provider_filter: Si fourni, filtre par indexed_provider = provider OR IS NULL
        """
        sources, total = await SourceRepository.get_all(
            db, is_enabled, source_type, search=search,
            provider_filter=provider_filter, limit=limit, offset=offset
        )
        # Enrichir avec corpus_count et corpus_names (relations chargées par le repository)
        return [SourceService._to_source_read(s, include_corpus=True) for s in sources], total

    @staticmethod
    async def get_source(db: AsyncSession, source_id: UUID) -> Optional[SourceRead]:
        """Recupere une source par ID"""
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None
        return SourceService._to_source_read(source, include_corpus=True)

    @staticmethod
    async def create_source(db: AsyncSession, data: SourceCreate) -> SourceRead:
        """Cree une nouvelle source (sans indexation - voir trigger_initial_indexation)"""
        # Verifier unicite du nom
        existing = await SourceRepository.get_by_name(db, data.name)
        if existing:
            raise ValueError(f"Une source avec le nom '{data.name}' existe deja")

        source = ContextSource(
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            source_type=data.source_type.value,
            config=data.config,
            is_enabled=data.is_enabled,
            timeout_seconds=data.timeout_seconds,
            max_results=data.max_results,
            priority=data.priority,
            # Champs d'indexation
            index_enabled=data.index_enabled,
            index_ttl_hours=data.index_ttl_hours,
            auto_refresh=data.auto_refresh,
            refresh_interval_hours=data.refresh_interval_hours,
            replace_on_refresh=data.replace_on_refresh,
        )

        # Valider la config du connecteur
        connector = SourceService._get_connector(source)
        if not connector.validate_config():
            raise ValueError("Configuration invalide pour ce type de source")

        created = await SourceRepository.create(db, source)

        return SourceService._to_source_read(created)

    @staticmethod
    async def trigger_initial_indexation(source_id: UUID) -> None:
        """
        Déclenche l'indexation initiale d'une source en tâche de fond.

        Crée le log d'indexation AVANT de lancer l'indexation pour permettre
        au frontend de suivre la progression immédiatement.
        """
        from app.db import async_session_maker
        from app.features.sources.scheduler import reindex_source
        from app.features.sources.history import IndexationHistoryService
        from app.features.system.service import SystemConfigService

        async with async_session_maker() as db:
            source = await SourceRepository.get_by_id(db, source_id)
            if not source:
                logger.error(f"Source {source_id} non trouvée pour indexation initiale")
                return

            if not source.index_enabled:
                logger.info(f"Source '{source.name}' : index_enabled=false, pas d'indexation")
                return

            # Créer le log AVANT pour que le polling frontend puisse le trouver
            log_entry = await IndexationHistoryService.start_indexation(
                db=db,
                source_id=source_id,
                trigger_type="on_create",
                triggered_by=None
            )
            await db.commit()

            # Récupérer le provider actif pour l'indexation
            config_service = SystemConfigService(db)
            provider = await config_service.get("llm.provider", "ollama")

            logger.info(f"Source '{source.name}' : démarrage indexation initiale (provider={provider})")
            try:
                await reindex_source(
                    db=db,
                    source=source,
                    trigger_type="on_create",
                    triggered_by=None,
                    log_id=str(log_entry.id),
                    provider=provider
                )
                logger.info(f"Source '{source.name}' indexée avec succès")
            except Exception as e:
                logger.error(f"Échec indexation initiale pour '{source.name}': {e}")

    @staticmethod
    async def update_source(
        db: AsyncSession,
        source_id: UUID,
        data: SourceUpdate
    ) -> Optional[SourceRead]:
        """Met a jour une source avec synchronisation ChromaDB si index_enabled change"""
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            source = await SourceRepository.get_by_id(db, source_id)
            return SourceService._to_source_read(source) if source else None

        # Récupérer la source actuelle pour détecter les changements d'index_enabled
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None

        # Détecter le changement de index_enabled
        new_index_enabled = update_data.get('index_enabled')
        if new_index_enabled is not None and new_index_enabled != source.index_enabled:
            old_index_enabled = source.index_enabled

            if new_index_enabled and not old_index_enabled:
                # Activer l'indexation : réindexer la source
                logger.info(f"Activating indexation for source '{source.name}', triggering reindex")
                # La réindexation sera faite après la mise à jour
                updated = await SourceRepository.update(db, source_id, update_data)
                if updated:
                    # Importer et exécuter la réindexation
                    from app.features.sources.scheduler import reindex_source
                    try:
                        await reindex_source(
                            db=db,
                            source=updated,
                            trigger_type="manual",
                            triggered_by=None
                        )
                        logger.info(f"Source '{source.name}' reindexed successfully")
                    except Exception as e:
                        logger.error(f"Failed to reindex source '{source.name}': {e}")
                        # Ne pas faire échouer la mise à jour si la réindexation échoue
                return SourceService._to_source_read(updated) if updated else None

            elif not new_index_enabled and old_index_enabled:
                # Désactiver l'indexation : supprimer les chunks de ChromaDB
                try:
                    deleted_count = await SourceIndexer.delete_source_documents(db, source.name)
                    # Mettre à jour le chunk_count à 0
                    update_data['chunk_count'] = 0
                    logger.info(f"Disabled indexation for source '{source.name}', deleted {deleted_count} chunks from ChromaDB")
                except Exception as e:
                    logger.error(f"ChromaDB cleanup failed when disabling indexation for '{source.name}': {e}")

        updated = await SourceRepository.update(db, source_id, update_data)
        return SourceService._to_source_read(updated) if updated else None

    @staticmethod
    async def clear_source_index(db: AsyncSession, source_id: UUID) -> int:
        """
        Vide uniquement l'index ChromaDB d'une source (sans supprimer la source en BDD).

        Args:
            db: Session DB
            source_id: ID de la source

        Returns:
            Nombre de chunks supprimés
        """
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return 0

        # Supprimer les chunks de ChromaDB via l'indexer
        deleted_count = await SourceIndexer.delete_source_documents(db, source.name)

        # Mettre à jour les compteurs
        if deleted_count > 0:
            source.chunk_count = 0
            source.last_indexed_at = None
            await db.commit()
            logger.info(f"Source {source.name}: index vidé ({deleted_count} chunks supprimés)")

        return deleted_count

    @staticmethod
    async def delete_source(db: AsyncSession, source_id: UUID) -> dict:
        """
        Supprime une source et son contenu indexé.

        Ordre : ChromaDB → BDD.
        Si ChromaDB échoue, la source n'est PAS supprimée en BDD.

        Returns:
            Dict avec deleted (bool)

        Raises:
            RuntimeError: Si le nettoyage ChromaDB échoue
        """
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return {"deleted": False}

        source_name = source.name

        # 1. Nettoyage ChromaDB EN PREMIER — propage l'exception si échec
        deleted_count = await SourceIndexer.delete_source_documents(db, source_name)
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} indexed documents for source '{source_name}'")

        # 2. Supprimer la source en BDD (seulement si ChromaDB a réussi)
        db_deleted = await SourceRepository.delete(db, source_id)

        return {"deleted": db_deleted}

    @staticmethod
    async def toggle_source(db: AsyncSession, source_id: UUID) -> Optional[SourceRead]:
        """Active/desactive une source"""
        toggled = await SourceRepository.toggle(db, source_id)
        return SourceService._to_source_read(toggled) if toggled else None

    @staticmethod
    async def health_check(db: AsyncSession, source_id: UUID) -> Optional[HealthCheckResponse]:
        """Verifie la sante d'une source"""
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None

        start_time = time.time()
        try:
            connector = SourceService._get_connector(source)
            result = await connector.health_check()
            latency_ms = int((time.time() - start_time) * 1000)

            # Mettre a jour le statut en BDD
            status = HealthStatus.HEALTHY if result.get('status') == 'healthy' else HealthStatus.UNHEALTHY
            await SourceRepository.update(db, source_id, {
                'health_status': status.value,
                'last_health_check': datetime.now(timezone.utc),
                'last_latency_ms': latency_ms
            })

            return HealthCheckResponse(
                source_id=source.id,
                source_name=source.name,
                status=status,
                latency_ms=latency_ms,
                error=result.get('error')
            )

        except Exception as e:
            logger.error(f"Health check failed for {source.name}: {e}")
            await SourceRepository.update(db, source_id, {
                'health_status': HealthStatus.UNHEALTHY.value,
                'last_health_check': datetime.now(timezone.utc)
            })
            return HealthCheckResponse(
                source_id=source.id,
                source_name=source.name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=None,
                error=str(e)
            )

    @staticmethod
    async def test_source(
        db: AsyncSession,
        source_id: UUID,
        query: str
    ) -> Optional[SourceTestResponse]:
        """Teste une source avec une requete"""
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None

        start_time = time.time()
        try:
            connector = SourceService._get_connector(source)
            results = await connector.search(query)
            latency_ms = int((time.time() - start_time) * 1000)

            return SourceTestResponse(
                success=True,
                results=[r.model_dump() for r in results],
                latency_ms=latency_ms,
                error=None
            )

        except Exception as e:
            logger.error(f"Test failed for {source.name}: {e}")
            return SourceTestResponse(
                success=False,
                results=[],
                latency_ms=int((time.time() - start_time) * 1000),
                error=str(e)
            )

    # ========================================================================
    # INDEXATION
    # ========================================================================

    @staticmethod
    async def get_source_index_stats(db: AsyncSession, source_id: UUID) -> Optional[SourceIndexStats]:
        """Récupère les statistiques d'indexation d'une source"""
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None

        stats = await SourceIndexer.get_source_stats(db, source.name)
        return SourceIndexStats(
            source_id=source_id,
            source_name=source.name,
            indexed_count=stats.get("indexed_count", 0),
            valid_count=stats.get("valid_count", 0),
            expired_count=stats.get("expired_count", 0),
            last_indexed_at=stats.get("last_indexed_at"),
            index_enabled=stats.get("index_enabled", False),
            ttl_hours=stats.get("ttl_hours", 24)
        )

    @staticmethod
    async def clear_source_index(db: AsyncSession, source_id: UUID) -> Optional[int]:
        """Vide l'index d'une source"""
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            return None

        deleted_count = await SourceIndexer.delete_source_documents(db, source.name)
        # Mettre à jour le chunk_count à 0
        await SourceRepository.update(db, source_id, {'chunk_count': 0})
        logger.info(f"Cleared {deleted_count} indexed documents for source '{source.name}'")
        return deleted_count

    # ========================================================================
    # BULK OPERATIONS
    # ========================================================================

    @staticmethod
    async def bulk_enable_sources(db: AsyncSession, source_ids: List[UUID]) -> dict:
        """
        Active plusieurs sources en masse.

        Args:
            db: Session de base de données
            source_ids: Liste des IDs à activer

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk enable sources: {len(source_ids)} sources")

        for source_id in source_ids:
            try:
                source = await SourceRepository.get_by_id(db, source_id)
                if not source:
                    failed_ids.append(source_id)
                    logger.warning(f"Bulk enable: source {source_id} non trouvée")
                    continue

                if source.is_enabled:
                    # Déjà activée, compter comme succès
                    success_count += 1
                    continue

                await SourceRepository.update(db, source_id, {'is_enabled': True})
                success_count += 1

            except Exception as e:
                failed_ids.append(source_id)
                logger.error(f"Bulk enable: erreur pour {source_id}: {e}")

        logger.info(f"Bulk enable terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_disable_sources(db: AsyncSession, source_ids: List[UUID]) -> dict:
        """
        Désactive plusieurs sources en masse.

        Args:
            db: Session de base de données
            source_ids: Liste des IDs à désactiver

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk disable sources: {len(source_ids)} sources")

        for source_id in source_ids:
            try:
                source = await SourceRepository.get_by_id(db, source_id)
                if not source:
                    failed_ids.append(source_id)
                    logger.warning(f"Bulk disable: source {source_id} non trouvée")
                    continue

                if not source.is_enabled:
                    # Déjà désactivée, compter comme succès
                    success_count += 1
                    continue

                await SourceRepository.update(db, source_id, {'is_enabled': False})
                success_count += 1

            except Exception as e:
                failed_ids.append(source_id)
                logger.error(f"Bulk disable: erreur pour {source_id}: {e}")

        logger.info(f"Bulk disable terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_delete_sources(db: AsyncSession, source_ids: List[UUID]) -> dict:
        """
        Supprime plusieurs sources en masse.

        Ordre par source : ChromaDB → BDD.
        Si ChromaDB échoue pour une source, celle-ci est marquée failed (non supprimée en BDD).

        Args:
            db: Session de base de données
            source_ids: Liste des IDs à supprimer

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []

        logger.info(f"Bulk delete sources: {len(source_ids)} sources")

        for source_id in source_ids:
            try:
                source = await SourceRepository.get_by_id(db, source_id)
                if not source:
                    failed_ids.append(source_id)
                    logger.warning(f"Bulk delete: source {source_id} non trouvée")
                    continue

                # 1. Nettoyage ChromaDB EN PREMIER — si échec, source marquée failed
                await SourceIndexer.delete_source_documents(db, source.name)

                # 2. Supprimer en BDD (seulement si ChromaDB a réussi)
                await SourceRepository.delete(db, source_id)
                success_count += 1

            except Exception as e:
                failed_ids.append(source_id)
                logger.error(f"Bulk delete: erreur pour {source_id}: {e}")

        logger.info(f"Bulk delete terminé: {success_count} succès, {len(failed_ids)} échecs")

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }
