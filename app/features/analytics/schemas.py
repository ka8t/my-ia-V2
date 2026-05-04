"""
Schemas Analytics

DTOs Pydantic pour le dashboard analytics.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


# --- Statistiques globales ---

class GlobalStats(BaseModel):
    """Statistiques globales de la plateforme."""
    total_users: int
    active_users_today: int
    active_users_week: int
    active_users_month: int
    total_conversations: int
    total_messages: int
    total_documents: int
    storage_used_bytes: int


class UserActivityStats(BaseModel):
    """Statistiques d'activite utilisateur."""
    user_id: UUID
    username: str
    email: str
    messages_count: int
    conversations_count: int
    documents_count: int
    last_activity: Optional[datetime] = None


# --- Statistiques temporelles ---

class TimeSeriesPoint(BaseModel):
    """Point de donnee temporelle."""
    date: str  # Format YYYY-MM-DD
    value: int


class TimeSeriesData(BaseModel):
    """Serie temporelle pour graphiques."""
    label: str
    data: List[TimeSeriesPoint]


class UsageOverTime(BaseModel):
    """Usage au fil du temps."""
    messages: List[TimeSeriesPoint]
    conversations: List[TimeSeriesPoint]
    new_users: List[TimeSeriesPoint]
    active_users: List[TimeSeriesPoint]


# --- Top N ---

class TopQuery(BaseModel):
    """Question frequente."""
    query: str
    count: int
    last_asked: datetime


class TopDocument(BaseModel):
    """Document le plus consulte."""
    document_id: UUID
    filename: str
    owner_username: str
    access_count: int


class TopUser(BaseModel):
    """Utilisateur le plus actif."""
    user_id: UUID
    username: str
    email: str
    activity_score: int  # Messages + conversations


# --- Reponses API ---

class DashboardOverview(BaseModel):
    """Vue d'ensemble du dashboard."""
    stats: GlobalStats
    usage_today: Dict[str, int]
    trends: Dict[str, float]  # Pourcentage de changement vs periode precedente


class AnalyticsResponse(BaseModel):
    """Reponse complete analytics."""
    overview: DashboardOverview
    usage_over_time: UsageOverTime
    top_users: List[TopUser]
    top_queries: List[TopQuery]
