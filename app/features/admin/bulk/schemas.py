"""
Schemas Admin Bulk

Schémas Pydantic pour les opérations en masse.
"""
import uuid
from typing import List, Dict, Optional

from pydantic import BaseModel, Field


# =============================================================================
# REQUÊTES BULK
# =============================================================================

class BulkUserIds(BaseModel):
    """Liste d'IDs utilisateurs pour opérations bulk"""
    user_ids: List[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Liste des IDs utilisateurs (max 100)"
    )


class BulkRoleChange(BaseModel):
    """Changement de rôle en masse"""
    user_ids: List[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Liste des IDs utilisateurs (max 100)"
    )
    new_role_id: int = Field(..., ge=1, description="Nouveau rôle ID")
    reason: Optional[str] = Field(None, max_length=500, description="Raison du changement")


class BulkIds(BaseModel):
    """Liste d'IDs génériques pour opérations bulk"""
    ids: List[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Liste des IDs (max 100)"
    )


class BulkDeleteRequest(BaseModel):
    """Requête de suppression en masse"""
    ids: List[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Liste des IDs à supprimer (max 100)"
    )
    confirm: bool = Field(
        default=False,
        description="Confirmation obligatoire (doit être true)"
    )


# =============================================================================
# REQUÊTES BULK FILTRÉES
# =============================================================================

class BulkUserFilters(BaseModel):
    """Filtres pour opérations bulk sur utilisateurs"""
    role_id: Optional[int] = Field(None, description="Filtrer par rôle")
    is_active: Optional[bool] = Field(None, description="Filtrer par statut actif")
    is_verified: Optional[bool] = Field(None, description="Filtrer par email vérifié")
    search: Optional[str] = Field(None, max_length=100, description="Recherche texte")


class BulkFilteredRequest(BaseModel):
    """Requête pour opération bulk avec filtres"""
    filters: BulkUserFilters = Field(..., description="Filtres à appliquer")
    confirm: bool = Field(default=False, description="Confirmation obligatoire")


class BulkFilteredRoleChange(BaseModel):
    """Changement de rôle en masse avec filtres"""
    filters: BulkUserFilters = Field(..., description="Filtres à appliquer")
    new_role_id: int = Field(..., ge=1, description="Nouveau rôle ID")
    confirm: bool = Field(default=False, description="Confirmation obligatoire")


# =============================================================================
# RÉPONSES BULK
# =============================================================================

class BulkOperationResult(BaseModel):
    """Résultat d'une opération bulk"""
    success_count: int = Field(..., description="Nombre d'opérations réussies")
    failed_count: int = Field(..., description="Nombre d'opérations échouées")
    failed_ids: List[uuid.UUID] = Field(
        default_factory=list,
        description="IDs des opérations échouées"
    )
    errors: Dict[str, str] = Field(
        default_factory=dict,
        description="Détails des erreurs par ID"
    )


class AdminUserInfo(BaseModel):
    """Info minimale d'un admin pour le preflight"""
    id: uuid.UUID
    email: str
    username: Optional[str] = None


class BulkPreflightResponse(BaseModel):
    """Réponse de vérification avant opération bulk filtrée"""
    total_count: int = Field(..., description="Nombre total d'utilisateurs impactés")
    admin_count: int = Field(default=0, description="Nombre d'admins dans la sélection")
    admins: List[AdminUserInfo] = Field(
        default_factory=list,
        description="Liste des admins détectés (si bloquant)"
    )
    can_proceed: bool = Field(..., description="True si l'opération peut continuer")
    warning_message: Optional[str] = Field(None, description="Message d'avertissement")
