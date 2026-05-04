"""
Schemas Pydantic pour la validation des inscriptions.
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class PendingUserRead(BaseModel):
    """Schema pour un utilisateur en attente de validation."""
    id: UUID
    email: EmailStr
    username: str
    created_at: datetime
    is_verified: bool
    oauth_provider: Optional[str] = None  # google, github, ou None
    role_id: int
    role_name: Optional[str] = None  # display_name du role

    class Config:
        from_attributes = True


class PendingUsersResponse(BaseModel):
    """Reponse avec liste des utilisateurs en attente."""
    total: int
    users: List[PendingUserRead]


class ApproveUserRequest(BaseModel):
    """Requete pour approuver un utilisateur."""
    pass  # Pas de champs requis, l'ID est dans l'URL


class RejectUserRequest(BaseModel):
    """Requete pour refuser un utilisateur."""
    reason: str  # Raison obligatoire pour le refus


class ValidationResponse(BaseModel):
    """Reponse apres approbation ou refus."""
    success: bool
    message: str
    user_id: UUID
    user_email: str
    action: str  # "approved" ou "rejected"


class ValidationStatsResponse(BaseModel):
    """Statistiques de validation."""
    pending_count: int
    approved_today: int
    rejected_today: int


class BulkValidationRequest(BaseModel):
    """Requête pour approbation en masse."""
    user_ids: List[UUID]
    confirm: bool = False  # Sécurité double confirmation


class BulkRejectRequest(BaseModel):
    """Requête pour rejet en masse."""
    user_ids: List[UUID]
    reason: str = Field(..., min_length=10, max_length=500)
    confirm: bool = False


class BulkValidationResponse(BaseModel):
    """Réponse des opérations en masse."""
    success_count: int
    failed_count: int
    failed_ids: List[UUID] = []
    message: str
