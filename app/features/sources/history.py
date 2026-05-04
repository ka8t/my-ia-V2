"""
Service d'historique des indexations de sources externes

Gère le logging, la détection de changements et la rétention des logs.
"""
import hashlib
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import SourceIndexationLog, ContextSource, User
from app.features.system.service import SystemConfigService

logger = logging.getLogger(__name__)


class IndexationHistoryService:
    """Service de gestion de l'historique des indexations"""

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """
        Calcule le hash SHA256 d'un contenu.

        Args:
            content: Contenu à hasher

        Returns:
            Hash SHA256 en hexadécimal
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @staticmethod
    async def start_indexation(
        db: AsyncSession,
        source_id: UUID,
        trigger_type: str,
        triggered_by: Optional[UUID] = None
    ) -> SourceIndexationLog:
        """
        Démarre une nouvelle indexation et crée l'entrée de log.

        Args:
            db: Session de base de données
            source_id: ID de la source
            trigger_type: Type de déclencheur ('manual', 'scheduled', 'on_create')
            triggered_by: ID de l'utilisateur (si manuel)

        Returns:
            L'entrée de log créée
        """
        log_entry = SourceIndexationLog(
            source_id=source_id,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            status="running",
            indexed_at=datetime.now(timezone.utc)
        )
        db.add(log_entry)
        await db.flush()

        logger.info(f"Started indexation for source {source_id}, trigger: {trigger_type}")
        return log_entry

    @staticmethod
    async def update_progress(
        db: AsyncSession,
        log_entry: SourceIndexationLog,
        progress: int,
        message: str
    ) -> None:
        """
        Met à jour la progression d'une indexation en cours.

        Args:
            db: Session de base de données
            log_entry: Entrée de log à mettre à jour
            progress: Pourcentage de progression (0-100)
            message: Message décrivant l'étape en cours
        """
        log_entry.progress = min(progress, 100)
        log_entry.progress_message = message
        await db.commit()

    @staticmethod
    async def cleanup_stale_indexations(db: AsyncSession) -> int:
        """
        Marque les indexations bloquées (status='running' trop longtemps) comme 'failed'.

        Lit le timeout depuis la config `indexation.stale_timeout_minutes` (défaut: 60).

        Args:
            db: Session de base de données

        Returns:
            Nombre d'indexations marquées comme failed
        """
        config_service = SystemConfigService(db)
        timeout_minutes_raw = await config_service.get("indexation.stale_timeout_minutes", 60)
        timeout_minutes = int(timeout_minutes_raw) if timeout_minutes_raw else 60

        if timeout_minutes <= 0:
            return 0

        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        # Récupérer les indexations bloquées
        result = await db.execute(
            select(SourceIndexationLog)
            .where(
                SourceIndexationLog.status == "running",
                SourceIndexationLog.indexed_at < cutoff_time
            )
        )
        stale_logs = list(result.scalars().all())

        if not stale_logs:
            return 0

        # Marquer chaque log comme failed
        for log_entry in stale_logs:
            log_entry.status = "failed"
            log_entry.error_message = f"Timeout: processus bloqué depuis plus de {timeout_minutes} minutes"
            log_entry.progress_message = None
            logger.warning(
                f"Marked stale indexation as failed: source {log_entry.source_id}, "
                f"started at {log_entry.indexed_at}"
            )

        await db.commit()
        logger.info(f"Cleaned up {len(stale_logs)} stale indexations (timeout: {timeout_minutes} min)")

        return len(stale_logs)

    @staticmethod
    async def get_running_indexation(
        db: AsyncSession,
        source_id: UUID
    ) -> Optional[SourceIndexationLog]:
        """
        Récupère l'indexation en cours pour une source.

        Nettoie automatiquement les indexations bloquées avant la recherche.

        Args:
            db: Session de base de données
            source_id: ID de la source

        Returns:
            L'entrée de log en cours ou None
        """
        # Nettoyer les indexations bloquées avant de chercher
        await IndexationHistoryService.cleanup_stale_indexations(db)

        result = await db.execute(
            select(SourceIndexationLog)
            .where(
                SourceIndexationLog.source_id == source_id,
                SourceIndexationLog.status == "running"
            )
            .order_by(SourceIndexationLog.indexed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_latest_indexation(
        db: AsyncSession,
        source_id: UUID
    ) -> Optional[SourceIndexationLog]:
        """
        Récupère la dernière indexation (tous statuts) pour une source.

        Args:
            db: Session de base de données
            source_id: ID de la source

        Returns:
            L'entrée de log la plus récente ou None
        """
        result = await db.execute(
            select(SourceIndexationLog)
            .where(SourceIndexationLog.source_id == source_id)
            .order_by(SourceIndexationLog.indexed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def complete_indexation(
        db: AsyncSession,
        log_entry: SourceIndexationLog,
        documents_count: int,
        replaced_count: int,
        content_hash: str,
        duration_ms: int,
        error_message: Optional[str] = None
    ) -> SourceIndexationLog:
        """
        Termine une indexation et met à jour le log.

        Args:
            db: Session de base de données
            log_entry: Entrée de log à mettre à jour
            documents_count: Nombre de documents indexés
            replaced_count: Nombre de documents remplacés
            content_hash: Hash du contenu indexé
            duration_ms: Durée en millisecondes
            error_message: Message d'erreur si échec

        Returns:
            L'entrée de log mise à jour
        """
        # Récupérer le hash précédent de la source
        source = await db.get(ContextSource, log_entry.source_id)
        previous_hash = source.last_content_hash if source else None

        # Déterminer si le contenu a changé
        content_changed = previous_hash is None or previous_hash != content_hash

        # Mettre à jour le log
        log_entry.documents_count = documents_count
        log_entry.replaced_count = replaced_count
        log_entry.content_hash = content_hash
        log_entry.content_changed = content_changed
        log_entry.duration_ms = duration_ms
        log_entry.status = "failed" if error_message else "success"
        log_entry.error_message = error_message
        log_entry.progress = 100
        log_entry.progress_message = None

        # Mettre à jour la source si succès
        if not error_message and source:
            source.last_indexed_at = log_entry.indexed_at
            source.last_content_hash = content_hash

        await db.commit()

        status = "failed" if error_message else "success"
        logger.info(
            f"Completed indexation for source {log_entry.source_id}: "
            f"{status}, {documents_count} chunks, changed: {content_changed}"
        )

        return log_entry

    @staticmethod
    async def fail_indexation(
        db: AsyncSession,
        log_entry: SourceIndexationLog,
        error_message: str,
        duration_ms: int
    ) -> SourceIndexationLog:
        """
        Marque une indexation comme échouée.

        Args:
            db: Session de base de données
            log_entry: Entrée de log
            error_message: Message d'erreur
            duration_ms: Durée en millisecondes

        Returns:
            L'entrée de log mise à jour
        """
        log_entry.status = "failed"
        log_entry.error_message = error_message
        log_entry.duration_ms = duration_ms
        log_entry.progress_message = None

        await db.commit()

        logger.error(f"Indexation failed for source {log_entry.source_id}: {error_message}")
        return log_entry

    @staticmethod
    async def cancel_indexation(
        db: AsyncSession,
        log_entry: SourceIndexationLog,
        duration_ms: int
    ) -> SourceIndexationLog:
        """
        Marque une indexation comme annulée.

        Args:
            db: Session de base de données
            log_entry: Entrée de log
            duration_ms: Durée en millisecondes

        Returns:
            L'entrée de log mise à jour
        """
        log_entry.status = "cancelled"
        log_entry.error_message = "Annulé par l'utilisateur"
        log_entry.duration_ms = duration_ms
        log_entry.progress_message = None

        await db.commit()

        logger.info(f"Indexation cancelled for source {log_entry.source_id}")
        return log_entry

    @staticmethod
    async def get_source_history(
        db: AsyncSession,
        source_id: UUID,
        limit: int = 20,
        offset: int = 0
    ) -> List[SourceIndexationLog]:
        """
        Récupère l'historique des indexations d'une source.

        Args:
            db: Session de base de données
            source_id: ID de la source
            limit: Nombre max de résultats
            offset: Décalage

        Returns:
            Liste des entrées de log
        """
        result = await db.execute(
            select(SourceIndexationLog)
            .options(selectinload(SourceIndexationLog.triggered_by_user))
            .where(SourceIndexationLog.source_id == source_id)
            .order_by(SourceIndexationLog.indexed_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_source_history_count(db: AsyncSession, source_id: UUID) -> int:
        """
        Compte le nombre d'entrées d'historique pour une source.

        Args:
            db: Session de base de données
            source_id: ID de la source

        Returns:
            Nombre d'entrées
        """
        result = await db.execute(
            select(func.count(SourceIndexationLog.id))
            .where(SourceIndexationLog.source_id == source_id)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_last_successful_indexation(
        db: AsyncSession,
        source_id: UUID
    ) -> Optional[SourceIndexationLog]:
        """
        Récupère la dernière indexation réussie d'une source.

        Args:
            db: Session de base de données
            source_id: ID de la source

        Returns:
            L'entrée de log ou None
        """
        result = await db.execute(
            select(SourceIndexationLog)
            .where(
                SourceIndexationLog.source_id == source_id,
                SourceIndexationLog.status == "success"
            )
            .order_by(SourceIndexationLog.indexed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def cleanup_old_logs(db: AsyncSession) -> int:
        """
        Supprime les logs d'indexation plus anciens que la rétention configurée.

        Args:
            db: Session de base de données

        Returns:
            Nombre de logs supprimés
        """
        config_service = SystemConfigService(db)
        retention_days = await config_service.get("sources.log_retention_days", 90)

        if retention_days == 0:
            logger.debug("Log retention disabled (0 days)")
            return 0

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

        result = await db.execute(
            delete(SourceIndexationLog)
            .where(SourceIndexationLog.indexed_at < cutoff_date)
            .returning(SourceIndexationLog.id)
        )
        deleted_ids = result.fetchall()
        deleted_count = len(deleted_ids)

        if deleted_count > 0:
            await db.commit()
            logger.info(f"Cleaned up {deleted_count} old indexation logs (older than {retention_days} days)")

        return deleted_count

    @staticmethod
    async def get_sources_needing_refresh(db: AsyncSession) -> List[ContextSource]:
        """
        Récupère les sources qui nécessitent une ré-indexation automatique.

        Une source nécessite un refresh si:
        - auto_refresh est activé
        - index_enabled est activé
        - is_enabled est activé
        - last_indexed_at + refresh_interval_hours < now

        Args:
            db: Session de base de données

        Returns:
            Liste des sources à rafraîchir
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            select(ContextSource)
            .where(
                ContextSource.is_enabled == True,
                ContextSource.index_enabled == True,
                ContextSource.auto_refresh == True,
                ContextSource.refresh_interval_hours.isnot(None)
            )
        )
        sources = list(result.scalars().all())

        # Filtrer celles qui ont besoin d'un refresh
        sources_to_refresh = []
        for source in sources:
            if source.last_indexed_at is None:
                # Jamais indexée → besoin de refresh
                sources_to_refresh.append(source)
            else:
                # Vérifier si l'intervalle est dépassé
                next_refresh = source.last_indexed_at + timedelta(hours=source.refresh_interval_hours)
                if now >= next_refresh:
                    sources_to_refresh.append(source)

        return sources_to_refresh

    @staticmethod
    async def get_stale_sources(db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Récupère les sources dont l'index est périmé ou bientôt périmé.

        Args:
            db: Session de base de données

        Returns:
            Liste des sources avec leur état de fraîcheur
        """
        config_service = SystemConfigService(db)
        warning_threshold = await config_service.get("sources.freshness_warning_percent", 30)
        expired_threshold = await config_service.get("sources.freshness_expired_percent", 0)

        result = await db.execute(
            select(ContextSource)
            .where(
                ContextSource.is_enabled == True,
                ContextSource.index_enabled == True,
                ContextSource.index_ttl_hours.isnot(None)
            )
        )
        sources = list(result.scalars().all())

        now = datetime.now(timezone.utc)
        stale_sources = []

        for source in sources:
            if source.last_indexed_at is None:
                # Jamais indexée
                stale_sources.append({
                    "source_id": source.id,
                    "source_name": source.name,
                    "display_name": source.display_name,
                    "status": "never_indexed",
                    "ttl_hours": source.index_ttl_hours,
                    "last_indexed_at": None,
                    "expires_at": None,
                    "freshness_percent": 0
                })
            else:
                ttl_delta = timedelta(hours=source.index_ttl_hours)
                expires_at = source.last_indexed_at + ttl_delta
                time_since_index = now - source.last_indexed_at
                freshness_percent = max(0, 100 - (time_since_index / ttl_delta * 100))

                # Déterminer le statut selon les seuils configurés
                if freshness_percent <= expired_threshold:
                    status = "expired"
                elif freshness_percent <= warning_threshold:
                    status = "warning"
                else:
                    status = "fresh"

                if status in ("expired", "warning"):
                    stale_sources.append({
                        "source_id": source.id,
                        "source_name": source.name,
                        "display_name": source.display_name,
                        "status": status,
                        "ttl_hours": source.index_ttl_hours,
                        "last_indexed_at": source.last_indexed_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "freshness_percent": round(freshness_percent, 1)
                    })

        return stale_sources

    @staticmethod
    async def get_freshness_status(
        db: AsyncSession,
        source: ContextSource
    ) -> Dict[str, Any]:
        """
        Calcule le statut de fraîcheur d'une source.

        Args:
            db: Session de base de données
            source: La source à évaluer

        Returns:
            Dictionnaire avec le statut de fraîcheur
        """
        config_service = SystemConfigService(db)
        warning_threshold = await config_service.get("sources.freshness_warning_percent", 30)
        expired_threshold = await config_service.get("sources.freshness_expired_percent", 0)

        # Utiliser le TTL de la source (défaut: 24h)
        ttl_hours = source.index_ttl_hours or 24

        if not source.index_enabled:
            return {
                "status": "disabled",
                "freshness_percent": None,
                "ttl_hours": ttl_hours,
                "last_indexed_at": source.last_indexed_at.isoformat() if source.last_indexed_at else None,
                "expires_at": None
            }

        if source.last_indexed_at is None:
            return {
                "status": "never_indexed",
                "freshness_percent": 0,
                "ttl_hours": ttl_hours,
                "last_indexed_at": None,
                "expires_at": None
            }

        now = datetime.now(timezone.utc)
        ttl_delta = timedelta(hours=ttl_hours)
        expires_at = source.last_indexed_at + ttl_delta
        time_since_index = now - source.last_indexed_at

        # Calculer le pourcentage de fraîcheur (100% = vient d'être indexé, 0% = expiré)
        freshness_percent = max(0, min(100, 100 - (time_since_index / ttl_delta * 100)))

        # Déterminer le statut selon les seuils configurés
        if freshness_percent <= expired_threshold:
            status = "expired"
        elif freshness_percent <= warning_threshold:
            status = "warning"
        else:
            status = "fresh"

        return {
            "status": status,
            "freshness_percent": round(freshness_percent, 1),
            "ttl_hours": ttl_hours,
            "last_indexed_at": source.last_indexed_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "hours_until_expiry": max(0, (expires_at - now).total_seconds() / 3600)
        }
