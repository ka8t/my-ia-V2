"""
Schemas partagés pour le module Admin

Schemas de base réutilisables pour tous les sub-modules admin.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Generic, TypeVar
from enum import Enum

from pydantic import BaseModel, Field


# TypeVar pour les réponses paginées génériques
T = TypeVar('T')


# =============================================================================
# PAGINATION
# =============================================================================

class PaginationParams(BaseModel):
    """Paramètres de pagination standard"""
    limit: int = Field(default=50, ge=1, le=200, description="Nombre d'éléments par page")
    offset: int = Field(default=0, ge=0, description="Décalage pour la pagination")


class PaginatedResponse(BaseModel, Generic[T]):
    """Réponse paginée générique"""
    total: int = Field(..., description="Nombre total d'éléments")
    limit: int = Field(..., description="Limite appliquée")
    offset: int = Field(..., description="Décalage appliqué")
    items: List[T] = Field(..., description="Liste des éléments")


# =============================================================================
# FILTRES COMMUNS
# =============================================================================

class DateRangeFilter(BaseModel):
    """Filtre par plage de dates"""
    created_after: Optional[datetime] = Field(None, description="Créé après cette date")
    created_before: Optional[datetime] = Field(None, description="Créé avant cette date")


# =============================================================================
# RÉPONSES OPÉRATIONS
# =============================================================================

class OperationResult(BaseModel):
    """Résultat d'une opération simple"""
    success: bool = Field(..., description="Succès de l'opération")
    message: str = Field(..., description="Message descriptif")
    affected_count: int = Field(default=0, description="Nombre d'éléments affectés")


class BulkOperationResult(BaseModel):
    """Résultat d'une opération bulk"""
    success_count: int = Field(..., description="Nombre d'opérations réussies")
    failed_count: int = Field(..., description="Nombre d'opérations échouées")
    failed_ids: List[uuid.UUID] = Field(default_factory=list, description="IDs des opérations échouées")
    errors: dict = Field(default_factory=dict, description="Détails des erreurs par ID")


# =============================================================================
# ENUMS
# =============================================================================

class ExportFormat(str, Enum):
    """Formats d'export disponibles"""
    CSV = "csv"
    JSON = "json"


class SortOrder(str, Enum):
    """Ordre de tri"""
    ASC = "asc"
    DESC = "desc"
