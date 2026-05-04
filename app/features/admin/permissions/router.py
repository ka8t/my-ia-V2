"""
Router Admin Permissions - Endpoints pour consulter les permissions.

Endpoints:
    GET /api/admin/permissions           - Liste toutes les permissions par role
    GET /api/admin/permissions/{role_id} - Permissions d'un role specifique
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user
from app.models import User
from app.features.admin.permissions.service import PermissionsService
from app.features.admin.permissions.schemas import (
    PermissionsListResponse,
    RolePermissions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/permissions", tags=["Admin Permissions"])


def get_permissions_service(
    session: AsyncSession = Depends(get_db),
) -> PermissionsService:
    """Factory pour le service permissions."""
    return PermissionsService(session=session)


@router.get("", response_model=PermissionsListResponse)
async def list_all_permissions(
    admin: User = Depends(get_current_admin_user),
    service: PermissionsService = Depends(get_permissions_service),
):
    """
    Liste toutes les permissions disponibles par role.

    Retourne les actions organisees par :
    - Role (admin, contributor, user)
    - Categorie (users, collections, documents, etc.)

    Chaque action inclut :
    - Nom technique
    - Nom affiche
    - Description
    - Endpoint API associe
    """
    return await service.get_all_permissions()


@router.get("/{role_id}", response_model=RolePermissions)
async def get_role_permissions(
    role_id: int,
    admin: User = Depends(get_current_admin_user),
    service: PermissionsService = Depends(get_permissions_service),
):
    """
    Retourne les permissions d'un role specifique.

    Args:
        role_id: ID du role (1=admin, 2=contributor, 3=user)
    """
    return await service.get_role_permissions(role_id)
