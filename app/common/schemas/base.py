"""
Schémas Pydantic de base

Schémas de base réutilisables pour l'ensemble de l'application.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# =============================================================================
# SCHEMAS GENERIQUES
# =============================================================================

class LLMHealthResponse(BaseModel):
    """Détails santé du provider LLM"""
    status: str
    provider: str
    url: Optional[str] = None
    models_available: Optional[int] = None
    models: Optional[List[str]] = None
    error: Optional[str] = None
    using_gpu: Optional[bool] = None


class HealthResponse(BaseModel):
    """Réponse du health check"""
    status: str
    llm: LLMHealthResponse
    chroma: bool
    model: str
    ollama: bool  # Rétrocompatibilité
    using_gpu: Optional[bool] = None  # True=GPU, False=CPU, None=inconnu


class ErrorResponse(BaseModel):
    """Réponse d'erreur standard"""
    detail: str
    status_code: int = Field(..., description="Code HTTP de l'erreur")


class SuccessResponse(BaseModel):
    """Réponse de succès générique"""
    success: bool = True
    message: str


# =============================================================================
# ROLE SCHEMAS
# =============================================================================

class RoleCreate(BaseModel):
    """Création d'un rôle"""
    name: str = Field(..., max_length=50)
    display_name: str = Field(..., max_length=100)
    description: Optional[str] = None


class RoleUpdate(BaseModel):
    """Mise à jour d'un rôle"""
    name: Optional[str] = Field(None, max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


class RoleRead(BaseModel):
    """Lecture d'un rôle"""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# CONVERSATION MODE SCHEMAS
# =============================================================================

class ConversationModeCreate(BaseModel):
    """Création d'un mode de conversation"""
    name: str = Field(..., max_length=50)
    display_name: str = Field(..., max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None


class ConversationModeUpdate(BaseModel):
    """Mise à jour d'un mode de conversation"""
    name: Optional[str] = Field(None, max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    system_prompt: Optional[str] = None


class ConversationModeRead(BaseModel):
    """Lecture d'un mode de conversation"""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# RESOURCE TYPE SCHEMAS
# =============================================================================

class ResourceTypeCreate(BaseModel):
    """Création d'un type de ressource"""
    name: str = Field(..., max_length=50)
    display_name: str = Field(..., max_length=100)


class ResourceTypeUpdate(BaseModel):
    """Mise à jour d'un type de ressource"""
    name: Optional[str] = Field(None, max_length=50)
    display_name: Optional[str] = Field(None, max_length=100)


class ResourceTypeRead(BaseModel):
    """Lecture d'un type de ressource"""
    id: int
    name: str
    display_name: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# AUDIT ACTION SCHEMAS
# =============================================================================

class AuditActionCreate(BaseModel):
    """Création d'une action d'audit"""
    name: str = Field(..., max_length=100)
    display_name: str = Field(..., max_length=200)
    severity: str = Field(default="info", max_length=20)


class AuditActionUpdate(BaseModel):
    """Mise à jour d'une action d'audit"""
    name: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    severity: Optional[str] = Field(None, max_length=20)


class AuditActionRead(BaseModel):
    """Lecture d'une action d'audit"""
    id: int
    name: str
    display_name: str
    severity: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# USER PREFERENCE SCHEMAS
# =============================================================================

class UserPreferenceUpdate(BaseModel):
    """Mise à jour des préférences"""
    top_k: Optional[int] = Field(None, ge=1, le=20)
    show_sources: Optional[bool] = None
    theme: Optional[str] = Field(None, max_length=20)
    default_mode_id: Optional[int] = None


class UserPreferenceRead(BaseModel):
    """Lecture des préférences"""
    id: uuid.UUID
    user_id: uuid.UUID
    top_k: int
    show_sources: bool
    theme: str
    default_mode_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# CONVERSATION SCHEMAS
# =============================================================================

class ConversationRead(BaseModel):
    """Lecture d'une conversation"""
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    mode_id: int
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =============================================================================
# MESSAGE SCHEMAS
# =============================================================================

class MessageRead(BaseModel):
    """Lecture d'un message"""
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: str
    content: str
    sources: Optional[Dict[str, Any]] = None
    created_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =============================================================================
# DOCUMENT SCHEMAS
# =============================================================================

class DocumentRead(BaseModel):
    """Lecture d'un document"""
    id: uuid.UUID
    user_id: uuid.UUID
    filename: str
    file_hash: str
    file_size: int
    file_type: str
    chunk_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# SESSION SCHEMAS
# =============================================================================

class SessionRead(BaseModel):
    """Lecture d'une session"""
    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    created_at: datetime
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True
