"""
Router pour les endpoints de validation des inscriptions.

Accessible uniquement aux admins et validateurs.
"""
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_async_session, get_current_admin_user
from app.core.logging import username_var
from app.features.auth.service import current_active_user
from app.models import User
from app.common.utils.security_logger import log_access_denied
from app.features.admin.validation.service import ValidationService
from app.features.admin.validation.schemas import (
    PendingUserRead,
    PendingUsersResponse,
    RejectUserRequest,
    ValidationResponse,
    ValidationStatsResponse,
    BulkValidationRequest,
    BulkRejectRequest,
    BulkValidationResponse
)
from app.features.audit.service import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/validation",
    tags=["admin-validation"]
)


async def require_validator(
    request: Request,
    current_user: User = Depends(current_active_user),
) -> User:
    """
    Dependency pour verifier que l'utilisateur est admin ou validateur.
    Inclut le logging de securite (acces refuse) et l'enrichissement
    des logs applicatifs, comme get_current_admin_user.
    """
    # role_id 1 = admin, role_id 4 = validator
    if current_user.role_id not in [1, 4]:
        log_access_denied(
            user_id=str(current_user.id),
            path=request.url.path,
            reason="admin_or_validator_required",
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces reserve aux administrateurs et validateurs"
        )

    # Enrichir les logs applicatifs avec le username
    username_var.set(current_user.username)

    return current_user


@router.get("/pending", response_model=PendingUsersResponse)
async def get_pending_users(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Liste les utilisateurs en attente de validation.
    """
    users, total = await ValidationService.get_pending_users(db, limit, offset)

    # Transformer en schema de reponse
    pending_users = []
    for user in users:
        oauth_provider = None
        if user.oauth_accounts:
            oauth_provider = user.oauth_accounts[0].oauth_name

        pending_users.append(PendingUserRead(
            id=user.id,
            email=user.email,
            username=user.username,
            created_at=user.created_at,
            is_verified=user.is_verified,
            oauth_provider=oauth_provider,
            role_id=user.role_id,
            role_name=user.role.display_name if user.role else None
        ))

    return PendingUsersResponse(total=total, users=pending_users)


# ========================================================================
# ROUTES BULK - Doivent être AVANT les routes avec {user_id}
# ========================================================================

@router.post("/bulk/approve", response_model=BulkValidationResponse)
async def bulk_approve_users(
    body: BulkValidationRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Approuve plusieurs utilisateurs en masse.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun utilisateur sélectionné"
        )

    logger.info(f"Bulk approve: {len(body.user_ids)} users par admin_id={current_user.id}")

    result = await ValidationService.bulk_approve_users(
        db, body.user_ids, current_user.id
    )

    return BulkValidationResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} utilisateur(s) approuvé(s)"
    )


@router.post("/bulk/reject", response_model=BulkValidationResponse)
async def bulk_reject_users(
    body: BulkRejectRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Rejette plusieurs utilisateurs en masse.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun utilisateur sélectionné"
        )

    logger.info(f"Bulk reject: {len(body.user_ids)} users par admin_id={current_user.id}")

    result = await ValidationService.bulk_reject_users(
        db, body.user_ids, current_user.id, body.reason
    )

    return BulkValidationResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} utilisateur(s) rejeté(s)"
    )


# ========================================================================
# ROUTES INDIVIDUELLES - Avec {user_id} en paramètre
# ========================================================================

@router.post("/{user_id}/approve", response_model=ValidationResponse)
async def approve_user(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Approuve un utilisateur en attente.
    """
    user = await ValidationService.approve_user(db, user_id, current_user.id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouve ou deja traite"
        )

    # Audit log
    await AuditService.log_user_approved(
        db=db,
        admin_user_id=current_user.id,
        target_user_id=user.id,
        target_user_email=user.email,
        request=request
    )

    return ValidationResponse(
        success=True,
        message=f"Utilisateur {user.email} approuve avec succes",
        user_id=user.id,
        user_email=user.email,
        action="approved"
    )


@router.post("/{user_id}/reject", response_model=ValidationResponse)
async def reject_user(
    user_id: UUID,
    body: RejectUserRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Refuse un utilisateur en attente.
    """
    if not body.reason or len(body.reason.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La raison du refus doit contenir au moins 10 caracteres"
        )

    reason = body.reason.strip()
    user = await ValidationService.reject_user(
        db, user_id, current_user.id, reason
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouve ou deja traite"
        )

    # Audit log
    await AuditService.log_user_rejected(
        db=db,
        admin_user_id=current_user.id,
        target_user_id=user.id,
        target_user_email=user.email,
        reason=reason,
        request=http_request
    )

    return ValidationResponse(
        success=True,
        message=f"Utilisateur {user.email} refuse",
        user_id=user.id,
        user_email=user.email,
        action="rejected"
    )


@router.get("/stats", response_model=ValidationStatsResponse)
async def get_validation_stats(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_validator)
):
    """
    Recupere les statistiques de validation.
    """
    stats = await ValidationService.get_validation_stats(db)
    return ValidationStatsResponse(**stats)
