"""
Router Admin Password Policy

Endpoints d'administration pour la gestion des politiques de mot de passe.
Tous les endpoints necessitent le role admin.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.password_policy.service import PasswordPolicyService
from app.features.admin.password_policy.schemas import (
    PasswordPolicyCreate,
    PasswordPolicyUpdate,
    PasswordPolicyRead,
    PasswordPolicyListItem,
    PasswordValidationRequest,
    PasswordValidationResult,
    PasswordRequirements
)
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# LIST & GET
# =============================================================================

@router.get("", response_model=List[PasswordPolicyListItem])
async def list_password_policies(
    include_inactive: bool = False,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste toutes les politiques de mot de passe.

    Query Parameters:
    - include_inactive: Inclure les politiques inactives (defaut: false)

    Requires: Admin role
    """
    try:
        policies = await PasswordPolicyService.get_all_policies(db, include_inactive)

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies", method="GET", status="200"
        ).inc()

        return policies

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing password policies: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/requirements", response_model=PasswordRequirements)
async def get_password_requirements(
    policy_name: str = "default",
    db: AsyncSession = Depends(get_db)
):
    """
    Retourne les exigences de mot de passe pour le frontend.

    Query Parameters:
    - policy_name: Nom de la politique (defaut: "default")

    Note: Cet endpoint est public pour permettre au frontend
    d'afficher les exigences avant l'inscription.
    """
    try:
        requirements = await PasswordPolicyService.get_requirements(db, policy_name)

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/requirements", method="GET", status="200"
        ).inc()

        return requirements

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/requirements", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting password requirements: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{policy_id}", response_model=PasswordPolicyRead)
async def get_password_policy(
    policy_id: int,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere les details d'une politique de mot de passe.

    Path Parameters:
    - policy_id: ID de la politique

    Requires: Admin role
    """
    try:
        policy = await PasswordPolicyService.get_policy(db, policy_id)

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="GET", status="200"
        ).inc()

        return policy

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting password policy {policy_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CREATE
# =============================================================================

@router.post("", response_model=PasswordPolicyRead, status_code=201)
async def create_password_policy(
    policy_data: PasswordPolicyCreate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cree une nouvelle politique de mot de passe.

    Body:
    - name: Nom unique de la politique
    - min_length: Longueur minimale (4-128)
    - max_length: Longueur maximale (8-256)
    - require_uppercase: Exiger majuscule
    - require_lowercase: Exiger minuscule
    - require_digit: Exiger chiffre
    - require_special: Exiger caractere special
    - special_characters: Liste des caracteres speciaux
    - expire_days: Jours avant expiration (0=jamais)
    - history_count: Nombre anciens mdp interdits
    - max_failed_attempts: Tentatives avant blocage
    - lockout_duration_minutes: Duree blocage
    - is_active: Politique active

    Requires: Admin role
    """
    try:
        policy = await PasswordPolicyService.create_policy(
            db=db,
            **policy_data.model_dump()
        )

        # Rafraichir l'objet pour detacher de la session
        await db.refresh(policy)

        # Audit log (resource_id=None car policy.id est un int, pas UUID)
        await AuditService.log_action(
            db=db,
            action_name='password_policy_created',
            user_id=admin_user.id,
            resource_type_name='password_policy',
            resource_id=None,
            details={
                'policy_id': policy.id,
                'policy_name': policy.name,
                'min_length': policy.min_length,
                'require_uppercase': policy.require_uppercase,
                'require_special': policy.require_special
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies", method="POST", status="201"
        ).inc()

        return PasswordPolicyRead.model_validate(policy)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies", method="POST", status="500"
        ).inc()
        logger.error(f"Error creating password policy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPDATE
# =============================================================================

@router.patch("/{policy_id}", response_model=PasswordPolicyRead)
async def update_password_policy(
    policy_id: int,
    policy_data: PasswordPolicyUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour une politique de mot de passe.

    Path Parameters:
    - policy_id: ID de la politique

    Body: Tous les champs sont optionnels

    Requires: Admin role
    """
    try:
        update_dict = policy_data.model_dump(exclude_unset=True)

        policy = await PasswordPolicyService.update_policy(
            db=db,
            policy_id=policy_id,
            **update_dict
        )

        # Rafraichir l'objet pour detacher de la session
        await db.refresh(policy)

        # Audit log (resource_id=None car policy.id est un int, pas UUID)
        await AuditService.log_action(
            db=db,
            action_name='password_policy_updated',
            user_id=admin_user.id,
            resource_type_name='password_policy',
            resource_id=None,
            details={
                'policy_id': policy.id,
                'policy_name': policy.name,
                'updates': update_dict
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="PATCH", status="200"
        ).inc()

        return PasswordPolicyRead.model_validate(policy)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating password policy {policy_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DELETE
# =============================================================================

@router.delete("/{policy_id}", status_code=204)
async def delete_password_policy(
    policy_id: int,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime une politique de mot de passe.

    Path Parameters:
    - policy_id: ID de la politique

    Requires: Admin role

    Note: La politique "default" ne peut pas etre supprimee.
    """
    try:
        # Recuperer le nom avant suppression pour l'audit
        policy = await PasswordPolicyService.get_policy(db, policy_id)
        policy_name = policy.name

        await PasswordPolicyService.delete_policy(db, policy_id)

        # Audit log (resource_id=None car policy_id est un int, pas UUID)
        await AuditService.log_action(
            db=db,
            action_name='password_policy_deleted',
            user_id=admin_user.id,
            resource_type_name='password_policy',
            resource_id=None,
            details={'policy_id': policy_id, 'policy_name': policy_name},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="DELETE", status="204"
        ).inc()

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/{id}", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting password policy {policy_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VALIDATION
# =============================================================================

@router.post("/validate", response_model=PasswordValidationResult)
async def validate_password(
    validation_request: PasswordValidationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Valide un mot de passe contre une politique.

    Body:
    - password: Mot de passe a valider
    - policy_name: Nom de la politique (defaut: "default")

    Returns:
    - is_valid: Mot de passe valide ou non
    - errors: Liste des erreurs
    - strength_score: Score de robustesse (0-100)
    - suggestions: Suggestions d'amelioration

    Note: Cet endpoint est public pour permettre la validation
    en temps reel lors de l'inscription.
    """
    try:
        result = await PasswordPolicyService.validate_password(
            db=db,
            password=validation_request.password,
            policy_name=validation_request.policy_name
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/validate", method="POST", status="200"
        ).inc()

        return PasswordValidationResult(
            is_valid=result.is_valid,
            errors=result.errors,
            strength_score=result.strength_score,
            suggestions=result.suggestions
        )

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/password-policies/validate", method="POST", status="500"
        ).inc()
        logger.error(f"Error validating password: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
