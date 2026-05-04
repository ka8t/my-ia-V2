"""Endpoints pour la gestion du profil utilisateur."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.features.auth.service import current_active_user
from app.models import User
from app.features.user.profile.service import ProfileService
from app.features.user.profile.schemas import (
    ProfileRead,
    ProfileUpdate,
    PasswordChangeRequest,
    PasswordChangeResponse
)
from app.features.audit.service import AuditService

router = APIRouter()


# =============================================================================
# PROFILE ENDPOINTS
# =============================================================================

@router.get(
    "/me/profile",
    response_model=ProfileRead,
    summary="Mon profil complet"
)
async def get_my_profile(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
) -> ProfileRead:
    """
    Recupere le profil complet de l'utilisateur connecte.

    Inclut les informations personnelles, l'adresse et les donnees geo.
    """
    return await ProfileService.get_profile(db, current_user.id)


@router.patch(
    "/me/profile",
    response_model=ProfileRead,
    summary="Modifier mon profil"
)
async def update_my_profile(
    data: ProfileUpdate,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
) -> ProfileRead:
    """
    Met a jour le profil de l'utilisateur connecte.

    Champs modifiables:
    - **first_name**: Prenom
    - **last_name**: Nom
    - **phone**: Telephone (sera normalise)
    - **address_line1**: Adresse ligne 1
    - **address_line2**: Adresse ligne 2
    - **city_id**: ID de la ville
    - **country_code**: Code pays ISO (FR, BE, CH...)
    """
    profile = await ProfileService.update_profile(db, current_user.id, data)

    # Audit
    await AuditService.log_action(
        db=db,
        action_name='profile_updated',
        user_id=current_user.id,
        resource_type_name='user',
        resource_id=current_user.id,
        details={'fields_updated': list(data.model_dump(exclude_unset=True).keys())},
        request=request
    )

    return profile


# =============================================================================
# PASSWORD CHANGE ENDPOINTS
# =============================================================================

@router.post(
    "/me/change-password",
    response_model=PasswordChangeResponse,
    summary="Changer mon mot de passe"
)
async def change_my_password(
    data: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
) -> PasswordChangeResponse:
    """
    Change le mot de passe de l'utilisateur connecte.

    Exigences:
    - Le mot de passe actuel doit etre correct
    - Le nouveau mot de passe doit respecter la politique configuree
    - Le nouveau mot de passe ne doit pas etre dans l'historique recent
    """
    await ProfileService.change_password(
        db=db,
        user_id=current_user.id,
        current_password=data.current_password,
        new_password=data.new_password
    )

    # Audit
    await AuditService.log_action(
        db=db,
        action_name='password_changed',
        user_id=current_user.id,
        resource_type_name='user',
        resource_id=current_user.id,
        details={},
        request=request
    )

    return PasswordChangeResponse(
        success=True,
        message="Mot de passe change avec succes"
    )
