"""
Router Admin Users

Endpoints d'administration pour la gestion des utilisateurs.
Tous les endpoints nécessitent le rôle admin.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.users.service import AdminUserService
from app.features.admin.users.schemas import (
    AdminUserCreate, AdminUserUpdate, AdminUserRead, AdminUserListItem,
    RoleChangeRequest, StatusChangeRequest, PasswordResetRequest, VoiceToTextToggleRequest
)
from app.features.admin.schemas import PaginatedResponse
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT
from app.common.utils.security_logger import log_privilege_change

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# LIST & GET
# =============================================================================

@router.get("", response_model=PaginatedResponse[AdminUserListItem])
async def list_users(
    role_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    is_verified: Optional[bool] = None,
    approval_status: Optional[str] = None,
    search: Optional[str] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les utilisateurs avec filtres et pagination.

    Query Parameters:
    - role_id: Filtrer par ID de rôle
    - is_active: Filtrer par statut actif (true/false)
    - is_verified: Filtrer par email vérifié (true/false)
    - search: Recherche dans email ou username
    - created_after: Filtre date création (après)
    - created_before: Filtre date création (avant)
    - limit: Nombre max de résultats (1-200, défaut: 50)
    - offset: Décalage pour pagination

    Requires: Admin role
    """
    try:
        limit = min(limit, 200)

        users, total = await AdminUserService.get_users(
            db=db,
            role_id=role_id,
            is_active=is_active,
            is_verified=is_verified,
            approval_status=approval_status,
            search=search,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users", method="GET", status="200"
        ).inc()

        return PaginatedResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=users
        )

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/users", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}", response_model=AdminUserRead)
async def get_user(
    user_id: uuid.UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les détails complets d'un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Requires: Admin role
    """
    try:
        user_data = await AdminUserService.get_user_details(db, user_id)

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="GET", status="200"
        ).inc()

        return user_data

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CREATE
# =============================================================================

@router.post("", response_model=AdminUserRead, status_code=201)
async def create_user(
    user_data: AdminUserCreate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Crée un nouvel utilisateur.

    Body:
    - email: Adresse email (unique)
    - username: Nom d'utilisateur (unique)
    - password: Mot de passe (min 8 caractères)
    - first_name: Prénom (optionnel)
    - last_name: Nom de famille (optionnel)
    - role_id: ID du rôle (défaut: 2 = user)
    - is_active: Compte actif (défaut: true)
    - is_verified: Email vérifié (défaut: false)

    Requires: Admin role
    """
    try:
        new_user = await AdminUserService.create_user(
            db=db,
            email=user_data.email,
            username=user_data.username,
            password=user_data.password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            phone=user_data.phone,
            address_line1=user_data.address_line1,
            address_line2=user_data.address_line2,
            city_id=user_data.city_id,
            country_code=user_data.country_code,
            role_id=user_data.role_id,
            is_active=user_data.is_active,
            is_verified=user_data.is_verified,
            voice_to_text_enabled=user_data.voice_to_text_enabled
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='admin_user_created',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=new_user.id,
            details={
                'created_user_email': new_user.email,
                'created_user_id': str(new_user.id),
                'role_id': new_user.role_id
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users", method="POST", status="201"
        ).inc()

        # Récupérer les données enrichies pour la réponse
        return await AdminUserService.get_user_details(db, new_user.id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users", method="POST", status="500"
        ).inc()
        logger.error(f"Error creating user: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# UPDATE
# =============================================================================

@router.patch("/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    user_data: AdminUserUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour les informations d'un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Body:
    - email: Nouvelle adresse email (optionnel)
    - username: Nouveau nom d'utilisateur (optionnel)
    - first_name: Nouveau prénom (optionnel)
    - last_name: Nouveau nom de famille (optionnel)
    - is_verified: Nouveau statut de vérification (optionnel)

    Requires: Admin role
    """
    try:
        update_dict = user_data.model_dump(exclude_unset=True)

        updated_user = await AdminUserService.update_user(
            db=db,
            user_id=user_id,
            **update_dict
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='admin_user_updated',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'updates': update_dict
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="PATCH", status="200"
        ).inc()

        return await AdminUserService.get_user_details(db, updated_user.id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/role", response_model=AdminUserRead)
async def change_user_role(
    user_id: uuid.UUID,
    role_data: RoleChangeRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Change le rôle d'un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Body:
    - role_id: Nouveau rôle ID
    - reason: Raison du changement (optionnel)

    Requires: Admin role

    Restrictions:
    - Un admin ne peut pas se rétrograder lui-même
    - Le dernier admin ne peut pas être rétrogradé
    """
    try:
        # Récupérer l'ancien rôle pour l'audit
        old_user_data = await AdminUserService.get_user_details(db, user_id)
        old_role_id = old_user_data["role_id"]

        updated_user = await AdminUserService.change_role(
            db=db,
            user_id=user_id,
            new_role_id=role_data.role_id,
            admin_user_id=admin_user.id
        )

        # Log de sécurité structuré
        log_privilege_change(
            admin_id=str(admin_user.id),
            target_user_id=str(user_id),
            old_role=str(old_role_id),
            new_role=str(role_data.role_id),
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='user_role_changed',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'old_role_id': old_role_id,
                'new_role_id': role_data.role_id,
                'reason': role_data.reason
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/role", method="PATCH", status="200"
        ).inc()

        return await AdminUserService.get_user_details(db, updated_user.id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/role", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error changing role for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/status", response_model=AdminUserRead)
async def change_user_status(
    user_id: uuid.UUID,
    status_data: StatusChangeRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Active ou désactive un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Body:
    - is_active: Nouveau statut (true=actif, false=inactif)
    - reason: Raison du changement (optionnel)

    Requires: Admin role

    Restrictions:
    - Un admin ne peut pas se désactiver lui-même
    """
    try:
        updated_user = await AdminUserService.change_status(
            db=db,
            user_id=user_id,
            is_active=status_data.is_active,
            admin_user_id=admin_user.id
        )

        action_name = 'user_activated' if status_data.is_active else 'user_deactivated'

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name=action_name,
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'is_active': status_data.is_active,
                'reason': status_data.reason
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/status", method="PATCH", status="200"
        ).inc()

        return await AdminUserService.get_user_details(db, updated_user.id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/status", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error changing status for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_user_password(
    user_id: uuid.UUID,
    password_data: PasswordResetRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Réinitialise le mot de passe d'un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Body:
    - new_password: Nouveau mot de passe (min 8 caractères)
    - notify_user: Notifier l'utilisateur par email (non implémenté)

    Requires: Admin role
    """
    try:
        await AdminUserService.reset_password(
            db=db,
            user_id=user_id,
            new_password=password_data.new_password
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='password_reset_by_admin',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'notify_user': password_data.notify_user
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/reset-password", method="POST", status="204"
        ).inc()

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/reset-password", method="POST", status="500"
        ).inc()
        logger.error(f"Error resetting password for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/voice-to-text", response_model=AdminUserRead)
async def toggle_voice_to_text(
    user_id: uuid.UUID,
    data: VoiceToTextToggleRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Active ou désactive la transcription vocale pour un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Body:
    - enabled: true pour activer, false pour désactiver

    Requires: Admin role
    """
    try:
        await AdminUserService.toggle_voice_to_text(
            db=db,
            user_id=user_id,
            enabled=data.enabled
        )

        # Audit log
        action_name = 'voice_to_text_enabled' if data.enabled else 'voice_to_text_disabled'
        await AuditService.log_action(
            db=db,
            action_name=action_name,
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'target_user_id': str(user_id),
                'voice_to_text_enabled': data.enabled
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/voice-to-text", method="PATCH", status="200"
        ).inc()

        return await AdminUserService.get_user_details(db, user_id)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}/voice-to-text", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error toggling voice-to-text for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DELETE
# =============================================================================

@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime un utilisateur.

    Path Parameters:
    - user_id: UUID de l'utilisateur

    Requires: Admin role

    Restrictions:
    - Un admin ne peut pas se supprimer lui-même
    - Le dernier admin ne peut pas être supprimé
    """
    try:
        # Récupérer les infos pour l'audit avant suppression
        user_data = await AdminUserService.get_user_details(db, user_id)

        await AdminUserService.delete_user(
            db=db,
            user_id=user_id,
            admin_user_id=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='admin_user_deleted',
            user_id=admin_user.id,
            resource_type_name='user',
            resource_id=user_id,
            details={
                'deleted_user_id': str(user_id),
                'deleted_user_email': user_data['email'],
                'deleted_user_role': user_data['role_id']
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="DELETE", status="204"
        ).inc()

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/users/{id}", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
