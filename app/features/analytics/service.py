"""
Service Analytics

Logique metier pour le dashboard analytics.
"""
import logging
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.analytics.repository import AnalyticsRepository
from app.features.analytics.schemas import (
    GlobalStats,
    DashboardOverview,
    AnalyticsResponse,
    UsageOverTime,
    TimeSeriesPoint,
    TopUser,
    TopQuery
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service pour les analytics du dashboard."""

    @staticmethod
    async def get_dashboard_overview(db: AsyncSession) -> DashboardOverview:
        """
        Recupere la vue d'ensemble du dashboard.

        Inclut les stats globales, usage du jour et tendances.
        """
        stats_data = await AnalyticsRepository.get_global_stats(db)
        usage_today = await AnalyticsRepository.get_usage_today(db)
        trends = await AnalyticsRepository.get_trends(db, days=7)

        return DashboardOverview(
            stats=GlobalStats(**stats_data),
            usage_today=usage_today,
            trends=trends
        )

    @staticmethod
    async def get_full_analytics(
        db: AsyncSession,
        days: int = 30
    ) -> AnalyticsResponse:
        """
        Recupere les analytics completes.

        Args:
            db: Session DB
            days: Nombre de jours d'historique
        """
        # Overview
        overview = await AnalyticsService.get_dashboard_overview(db)

        # Usage over time
        usage_data = await AnalyticsRepository.get_usage_over_time(db, days=days)
        usage_over_time = UsageOverTime(
            messages=[TimeSeriesPoint(**p) for p in usage_data["messages"]],
            conversations=[TimeSeriesPoint(**p) for p in usage_data["conversations"]],
            new_users=[TimeSeriesPoint(**p) for p in usage_data["new_users"]],
            active_users=[TimeSeriesPoint(**p) for p in usage_data["active_users"]]
        )

        # Top users
        top_users_data = await AnalyticsRepository.get_top_users(db, limit=10, days=days)
        top_users = [TopUser(**u) for u in top_users_data]

        # Top queries
        top_queries_data = await AnalyticsRepository.get_top_queries(db, limit=10, days=days)
        top_queries = [TopQuery(**q) for q in top_queries_data]

        return AnalyticsResponse(
            overview=overview,
            usage_over_time=usage_over_time,
            top_users=top_users,
            top_queries=top_queries
        )

    @staticmethod
    async def get_usage_chart_data(
        db: AsyncSession,
        metric: str,
        days: int = 30
    ) -> List[TimeSeriesPoint]:
        """
        Recupere les donnees d'un graphique specifique.

        Args:
            metric: messages, conversations, new_users, active_users
            days: Nombre de jours
        """
        usage_data = await AnalyticsRepository.get_usage_over_time(
            db, days=days
        )

        if metric not in usage_data:
            return []

        return [TimeSeriesPoint(**p) for p in usage_data[metric]]
