"""
Router Health & Metrics

Endpoints pour vérifier la santé de l'application et accéder aux métriques.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response
from prometheus_client import generate_latest

from app.common.schemas.base import HealthResponse
from app.core.deps import get_db
from app.features.health.service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check de tous les services

    Returns:
        État de santé de l'application et ses dépendances
    """
    return await HealthService.get_health_status(db)


@router.get("/metrics")
async def metrics():
    """
    Métriques Prometheus

    Returns:
        Métriques au format Prometheus
    """
    return Response(content=generate_latest(), media_type="text/plain")


@router.get("/")
async def root():
    """
    Endpoint racine

    Returns:
        Informations de base sur l'API
    """
    return {
        "name": "MY-IA API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics"
    }
