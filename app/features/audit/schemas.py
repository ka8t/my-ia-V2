"""
Schemas Audit

DTOs Pydantic pour le système d'audit.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# --- Réponses ---

class AuditActionResponse(BaseModel):
    """Action d'audit."""
    id: int
    name: str
    display_name: str
    severity: str

    class Config:
        from_attributes = True


class ResourceTypeResponse(BaseModel):
    """Type de ressource."""
    id: int
    name: str
    display_name: str

    class Config:
        from_attributes = True


class AuditUserResponse(BaseModel):
    """Utilisateur simplifié pour audit."""
    id: UUID
    username: str
    email: str
    role_name: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    """Log d'audit complet."""
    id: UUID
    created_at: datetime
    user_id: Optional[UUID] = None
    user: Optional[AuditUserResponse] = None
    action: AuditActionResponse
    resource_type: Optional[ResourceTypeResponse] = None
    resource_id: Optional[UUID] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Liste paginée de logs d'audit."""
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# --- Filtres ---

class AuditLogFilters(BaseModel):
    """Filtres pour la recherche de logs."""
    user_id: Optional[UUID] = Field(None, description="Filtrer par utilisateur")
    action_name: Optional[str] = Field(None, description="Filtrer par action (ex: login)")
    resource_type: Optional[str] = Field(None, description="Filtrer par type de ressource")
    resource_id: Optional[UUID] = Field(None, description="Filtrer par ressource spécifique")
    severity: Optional[str] = Field(None, description="Filtrer par sévérité (info, warning, critical)")
    ip_address: Optional[str] = Field(None, description="Filtrer par adresse IP")
    date_from: Optional[datetime] = Field(None, description="Date de début")
    date_to: Optional[datetime] = Field(None, description="Date de fin")


# --- Statistiques ---

class AuditStatByAction(BaseModel):
    """Statistique par action."""
    action_name: str
    action_display_name: str
    severity: str
    count: int


class AuditStatByUser(BaseModel):
    """Statistique par utilisateur."""
    user_id: UUID
    username: str
    email: str
    action_count: int


class AuditStatByDay(BaseModel):
    """Statistique par jour."""
    date: str  # Format YYYY-MM-DD
    count: int


class AuditStatsResponse(BaseModel):
    """Statistiques globales d'audit."""
    total_logs: int
    logs_today: int
    logs_this_week: int
    logs_this_month: int
    by_action: List[AuditStatByAction]
    by_severity: Dict[str, int]
    by_day: List[AuditStatByDay]  # 30 derniers jours
    top_users: List[AuditStatByUser]  # Top 10 utilisateurs actifs


# --- Export ---

class AuditExportRequest(BaseModel):
    """Paramètres d'export."""
    format: str = Field("csv", pattern="^(csv|json)$", description="Format d'export")
    filters: Optional[AuditLogFilters] = None
    max_rows: int = Field(10000, ge=1, le=100000, description="Nombre max de lignes")
