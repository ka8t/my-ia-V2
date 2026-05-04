"""
Schemas Admin Dashboard

Schémas Pydantic pour les statistiques et métriques du dashboard.
"""
from datetime import date, datetime, timezone
from typing import Optional, List, Dict

from pydantic import BaseModel, Field


# =============================================================================
# STATISTIQUES UTILISATEURS
# =============================================================================

class UserStats(BaseModel):
    """Statistiques des utilisateurs"""
    total: int = Field(..., description="Nombre total d'utilisateurs")
    active: int = Field(..., description="Nombre d'utilisateurs actifs")
    inactive: int = Field(..., description="Nombre d'utilisateurs inactifs")
    verified: int = Field(..., description="Nombre d'utilisateurs vérifiés")
    by_role: Dict[str, int] = Field(default_factory=dict, description="Répartition par rôle")
    new_last_7_days: int = Field(default=0, description="Nouveaux utilisateurs (7 derniers jours)")
    new_last_30_days: int = Field(default=0, description="Nouveaux utilisateurs (30 derniers jours)")


# =============================================================================
# STATISTIQUES CONVERSATIONS
# =============================================================================

class ConversationStats(BaseModel):
    """Statistiques des conversations"""
    total: int = Field(..., description="Nombre total de conversations")
    by_mode: Dict[str, int] = Field(default_factory=dict, description="Répartition par mode")
    messages_total: int = Field(default=0, description="Nombre total de messages")
    avg_messages_per_conversation: float = Field(default=0.0, description="Moyenne messages/conversation")


# =============================================================================
# STATISTIQUES DOCUMENTS
# =============================================================================

class DocumentStats(BaseModel):
    """Statistiques des documents"""
    total: int = Field(..., description="Nombre total de documents")
    total_size_bytes: int = Field(default=0, description="Taille totale en octets")
    by_type: Dict[str, int] = Field(default_factory=dict, description="Répartition par type de fichier")
    total_chunks: int = Field(default=0, description="Nombre total de chunks")


# =============================================================================
# STATISTIQUES SYSTÈME
# =============================================================================

class SystemStats(BaseModel):
    """Statistiques système"""
    total_sessions: int = Field(default=0, description="Nombre total de sessions")
    active_sessions: int = Field(default=0, description="Sessions actives")
    total_audit_logs: int = Field(default=0, description="Nombre total de logs d'audit")


# =============================================================================
# DASHBOARD OVERVIEW
# =============================================================================

class DashboardOverview(BaseModel):
    """Vue d'ensemble du dashboard"""
    users: UserStats
    conversations: ConversationStats
    documents: DocumentStats
    system: SystemStats
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# USAGE QUOTIDIEN / HEBDOMADAIRE
# =============================================================================

class UsageDaily(BaseModel):
    """Statistiques d'usage par jour"""
    day: date = Field(..., description="Date du jour")
    conversations_created: int = Field(default=0, description="Conversations créées")
    messages_sent: int = Field(default=0, description="Messages envoyés")
    documents_uploaded: int = Field(default=0, description="Documents uploadés")
    active_users: int = Field(default=0, description="Utilisateurs actifs")


class UsageWeekly(BaseModel):
    """Statistiques d'usage par semaine"""
    week_start: date = Field(..., description="Début de la semaine")
    week_end: date = Field(..., description="Fin de la semaine")
    conversations_created: int = Field(default=0, description="Conversations créées")
    messages_sent: int = Field(default=0, description="Messages envoyés")
    documents_uploaded: int = Field(default=0, description="Documents uploadés")
    active_users: int = Field(default=0, description="Utilisateurs uniques actifs")


# =============================================================================
# TENDANCES
# =============================================================================

class TrendData(BaseModel):
    """Données de tendance"""
    period: str = Field(..., description="Période analysée (daily, weekly, monthly)")
    data: List[UsageDaily] = Field(default_factory=list, description="Données par période")
    growth_users_percent: float = Field(default=0.0, description="Croissance utilisateurs (%)")
    growth_conversations_percent: float = Field(default=0.0, description="Croissance conversations (%)")
    growth_documents_percent: float = Field(default=0.0, description="Croissance documents (%)")
