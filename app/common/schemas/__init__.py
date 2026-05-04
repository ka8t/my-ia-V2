"""
Schemas Pydantic - Exports
"""
from app.common.schemas.base import (
    # Génériques
    HealthResponse,
    ErrorResponse,
    SuccessResponse,
    # Role
    RoleCreate,
    RoleUpdate,
    RoleRead,
    # ConversationMode
    ConversationModeCreate,
    ConversationModeUpdate,
    ConversationModeRead,
    # ResourceType
    ResourceTypeCreate,
    ResourceTypeUpdate,
    ResourceTypeRead,
    # AuditAction
    AuditActionCreate,
    AuditActionUpdate,
    AuditActionRead,
    # UserPreference
    UserPreferenceUpdate,
    UserPreferenceRead,
    # Conversation
    ConversationRead,
    # Message
    MessageRead,
    # Document
    DocumentRead,
    # Session
    SessionRead,
)

__all__ = [
    "HealthResponse",
    "ErrorResponse",
    "SuccessResponse",
    "RoleCreate",
    "RoleUpdate",
    "RoleRead",
    "ConversationModeCreate",
    "ConversationModeUpdate",
    "ConversationModeRead",
    "ResourceTypeCreate",
    "ResourceTypeUpdate",
    "ResourceTypeRead",
    "AuditActionCreate",
    "AuditActionUpdate",
    "AuditActionRead",
    "UserPreferenceUpdate",
    "UserPreferenceRead",
    "ConversationRead",
    "MessageRead",
    "DocumentRead",
    "SessionRead",
]
