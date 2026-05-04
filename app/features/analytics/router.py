"""
Router Analytics

Endpoints admin pour le dashboard analytics.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user
from app.features.analytics.service import AnalyticsService
from app.features.analytics.schemas import (
    DashboardOverview,
    AnalyticsResponse,
    TopUser,
    TopQuery,
    TimeSeriesPoint
)
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Admin - Analytics"])


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Recupere la vue d'ensemble du dashboard.

    Inclut :
    - Statistiques globales (users, messages, documents)
    - Usage du jour
    - Tendances vs semaine precedente
    """
    return await AnalyticsService.get_dashboard_overview(db)


@router.get("", response_model=AnalyticsResponse)
async def get_full_analytics(
    days: int = Query(30, ge=1, le=365, description="Nombre de jours d'historique"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Recupere les analytics completes.

    Inclut :
    - Vue d'ensemble
    - Usage au fil du temps (graphiques)
    - Top utilisateurs
    - Questions frequentes
    """
    return await AnalyticsService.get_full_analytics(
        db, days=days
    )


@router.get("/top-users", response_model=List[TopUser])
async def get_top_users(
    limit: int = Query(10, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Recupere les utilisateurs les plus actifs.

    Base sur le nombre de messages et conversations.
    """
    from app.features.analytics.repository import AnalyticsRepository
    users_data = await AnalyticsRepository.get_top_users(
        db, limit=limit, days=days
    )
    return [TopUser(**u) for u in users_data]


@router.get("/top-queries", response_model=List[TopQuery])
async def get_top_queries(
    limit: int = Query(10, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Recupere les questions les plus frequentes.

    Base sur les messages utilisateur.
    """
    from app.features.analytics.repository import AnalyticsRepository
    queries_data = await AnalyticsRepository.get_top_queries(
        db, limit=limit, days=days
    )
    return [TopQuery(**q) for q in queries_data]


@router.get("/chart/{metric}", response_model=List[TimeSeriesPoint])
async def get_chart_data(
    metric: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """
    Recupere les donnees d'un graphique specifique.

    Metrics disponibles:
    - messages
    - conversations
    - new_users
    - active_users
    """
    valid_metrics = ["messages", "conversations", "new_users", "active_users"]
    if metric not in valid_metrics:
        from app.common.exceptions.http import bad_request, ErrorCode
        raise bad_request(ErrorCode.INVALID_INPUT, {
            "valid_metrics": valid_metrics
        })

    return await AnalyticsService.get_usage_chart_data(
        db, metric=metric, days=days
    )
