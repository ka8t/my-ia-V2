"""
Repository pour les logs applicatifs

Opérations base de données sur la table app_logs.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, delete, or_, outerjoin
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppLog, User


class LogRepository:
    """Repository pour la table app_logs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_logs(
        self,
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
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Récupère les logs avec filtres et pagination.

        Effectue un LEFT JOIN sur User pour inclure le username.

        Returns:
            Tuple (logs_with_username, total_count)
        """
        query = select(AppLog, User.username).outerjoin(
            User, AppLog.user_id == User.id
        )

        # Appliquer les filtres
        if log_category:
            query = query.where(AppLog.log_category == log_category)
        if level:
            query = query.where(AppLog.level == level)
        if user_id:
            query = query.where(AppLog.user_id == user_id)
        if request_id:
            query = query.where(AppLog.request_id == request_id)
        if date_from:
            query = query.where(AppLog.timestamp >= date_from)
        if date_to:
            query = query.where(AppLog.timestamp <= date_to)
        if is_alert is not None:
            query = query.where(AppLog.is_alert == is_alert)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    AppLog.message.ilike(pattern),
                    AppLog.logger_name.ilike(pattern),
                )
            )

        # Compter le total (sur AppLog uniquement)
        count_base = select(AppLog.id)
        # Réappliquer les mêmes filtres pour le count
        if log_category:
            count_base = count_base.where(AppLog.log_category == log_category)
        if level:
            count_base = count_base.where(AppLog.level == level)
        if user_id:
            count_base = count_base.where(AppLog.user_id == user_id)
        if request_id:
            count_base = count_base.where(AppLog.request_id == request_id)
        if date_from:
            count_base = count_base.where(AppLog.timestamp >= date_from)
        if date_to:
            count_base = count_base.where(AppLog.timestamp <= date_to)
        if is_alert is not None:
            count_base = count_base.where(AppLog.is_alert == is_alert)
        if search:
            pattern = f"%{search}%"
            count_base = count_base.where(
                or_(
                    AppLog.message.ilike(pattern),
                    AppLog.logger_name.ilike(pattern),
                )
            )
        count_query = select(func.count()).select_from(count_base.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Pagination et tri
        offset = (page - 1) * page_size
        query = query.order_by(AppLog.timestamp.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        rows = result.all()

        # Attacher username à chaque log
        logs = []
        for row in rows:
            log = row[0]
            log.username = row[1]  # Attribut dynamique
            logs.append(log)

        return logs, total

    async def get_stats(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Récupère les statistiques des logs."""
        base_filter = []
        if date_from:
            base_filter.append(AppLog.timestamp >= date_from)
        if date_to:
            base_filter.append(AppLog.timestamp <= date_to)

        # Total
        total_query = select(func.count(AppLog.id)).where(*base_filter) if base_filter else select(func.count(AppLog.id))
        total_result = await self.db.execute(total_query)
        total = total_result.scalar() or 0

        # Par catégorie
        cat_query = (
            select(AppLog.log_category, func.count(AppLog.id))
            .where(*base_filter)
            .group_by(AppLog.log_category)
        ) if base_filter else (
            select(AppLog.log_category, func.count(AppLog.id))
            .group_by(AppLog.log_category)
        )
        cat_result = await self.db.execute(cat_query)
        by_category = [{"category": row[0], "count": row[1]} for row in cat_result.all()]

        # Par niveau
        lvl_query = (
            select(AppLog.level, func.count(AppLog.id))
            .where(*base_filter)
            .group_by(AppLog.level)
        ) if base_filter else (
            select(AppLog.level, func.count(AppLog.id))
            .group_by(AppLog.level)
        )
        lvl_result = await self.db.execute(lvl_query)
        by_level = [{"level": row[0], "count": row[1]} for row in lvl_result.all()]

        # Alertes
        alert_query = (
            select(func.count(AppLog.id))
            .where(AppLog.is_alert == True, *base_filter)
        ) if base_filter else (
            select(func.count(AppLog.id))
            .where(AppLog.is_alert == True)
        )
        alert_result = await self.db.execute(alert_query)
        alerts_count = alert_result.scalar() or 0

        return {
            "total": total,
            "by_category": by_category,
            "by_level": by_level,
            "alerts_count": alerts_count,
        }

    async def get_recent_alerts(
        self,
        page: int = 1,
        page_size: int = 50,
        log_category: Optional[str] = None,
    ) -> Tuple[List[Any], int]:
        """
        Récupère les alertes récentes (is_alert=True).

        Returns:
            Tuple (alerts_with_username, total_count)
        """
        query = select(AppLog, User.username).outerjoin(
            User, AppLog.user_id == User.id
        ).where(AppLog.is_alert == True)

        if log_category:
            query = query.where(AppLog.log_category == log_category)

        # Compter le total
        count_base = select(AppLog.id).where(AppLog.is_alert == True)
        if log_category:
            count_base = count_base.where(AppLog.log_category == log_category)
        count_query = select(func.count()).select_from(count_base.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Pagination et tri
        offset = (page - 1) * page_size
        query = query.order_by(AppLog.timestamp.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        rows = result.all()

        alerts = []
        for row in rows:
            log = row[0]
            log.username = row[1]
            alerts.append(log)

        return alerts, total

    async def delete_by_ids(self, log_ids: List[UUID]) -> int:
        """
        Supprime des logs par leurs IDs.

        Args:
            log_ids: Liste des UUIDs des logs à supprimer

        Returns:
            Nombre de logs effectivement supprimés
        """
        stmt = delete(AppLog).where(AppLog.id.in_(log_ids))
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount or 0

    async def cleanup(
        self,
        category: Optional[str] = None,
        older_than_days: int = 30,
    ) -> int:
        """
        Supprime les logs selon les critères de rétention.

        Returns:
            Nombre de logs supprimés
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

        stmt = delete(AppLog).where(AppLog.timestamp < cutoff)
        if category:
            stmt = stmt.where(AppLog.log_category == category)

        result = await self.db.execute(stmt)
        await self.db.commit()

        return result.rowcount or 0
