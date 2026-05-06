"""
Service pour les logs applicatifs

Logique métier pour la consultation, les statistiques, la purge et l'export des logs.
"""
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.logs.repository import LogRepository
from app.features.logs.schemas import (
    LogListResponse,
    LogStatsResponse,
    LogCategoryStats,
    LogLevelStats,
    LogCleanupResponse,
    AlertListResponse,
    AppLogRead,
    BulkLogDeleteResponse,
)


class LogService:
    """Service pour la gestion des logs applicatifs."""

    @staticmethod
    async def get_logs(
        db: AsyncSession,
        page: int = 1,
        page_size: int = 50,
        log_category: Optional[str] = None,
        level: Optional[str] = None,
        search: Optional[str] = None,
        user_id: Optional[UUID] = None,
        request_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        is_alert: Optional[bool] = None,
    ) -> LogListResponse:
        """Récupère les logs avec filtres et pagination."""
        repo = LogRepository(db)
        logs, total = await repo.get_logs(
            page=page,
            page_size=page_size,
            log_category=log_category,
            level=level,
            search=search,
            user_id=user_id,
            request_id=request_id,
            date_from=date_from,
            date_to=date_to,
            is_alert=is_alert,
        )

        total_pages = math.ceil(total / page_size) if page_size > 0 else 0

        items = []
        for log in logs:
            item = AppLogRead.model_validate(log)
            item.username = getattr(log, 'username', None)
            items.append(item)

        return LogListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> LogStatsResponse:
        """Récupère les statistiques des logs."""
        repo = LogRepository(db)
        stats = await repo.get_stats(date_from=date_from, date_to=date_to)

        return LogStatsResponse(
            total=stats["total"],
            by_category=[LogCategoryStats(**c) for c in stats["by_category"]],
            by_level=[LogLevelStats(**l) for l in stats["by_level"]],
            alerts_count=stats["alerts_count"],
        )

    @staticmethod
    async def cleanup(
        db: AsyncSession,
        category: Optional[str] = None,
        older_than_days: int = 30,
    ) -> LogCleanupResponse:
        """Purge les logs selon les critères de rétention."""
        repo = LogRepository(db)
        deleted = await repo.cleanup(
            category=category,
            older_than_days=older_than_days,
        )

        return LogCleanupResponse(
            deleted_count=deleted,
            category=category,
            older_than_days=older_than_days,
        )

    @staticmethod
    async def get_alerts(
        db: AsyncSession,
        page: int = 1,
        page_size: int = 50,
        log_category: Optional[str] = None,
    ) -> AlertListResponse:
        """Récupère les alertes récentes."""
        repo = LogRepository(db)
        alerts, total = await repo.get_recent_alerts(
            page=page,
            page_size=page_size,
            log_category=log_category,
        )

        total_pages = math.ceil(total / page_size) if page_size > 0 else 0

        items = []
        for a in alerts:
            item = AppLogRead.model_validate(a)
            item.username = getattr(a, 'username', None)
            items.append(item)

        return AlertListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @staticmethod
    async def bulk_delete(
        db: AsyncSession,
        log_ids: List[UUID],
    ) -> BulkLogDeleteResponse:
        """
        Supprime des logs en masse par leurs IDs.

        Args:
            db: Session de base de données
            log_ids: Liste des UUIDs des logs à supprimer

        Returns:
            BulkLogDeleteResponse avec le nombre de succès/échecs
        """
        repo = LogRepository(db)
        deleted = await repo.delete_by_ids(log_ids)

        return BulkLogDeleteResponse(
            success_count=deleted,
            failed_count=len(log_ids) - deleted,
        )

    @staticmethod
    async def export_logs(
        db: AsyncSession,
        log_category: Optional[str] = None,
        level: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """
        Exporte les logs avec filtres (sans pagination).

        Args:
            db: Session de base de données
            log_category: Filtrer par catégorie
            level: Filtrer par niveau
            search: Recherche texte
            date_from: Date de début
            date_to: Date de fin
            limit: Nombre max d'enregistrements

        Returns:
            Liste de dictionnaires représentant les logs
        """
        repo = LogRepository(db)
        logs, _ = await repo.get_logs(
            page=1,
            page_size=limit,
            log_category=log_category,
            level=level,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )

        return [
            {
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                "level": log.level,
                "log_category": log.log_category,
                "service": log.service or "",
                "environment": log.environment or "",
                "request_id": log.request_id or "",
                "user_id": str(log.user_id) if log.user_id else "",
                "username": getattr(log, 'username', None) or "",
                "session_id": log.session_id or "",
                "message": log.message,
                "context": json.dumps(log.context, ensure_ascii=False) if log.context else "",
                "ip_address": log.ip_address or "",
                "user_agent": log.user_agent or "",
                "logger_name": log.logger_name or "",
                "is_alert": log.is_alert,
            }
            for log in logs
        ]
