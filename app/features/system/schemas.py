"""
Schemas SystemConfig - Modeles Pydantic pour l'API de configuration.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class SystemConfigResponse(BaseModel):
    """Reponse pour une configuration."""

    id: int
    key: str
    value: Any
    raw_value: str
    value_type: str
    category: str
    description: Optional[str] = None
    is_sensitive: bool = False
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class SystemConfigListResponse(BaseModel):
    """Liste des configurations."""

    configs: List[SystemConfigResponse]
    categories: List[str]


class SystemConfigUpdateRequest(BaseModel):
    """Requete de mise a jour d'une configuration."""

    value: Any = Field(..., description="Nouvelle valeur")


class SystemConfigCreateRequest(BaseModel):
    """Requete de creation d'une configuration."""

    key: str = Field(..., min_length=1, max_length=100)
    value: Any
    value_type: str = Field(default="string", pattern="^(string|int|float|bool|json|list)$")
    category: str = Field(default="general", max_length=50)
    description: Optional[str] = None
    is_sensitive: bool = False


class StorageConfigResponse(BaseModel):
    """Configuration du storage."""

    allowed_mime_types: List[str]
    blocked_extensions: List[str]
    max_file_size_mb: int
    default_quota_mb: int


class StorageConfigUpdateRequest(BaseModel):
    """Mise a jour de la configuration storage."""

    allowed_mime_types: Optional[List[str]] = None
    blocked_extensions: Optional[List[str]] = None
    max_file_size_mb: Optional[int] = Field(None, ge=1, le=500)
    default_quota_mb: Optional[int] = Field(None, ge=1, le=10240)
