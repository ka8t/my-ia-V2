"""
Router Admin Dashboard

Endpoints pour le tableau de bord administrateur.
Tous les endpoints nécessitent le rôle admin.
"""
import logging
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.dashboard.service import DashboardService
from app.features.admin.dashboard.schemas import (
    DashboardOverview, UserStats, ConversationStats,
    DocumentStats, UsageDaily, TrendData
)
from app.common.metrics import REQUEST_COUNT
from app.common.utils.timing_stats import timing_stats

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# OVERVIEW
# =============================================================================

@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la vue d'ensemble complète du dashboard.

    Inclut:
    - Statistiques utilisateurs (total, actifs, par rôle, nouveaux)
    - Statistiques conversations (total, par mode, messages)
    - Statistiques documents (total, taille, par type, chunks)
    - Statistiques système (sessions, audit logs)

    Requires: Admin role
    """
    try:
        overview = await DashboardService.get_overview(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/overview", method="GET", status="200"
        ).inc()

        return overview

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/overview", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting dashboard overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# STATISTIQUES DÉTAILLÉES
# =============================================================================

@router.get("/users", response_model=UserStats)
async def get_user_stats(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques détaillées des utilisateurs.

    Requires: Admin role
    """
    try:
        stats = await DashboardService.get_user_stats(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/users", method="GET", status="200"
        ).inc()

        return stats

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/users", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting user stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations", response_model=ConversationStats)
async def get_conversation_stats(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques détaillées des conversations.

    Requires: Admin role
    """
    try:
        stats = await DashboardService.get_conversation_stats(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/conversations", method="GET", status="200"
        ).inc()

        return stats

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/conversations", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting conversation stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents", response_model=DocumentStats)
async def get_document_stats(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques détaillées des documents.

    Requires: Admin role
    """
    try:
        stats = await DashboardService.get_document_stats(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/documents", method="GET", status="200"
        ).inc()

        return stats

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/documents", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting document stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# USAGE
# =============================================================================

@router.get("/usage/daily", response_model=List[UsageDaily])
async def get_usage_daily(
    days: int = 30,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques d'usage des N derniers jours.

    Query Parameters:
    - days: Nombre de jours à analyser (défaut: 30, max: 90)

    Requires: Admin role
    """
    try:
        days = min(days, 90)  # Limiter à 90 jours
        usage = await DashboardService.get_usage_daily(db, days=days)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/usage/daily", method="GET", status="200"
        ).inc()

        return usage

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/usage/daily", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting daily usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TENDANCES
# =============================================================================

@router.get("/trends", response_model=TrendData)
async def get_trends(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les tendances de croissance.

    Compare les 7 derniers jours aux 7 jours précédents.

    Requires: Admin role
    """
    try:
        trends = await DashboardService.get_trends(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/trends", method="GET", status="200"
        ).inc()

        return trends

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/trends", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting trends: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TIMING / PERFORMANCES
# =============================================================================

@router.get("/timing", response_model=Dict[str, Any])
async def get_timing_stats(
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Récupère les statistiques de timing/performance.

    Retourne les métriques de performance pour:
    - Temps de réponse pré-LLM (config, chroma, contextualisation, sources)
    - Statistiques par catégorie (min, max, avg, p95)

    Requires: Admin role
    """
    try:
        summary = timing_stats.get_summary()

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/timing", method="GET", status="200"
        ).inc()

        return summary

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/timing", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting timing stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/timing")
async def reset_timing_stats(
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Réinitialise les statistiques de timing.

    Requires: Admin role
    """
    try:
        timing_stats.reset()

        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/timing", method="DELETE", status="200"
        ).inc()

        return {"message": "Timing statistics reset successfully"}

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/dashboard/timing", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error resetting timing stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
