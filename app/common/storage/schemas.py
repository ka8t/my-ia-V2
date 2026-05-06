"""
Schemas Storage

Ce module définit les dataclasses et modèles Pydantic pour le storage.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


@dataclass
class FileInfo:
    """Métadonnées d'un fichier stocké."""

    path: str
    filename: str
    size: int  # bytes
    mime_type: str
    created_at: datetime
    modified_at: datetime


@dataclass
class StorageStats:
    """Statistiques globales du storage."""

    total_bytes: int  # Espace total
    used_bytes: int  # Espace utilisé
    free_bytes: int  # Espace libre
    file_count: int  # Nombre de fichiers
    user_count: int  # Nombre d'utilisateurs avec fichiers

    @property
    def usage_percent(self) -> float:
        """Pourcentage d'utilisation."""
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100

    @property
    def total_gb(self) -> float:
        """Espace total en GB."""
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        """Espace utilisé en GB."""
        return self.used_bytes / (1024**3)

    @property
    def free_gb(self) -> float:
        """Espace libre en GB."""
        return self.free_bytes / (1024**3)


@dataclass
class UserStorageStats:
    """Statistiques de stockage d'un utilisateur."""

    user_id: UUID
    used_bytes: int  # Espace utilisé
    file_count: int  # Nombre de fichiers
    quota_bytes: Optional[int] = None  # Quota (None = illimité)
    quota_used_percent: float = 0.0  # % du quota utilisé (0-100)

    @property
    def used_mb(self) -> float:
        """Espace utilisé en MB."""
        return self.used_bytes / (1024**2)

    @property
    def quota_mb(self) -> Optional[float]:
        """Quota en MB."""
        if self.quota_bytes is None:
            return None
        return self.quota_bytes / (1024**2)

    @property
    def remaining_bytes(self) -> Optional[int]:
        """Espace restant en bytes."""
        if self.quota_bytes is None:
            return None
        return max(0, self.quota_bytes - self.used_bytes)


@dataclass
class QuotaConfig:
    """Configuration des quotas."""

    default_quota_bytes: int  # Quota par défaut (ex: 100 MB)
    max_file_size_bytes: int  # Taille max par fichier (ex: 50 MB)
    allowed_mime_types: List[str] = field(default_factory=list)  # Types autorisés
    blocked_extensions: List[str] = field(default_factory=list)  # Extensions bloquées

    @property
    def default_quota_mb(self) -> float:
        """Quota par défaut en MB."""
        return self.default_quota_bytes / (1024**2)

    @property
    def max_file_size_mb(self) -> float:
        """Taille max fichier en MB."""
        return self.max_file_size_bytes / (1024**2)


# === Pydantic Models pour API ===


class StorageStatsResponse(BaseModel):
    """Réponse API pour les stats globales."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    file_count: int
    user_count: int
    usage_percent: float
    total_gb: float
    used_gb: float
    free_gb: float

    class Config:
        from_attributes = True


class UserStorageStatsResponse(BaseModel):
    """Réponse API pour les stats utilisateur."""

    user_id: UUID
    used_bytes: int
    file_count: int
    quota_bytes: Optional[int] = None
    quota_used_percent: float = 0.0
    used_mb: float
    quota_mb: Optional[float] = None
    remaining_bytes: Optional[int] = None

    class Config:
        from_attributes = True


class QuotaUpdateRequest(BaseModel):
    """Requête pour modifier le quota d'un utilisateur."""

    quota_mb: int = Field(..., ge=0, le=10240, description="Quota en MB (0-10GB)")


class FileInfoResponse(BaseModel):
    """Réponse API pour les infos d'un fichier."""

    path: str
    filename: str
    size: int
    mime_type: str
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True
