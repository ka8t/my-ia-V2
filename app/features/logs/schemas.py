"""
Schemas Pydantic pour le module Logs

DTOs pour la lecture, le filtrage et les statistiques des logs applicatifs.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AppLogRead(BaseModel):
    """DTO de lecture d'un log applicatif."""
    id: UUID
    timestamp: datetime
    level: str
    log_category: str
    service: Optional[str] = None
    environment: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[UUID] = None
    username: Optional[str] = None
    session_id: Optional[str] = None
    message: str
    context: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    logger_name: Optional[str] = None
    is_alert: bool = False

    model_config = {"from_attributes": True}


class LogListResponse(BaseModel):
    """Réponse paginée pour la liste des logs."""
    items: List[AppLogRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class LogFilter(BaseModel):
    """Filtres pour la recherche de logs."""
    log_category: Optional[str] = None
    level: Optional[str] = None
    search: Optional[str] = None
    user_id: Optional[UUID] = None
    request_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    is_alert: Optional[bool] = None


class LogCategoryStats(BaseModel):
    """Statistiques par catégorie de log."""
    category: str
    count: int


class LogLevelStats(BaseModel):
    """Statistiques par niveau de log."""
    level: str
    count: int


class LogStatsResponse(BaseModel):
    """Réponse pour les statistiques de logs."""
    total: int
    by_category: List[LogCategoryStats]
    by_level: List[LogLevelStats]
    alerts_count: int


class LogCleanupRequest(BaseModel):
    """Requête de purge des logs."""
    category: Optional[str] = Field(None, description="Catégorie à purger (toutes si None)")
    older_than_days: int = Field(30, ge=0, description="Supprimer les logs plus vieux que N jours (0 = tout purger)")


class LogCleanupResponse(BaseModel):
    """Réponse après purge des logs."""
    deleted_count: int
    category: Optional[str]
    older_than_days: int


class AlertListResponse(BaseModel):
    """Réponse pour la liste des alertes récentes."""
    items: List[AppLogRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class BulkLogDeleteRequest(BaseModel):
    """Requête de suppression en masse de logs."""
    log_ids: List[UUID] = Field(..., min_length=1, max_length=1000, description="IDs des logs à supprimer")
    confirm: bool = Field(..., description="Confirmation de la suppression")


class BulkLogDeleteResponse(BaseModel):
    """Réponse après suppression en masse de logs."""
    success_count: int
    failed_count: int = 0
    errors: List[str] = []
