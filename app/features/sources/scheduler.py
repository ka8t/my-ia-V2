"""
Scheduler pour les tâches périodiques automatisées

Utilise APScheduler pour exécuter des tâches périodiques:
- Vérification et ré-indexation des sources avec auto_refresh activé
- Nettoyage des vieux logs d'indexation
- Nettoyage des documents expirés dans ChromaDB
- Nettoyage des documents orphelins
- Purge des logs applicatifs (table app_logs) par catégorie

Les intervalles sont configurables via la table system_config:
- sources.scheduler_check_interval_minutes
- sources.scheduler_cleanup_docs_interval_hours
- sources.scheduler_cleanup_logs_interval_days
- logging.retention_*_days (par catégorie)
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.features.sources.history import IndexationHistoryService
from app.features.sources.indexer import SourceIndexer
from app.features.sources.service import SourceService
from app.features.sources.schemas import ContextResult, SourceType
from app.features.system.service import SystemConfigService

logger = logging.getLogger(__name__)

# Instance globale du scheduler
_scheduler: Optional[AsyncIOScheduler] = None

# Cache des configs (mis à jour périodiquement)
_config_cache: Dict[str, Any] = {
    "scheduler_enabled": True,
    "scheduler_check_interval_minutes": 15,
    "scheduler_cleanup_docs_interval_hours": 1,
    "scheduler_cleanup_logs_interval_days": 1,
    "log_retention_days": 30,
}


async def load_config_from_db() -> Dict[str, Any]:
    """
    Charge la configuration d'indexation depuis la base de données.

    Returns:
        Dict avec les valeurs de configuration
    """
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session_maker() as db:
            config_service = SystemConfigService(db)

            config = {
                "scheduler_enabled": await config_service.get("sources.scheduler_enabled", True),
                "scheduler_check_interval_minutes": await config_service.get("sources.scheduler_check_interval_minutes", 15),
                "scheduler_cleanup_docs_interval_hours": await config_service.get("sources.scheduler_cleanup_docs_interval_hours", 1),
                "scheduler_cleanup_logs_interval_days": await config_service.get("sources.scheduler_cleanup_logs_interval_days", 1),
                "log_retention_days": await config_service.get("sources.log_retention_days", 30),
            }

            return config
    except Exception as e:
        logger.warning(f"Failed to load config from DB, using defaults: {e}")
        return _config_cache.copy()
    finally:
        await engine.dispose()


async def get_db_session() -> AsyncSession:
    """Crée une session de base de données pour les tâches scheduler"""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        return session


async def check_and_reindex_sources():
    """
    Vérifie les sources qui nécessitent une ré-indexation automatique
    et déclenche l'indexation si nécessaire.
    """
    logger.info("Scheduler: Checking sources for auto-refresh...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si le scheduler est activé
            config_service = SystemConfigService(db)
            enabled = await config_service.get("sources.scheduler_enabled", True)
            if not enabled:
                logger.debug("Scheduler: Disabled by configuration, skipping")
                return

            # Récupérer les sources qui ont besoin d'un refresh
            sources = await IndexationHistoryService.get_sources_needing_refresh(db)

            if not sources:
                logger.debug("Scheduler: No sources need refresh")
                return

            logger.info(f"Scheduler: {len(sources)} source(s) need refresh")

            for source in sources:
                try:
                    await reindex_source(db, source)
                except Exception as e:
                    logger.error(f"Scheduler: Error refreshing source {source.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Scheduler: Error in check_and_reindex_sources: {e}")
        finally:
            await engine.dispose()


async def reindex_source(
    db: AsyncSession,
    source,
    trigger_type: str = "scheduled",
    triggered_by: Optional[str] = None,
    log_id: Optional[str] = None,
    provider: Optional[str] = None
):
    """
    Ré-indexe une source spécifique.

    Args:
        db: Session de base de données
        source: La source à ré-indexer
        trigger_type: Type de déclencheur ('scheduled', 'manual')
        triggered_by: UUID de l'utilisateur (si manuel)
        log_id: ID d'un log existant (si créé en amont pour le polling)
        provider: Provider cible (ollama ou llamacpp). Si None, utilise le provider actif.
    """
    from uuid import UUID as UUIDType
    from app.models import SourceIndexationLog
    from app.common.utils.reindex import (
        is_source_cancel_requested,
        clear_source_cancel_flag,
        ReindexManager,
    )

    source_id_str = str(source.id)

    def _is_cancelled() -> bool:
        """Vérifie si l'annulation a été demandée."""
        return is_source_cancel_requested(source_id_str)

    def _set_cancelled_progress():
        """Met à jour la progression en mémoire avec status cancelled."""
        ReindexManager.set_source_progress(
            source_id_str,
            progress=0,
            message="cancelled",
            status="cancelled",
            name=source.name,
            error_message="Annulé par l'utilisateur",
        )

    start_time = time.time()
    logger.info(f"Scheduler: Starting indexation for source '{source.name}' (trigger: {trigger_type})")

    # Utiliser le log existant ou en créer un nouveau
    if log_id:
        log_entry = await db.get(SourceIndexationLog, UUIDType(log_id))
        if not log_entry:
            logger.warning(f"Log entry {log_id} not found, creating new one")
            log_entry = await IndexationHistoryService.start_indexation(
                db=db,
                source_id=source.id,
                trigger_type=trigger_type,
                triggered_by=triggered_by
            )
    else:
        log_entry = await IndexationHistoryService.start_indexation(
            db=db,
            source_id=source.id,
            trigger_type=trigger_type,
            triggered_by=triggered_by
        )

    try:
        # Vérifier annulation avant de commencer
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}' before start")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        # Progression : démarrage
        await IndexationHistoryService.update_progress(db, log_entry, 0, "starting")

        # Récupérer le connecteur approprié pour cette source
        connector = SourceService._get_connector(source)

        # Requête de récupération du contenu
        # On utilise une requête générique car on veut indexer tout le contenu disponible
        query = source.config.get("default_query", "*")

        # Vérifier annulation
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}'")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        # Progression : récupération du contenu
        await IndexationHistoryService.update_progress(db, log_entry, 5, "fetching_content")

        # Callback de progression pour la phase crawling/fetching (5% -> 15%)
        async def _on_fetch_progress(current: int, total: int, message: str):
            """Met à jour la progression pendant le crawling (plage 5-15%)."""
            pct = 5 + int((current / max(total, 1)) * 10)  # 5% + 0-10%
            await IndexationHistoryService.update_progress(db, log_entry, pct, message)

        # Appeler le connecteur pour récupérer les résultats
        results: list[ContextResult] = await connector.search(
            query, progress_callback=_on_fetch_progress
        )

        # Vérifier annulation après le fetch
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}' after fetch")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        if not results:
            logger.info(f"Scheduler: Source '{source.name}' returned no results")
            duration_ms = int((time.time() - start_time) * 1000)
            await IndexationHistoryService.complete_indexation(
                db=db,
                log_entry=log_entry,
                documents_count=0,
                replaced_count=0,
                content_hash="empty",
                duration_ms=duration_ms
            )
            # Mettre à jour le chunk_count à 0
            source.chunk_count = 0
            await db.commit()
            return

        # Progression : calcul du hash
        await IndexationHistoryService.update_progress(db, log_entry, 15, "computing_hash")

        # Calculer le hash du contenu pour détecter les changements
        content_for_hash = "\n".join([r.content for r in results])
        content_hash = IndexationHistoryService.compute_content_hash(content_for_hash)

        # Vérifier si le contenu a changé (seulement pour les triggers automatiques)
        # Les triggers "manual" et "corpus_reindex" forcent toujours la réindexation
        force_reindex = trigger_type in ("manual", "corpus_reindex")
        if not force_reindex and source.last_content_hash == content_hash and not source.replace_on_refresh:
            logger.info(f"Scheduler: Source '{source.name}' content unchanged, skipping indexation")

            # Récupérer le nombre réel de chunks dans ChromaDB et mettre à jour chunk_count
            stats = await SourceIndexer.get_source_stats(db, source.name)
            existing_chunks = stats.get("indexed_count", 0)
            if source.chunk_count != existing_chunks:
                source.chunk_count = existing_chunks
                await db.commit()
                logger.info(f"Scheduler: Updated chunk_count for '{source.name}': {existing_chunks}")

            duration_ms = int((time.time() - start_time) * 1000)
            await IndexationHistoryService.complete_indexation(
                db=db,
                log_entry=log_entry,
                documents_count=existing_chunks,
                replaced_count=0,
                content_hash=content_hash,
                duration_ms=duration_ms
            )
            return

        # Vérifier annulation avant suppression
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}' before delete")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        # Toujours supprimer les anciens documents avant réindexation
        # (évite les erreurs de dimension si le modèle d'embedding a changé)
        await IndexationHistoryService.update_progress(db, log_entry, 20, "deleting_old_docs")
        replaced_count = await SourceIndexer.delete_source_documents(db, source.name)
        logger.info(f"Scheduler: Deleted {replaced_count} old documents for source '{source.name}'")

        # Progression : début de l'indexation
        total_results = len(results)
        await IndexationHistoryService.update_progress(
            db, log_entry, 25, f"indexing:0/{total_results}"
        )

        # Callback de progression pour l'indexation
        async def _on_index_progress(current: int, total: int):
            pct = 25 + int((current / max(total, 1)) * 70)
            await IndexationHistoryService.update_progress(
                db, log_entry, pct, f"indexing:{current}/{total}"
            )

        # Vérifier annulation avant indexation
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}' before index")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        # Indexer les nouveaux résultats dans ChromaDB
        documents_count = await SourceIndexer.index_results(
            db, results, query,
            progress_callback=_on_index_progress,
            provider=provider
        )

        # Vérifier annulation après indexation
        if _is_cancelled():
            logger.info(f"Scheduler: Indexation cancelled for source '{source.name}' after index")
            await IndexationHistoryService.cancel_indexation(db, log_entry, int((time.time() - start_time) * 1000))
            _set_cancelled_progress()
            clear_source_cancel_flag(source_id_str)
            return

        duration_ms = int((time.time() - start_time) * 1000)
        await IndexationHistoryService.complete_indexation(
            db=db,
            log_entry=log_entry,
            documents_count=documents_count,
            replaced_count=replaced_count,
            content_hash=content_hash,
            duration_ms=duration_ms
        )

        # Récupérer le provider utilisé pour l'indexation
        if provider:
            used_provider = provider
        else:
            config_service = SystemConfigService(db)
            used_provider = await config_service.get("llm.provider", "ollama")

        # Mettre à jour le chunk_count et le provider de la source
        source.chunk_count = documents_count
        source.indexed_provider = used_provider
        await db.commit()

        logger.info(
            f"Scheduler: Completed indexation for source '{source.name}': "
            f"{documents_count} chunks indexed, {replaced_count} replaced, provider={used_provider}, {duration_ms}ms"
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        await IndexationHistoryService.fail_indexation(db, log_entry, str(e), duration_ms)
        logger.error(f"Scheduler: Failed to index source '{source.name}': {e}")
    finally:
        # Toujours nettoyer le flag d'annulation
        clear_source_cancel_flag(source_id_str)


async def cleanup_expired_documents():
    """Nettoie les documents expirés dans ChromaDB."""
    logger.info("Scheduler: Cleaning up expired documents...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si le scheduler est activé
            config_service = SystemConfigService(db)
            enabled = await config_service.get("sources.scheduler_enabled", True)
            if not enabled:
                logger.debug("Scheduler: Disabled by configuration, skipping cleanup")
                return

            deleted_count = await SourceIndexer.cleanup_expired(db)
            if deleted_count > 0:
                logger.info(f"Scheduler: Cleaned up {deleted_count} expired documents")
        except Exception as e:
            logger.error(f"Scheduler: Error cleaning up expired documents: {e}")
        finally:
            await engine.dispose()


async def cleanup_old_logs():
    """Nettoie les vieux logs d'indexation."""
    logger.info("Scheduler: Cleaning up old indexation logs...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si le scheduler est activé
            config_service = SystemConfigService(db)
            enabled = await config_service.get("sources.scheduler_enabled", True)
            if not enabled:
                logger.debug("Scheduler: Disabled by configuration, skipping log cleanup")
                return

            deleted_count = await IndexationHistoryService.cleanup_old_logs(db)
            if deleted_count > 0:
                logger.info(f"Scheduler: Cleaned up {deleted_count} old logs")
        except Exception as e:
            logger.error(f"Scheduler: Error cleaning up old logs: {e}")
        finally:
            await engine.dispose()


async def cleanup_orphaned_documents():
    """Nettoie les documents ChromaDB dont la source a été supprimée en BDD."""
    logger.info("Scheduler: Cleaning up orphaned documents...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si le scheduler est activé
            config_service = SystemConfigService(db)
            enabled = await config_service.get("sources.scheduler_enabled", True)
            if not enabled:
                logger.debug("Scheduler: Disabled by configuration, skipping orphan cleanup")
                return

            # Récupérer les noms de toutes les sources existantes en BDD
            from app.features.sources.repository import SourceRepository
            all_sources = await SourceRepository.get_all(db)
            existing_names = {s.name for s in all_sources}

            deleted_count = await SourceIndexer.cleanup_orphaned_documents(db, existing_names)
            if deleted_count > 0:
                logger.info(f"Scheduler: Cleaned up {deleted_count} orphaned documents")
            else:
                logger.debug("Scheduler: No orphaned documents found")
        except Exception as e:
            logger.error(f"Scheduler: Error cleaning up orphaned documents: {e}")
        finally:
            await engine.dispose()


async def cleanup_app_logs():
    """
    Purge les logs applicatifs (table app_logs) selon la rétention par catégorie.

    Lit la configuration depuis system_configs :
    - logging.retention_technical_days (défaut: 30)
    - logging.retention_access_days (défaut: 30)
    - logging.retention_audit_days (défaut: 365)
    - logging.retention_security_days (défaut: 365)
    - logging.retention_infra_days (défaut: 14)
    """
    logger.info("Scheduler: Cleaning up expired app logs...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si la persistance BDD est activée
            config_service = SystemConfigService(db)
            db_enabled = await config_service.get("logging.db_enabled", True)
            if not db_enabled:
                logger.debug("Scheduler: Log DB persistence disabled, skipping app logs cleanup")
                return

            # Lire la rétention par catégorie
            retention_map = {
                "technical": int(await config_service.get("logging.retention_technical_days", 30)),
                "access": int(await config_service.get("logging.retention_access_days", 30)),
                "audit": int(await config_service.get("logging.retention_audit_days", 365)),
                "security": int(await config_service.get("logging.retention_security_days", 365)),
                "infra": int(await config_service.get("logging.retention_infra_days", 14)),
            }

            # Purger chaque catégorie
            from app.features.logs.repository import LogRepository
            repo = LogRepository(db)
            total_deleted = 0

            for category, days in retention_map.items():
                deleted = await repo.cleanup(category=category, older_than_days=days)
                if deleted > 0:
                    logger.info(f"Scheduler: Purged {deleted} {category} logs older than {days} days")
                    total_deleted += deleted

            if total_deleted > 0:
                logger.info(f"Scheduler: Total app logs purged: {total_deleted}")
            else:
                logger.debug("Scheduler: No expired app logs to purge")
        except Exception as e:
            logger.error(f"Scheduler: Error cleaning up app logs: {e}")
        finally:
            await engine.dispose()


async def check_log_alerts():
    """
    Exécute les vérifications d'alerting sur les logs applicatifs.

    Détecte les patterns critiques (explosion d'erreurs, échecs login répétés)
    et marque les logs correspondants avec is_alert=True.
    """
    logger.debug("Scheduler: Running alert checks...")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_maker() as db:
        try:
            # Vérifier si la persistance BDD des logs est activée
            config_service = SystemConfigService(db)
            db_enabled = await config_service.get("logging.db_enabled", True)
            if not db_enabled:
                return

            from app.common.utils.alert_checker import run_all_checks
            results = await run_all_checks(db)

            total = sum(results.values())
            if total > 0:
                logger.info(f"Scheduler: Alert check completed — {total} new alerts flagged")
        except Exception as e:
            logger.error(f"Scheduler: Error running alert checks: {e}")
        finally:
            await engine.dispose()


def init_scheduler(
    check_interval_minutes: int = 15,
    cleanup_docs_hours: int = 1,
    cleanup_logs_days: int = 1
) -> AsyncIOScheduler:
    """
    Initialise et configure le scheduler.

    Args:
        check_interval_minutes: Intervalle de vérification des sources (minutes)
        cleanup_docs_hours: Intervalle de nettoyage des documents expirés (heures)
        cleanup_logs_days: Intervalle de nettoyage des logs (jours)

    Returns:
        L'instance du scheduler configuré
    """
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")

    # Vérification des sources à ré-indexer
    _scheduler.add_job(
        check_and_reindex_sources,
        trigger=IntervalTrigger(minutes=check_interval_minutes),
        id="check_reindex_sources",
        name="Check and reindex sources",
        replace_existing=True,
        misfire_grace_time=120
    )

    # Nettoyage des documents expirés
    _scheduler.add_job(
        cleanup_expired_documents,
        trigger=IntervalTrigger(hours=cleanup_docs_hours),
        id="cleanup_expired_docs",
        name="Cleanup expired documents",
        replace_existing=True,
        misfire_grace_time=300
    )

    # Nettoyage des vieux logs
    _scheduler.add_job(
        cleanup_old_logs,
        trigger=IntervalTrigger(days=cleanup_logs_days),
        id="cleanup_old_logs",
        name="Cleanup old indexation logs",
        replace_existing=True,
        misfire_grace_time=3600
    )

    # Nettoyage des documents orphelins (sources supprimées en BDD)
    _scheduler.add_job(
        cleanup_orphaned_documents,
        trigger=IntervalTrigger(hours=6),
        id="cleanup_orphaned_docs",
        name="Cleanup orphaned source documents",
        replace_existing=True,
        misfire_grace_time=600
    )

    # Purge des logs applicatifs (table app_logs) — quotidien
    _scheduler.add_job(
        cleanup_app_logs,
        trigger=IntervalTrigger(hours=24),
        id="cleanup_app_logs",
        name="Cleanup expired app logs",
        replace_existing=True,
        misfire_grace_time=3600
    )

    # Vérification des alertes (patterns critiques) — toutes les 5 minutes
    _scheduler.add_job(
        check_log_alerts,
        trigger=IntervalTrigger(minutes=5),
        id="check_log_alerts",
        name="Check log alert patterns",
        replace_existing=True,
        misfire_grace_time=60
    )

    logger.info(
        f"Source indexation scheduler initialized with intervals: "
        f"check={check_interval_minutes}min, cleanup_docs={cleanup_docs_hours}h, "
        f"cleanup_logs={cleanup_logs_days}d, cleanup_orphans=6h, cleanup_app_logs=24h"
    )
    return _scheduler


async def init_scheduler_from_db() -> AsyncIOScheduler:
    """
    Initialise le scheduler avec les configurations depuis la BDD.

    Returns:
        L'instance du scheduler configuré
    """
    global _config_cache

    # Charger les configs depuis la BDD
    config = await load_config_from_db()
    _config_cache = config

    return init_scheduler(
        check_interval_minutes=int(config.get("scheduler_check_interval_minutes", 15)),
        cleanup_docs_hours=int(config.get("scheduler_cleanup_docs_interval_hours", 1)),
        cleanup_logs_days=int(config.get("scheduler_cleanup_logs_interval_days", 1))
    )


def start_scheduler():
    """Démarre le scheduler avec les configs par défaut."""
    global _scheduler

    if _scheduler is None:
        _scheduler = init_scheduler()

    if not _scheduler.running:
        _scheduler.start()
        logger.info("Source indexation scheduler started")


async def start_scheduler_async():
    """Démarre le scheduler avec les configs depuis la BDD (async)."""
    global _scheduler

    if _scheduler is None:
        _scheduler = await init_scheduler_from_db()

    if not _scheduler.running:
        _scheduler.start()
        logger.info("Source indexation scheduler started (with DB config)")


def stop_scheduler():
    """Arrête le scheduler."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Source indexation scheduler stopped")


async def reload_scheduler():
    """
    Recharge le scheduler avec les nouvelles configurations depuis la BDD.
    """
    global _scheduler, _config_cache

    # Charger les nouvelles configs
    config = await load_config_from_db()

    # Vérifier si les configs ont changé
    if config == _config_cache:
        logger.debug("Scheduler: Config unchanged, no reload needed")
        return

    _config_cache = config

    # Arrêter le scheduler actuel
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None

    # Recréer avec les nouvelles configs si activé
    if config.get("scheduler_enabled", True):
        _scheduler = init_scheduler(
            check_interval_minutes=int(config.get("scheduler_check_interval_minutes", 15)),
            cleanup_docs_hours=int(config.get("scheduler_cleanup_docs_interval_hours", 1)),
            cleanup_logs_days=int(config.get("scheduler_cleanup_logs_interval_days", 1))
        )
        _scheduler.start()
        logger.info("Scheduler reloaded with new configuration")
    else:
        logger.info("Scheduler disabled by configuration")


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Retourne l'instance du scheduler."""
    return _scheduler


def get_scheduler_status() -> dict:
    """
    Retourne le statut du scheduler.

    Returns:
        Dictionnaire avec le statut du scheduler
    """
    if _scheduler is None:
        return {"running": False, "jobs": [], "config": _config_cache}

    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })

    return {
        "running": _scheduler.running,
        "jobs": jobs,
        "config": _config_cache
    }
