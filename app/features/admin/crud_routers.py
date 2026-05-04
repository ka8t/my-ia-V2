"""
CRUD Routers Admin - Routers générés pour les entités de référence.

Utilise le Generic CRUD Router pour réduire la duplication de code.
Remplace ~400 lignes de code répétitif par ~50 lignes.
"""
from app.models import Role, ConversationMode, ResourceType, AuditAction
from app.common.schemas import (
    RoleRead, RoleCreate, RoleUpdate,
    ConversationModeRead, ConversationModeCreate, ConversationModeUpdate,
    ResourceTypeRead, ResourceTypeCreate, ResourceTypeUpdate,
    AuditActionRead, AuditActionCreate, AuditActionUpdate,
)
from app.features.admin.service import AdminService
from app.common.crud_router import create_crud_router


# =============================================================================
# ROLES CRUD Router
# =============================================================================
roles_crud_router = create_crud_router(
    model_class=Role,
    read_schema=RoleRead,
    create_schema=RoleCreate,
    update_schema=RoleUpdate,
    prefix="/roles",
    entity_name="role",
    id_field="role_id",
    service_create=AdminService.create_role,
    service_update=AdminService.update_role,
    service_delete=AdminService.delete_role,
    tags=["Admin - Roles"],
)


# =============================================================================
# CONVERSATION MODES CRUD Router
# =============================================================================
conversation_modes_crud_router = create_crud_router(
    model_class=ConversationMode,
    read_schema=ConversationModeRead,
    create_schema=ConversationModeCreate,
    update_schema=ConversationModeUpdate,
    prefix="/conversation-modes",
    entity_name="conversation_mode",
    id_field="mode_id",
    service_create=AdminService.create_conversation_mode,
    service_update=AdminService.update_conversation_mode,
    service_delete=AdminService.delete_conversation_mode,
    tags=["Admin - Conversation Modes"],
)


# =============================================================================
# RESOURCE TYPES CRUD Router
# =============================================================================
resource_types_crud_router = create_crud_router(
    model_class=ResourceType,
    read_schema=ResourceTypeRead,
    create_schema=ResourceTypeCreate,
    update_schema=ResourceTypeUpdate,
    prefix="/resource-types",
    entity_name="resource_type",
    id_field="type_id",
    service_create=AdminService.create_resource_type,
    service_update=AdminService.update_resource_type,
    service_delete=AdminService.delete_resource_type,
    tags=["Admin - Resource Types"],
)


# =============================================================================
# AUDIT ACTIONS CRUD Router
# =============================================================================
audit_actions_crud_router = create_crud_router(
    model_class=AuditAction,
    read_schema=AuditActionRead,
    create_schema=AuditActionCreate,
    update_schema=AuditActionUpdate,
    prefix="/audit-actions",
    entity_name="audit_action",
    id_field="action_id",
    service_create=AdminService.create_audit_action,
    service_update=AdminService.update_audit_action,
    service_delete=AdminService.delete_audit_action,
    tags=["Admin - Audit Actions"],
)
