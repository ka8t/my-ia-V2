"""
Router pour les endpoints d'authentification

Expose tous les endpoints d'authentification (login, register, reset-password, verify, oauth).
"""
import logging
import jwt
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.features.auth.service import (
    auth_backend, fastapi_users, current_active_user, optional_current_user,
    AuthDBService,
)
from app.features.auth.config import SECRET, TOKEN_LIFETIME_SECONDS
from app.features.auth.oauth import (
    google_oauth_client,
    github_oauth_client,
    get_oauth_redirect_url,
    get_available_oauth_providers
)
from app.features.user.schemas import UserRead, UserCreate
from app.features.user.dependencies import get_user_manager
from app.models import User
from app.core.deps import get_async_session
from app.features.collections.chroma import delete_user_collection
from app.common.schemas.base import RoleRead
from app.common.i18n import t

logger = logging.getLogger(__name__)


def get_auth_db_service(
    db: AsyncSession = Depends(get_async_session),
) -> AuthDBService:
    """Factory pour le service DB d'authentification."""
    return AuthDBService(session=db)


# Router principal pour l'authentification
router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

# Sous-routers générés par fastapi_users
auth_router = fastapi_users.get_auth_router(auth_backend)
register_router = fastapi_users.get_register_router(UserRead, UserCreate)
reset_password_router = fastapi_users.get_reset_password_router()
verify_router = fastapi_users.get_verify_router(UserRead)

# Inclure tous les sous-routers dans le router principal (pattern FastAPI standard)
router.include_router(auth_router, prefix="/jwt")
router.include_router(register_router, prefix="/register")
router.include_router(reset_password_router, prefix="/reset-password")
router.include_router(verify_router, prefix="/verify")

# OAuth routers (si configures)
if google_oauth_client:
    google_oauth_router = fastapi_users.get_oauth_router(
        google_oauth_client,
        auth_backend,
        SECRET,
        redirect_url=get_oauth_redirect_url("google"),
        associate_by_email=True,  # Associer compte OAuth a user existant par email
        is_verified_by_default=True,  # Users OAuth sont verifies automatiquement
    )
    router.include_router(google_oauth_router, prefix="/oauth/google", tags=["oauth"])

if github_oauth_client:
    github_oauth_router = fastapi_users.get_oauth_router(
        github_oauth_client,
        auth_backend,
        SECRET,
        redirect_url=get_oauth_redirect_url("github"),
        associate_by_email=True,
        is_verified_by_default=True,
    )
    router.include_router(github_oauth_router, prefix="/oauth/github", tags=["oauth"])


@router.get("/oauth/providers")
async def get_oauth_providers() -> List[str]:
    """
    Retourne la liste des providers OAuth disponibles.

    Utilise par le frontend pour afficher les boutons OAuth.
    """
    return get_available_oauth_providers()


@router.get("/check-username/{username}")
async def check_username_availability(
    username: str,
    exclude_user_id: Optional[str] = None,
    service: AuthDBService = Depends(get_auth_db_service),
):
    """
    Verifie si un username est disponible (insensible a la casse).

    Utilise par le frontend lors de l'inscription pour validation en temps reel.

    Args:
        username: Le username a verifier
        exclude_user_id: ID utilisateur a exclure (pour l'edition de profil)

    Returns:
        {"available": true} si le username est libre
        {"available": false} si le username est deja pris
    """
    try:
        # Parser l'UUID d'exclusion si fourni
        parsed_exclude_id = None
        if exclude_user_id:
            try:
                parsed_exclude_id = UUID(exclude_user_id)
            except ValueError:
                pass  # ID invalide, ignorer l'exclusion

        available = await service.check_username_available(username, parsed_exclude_id)
        return {"available": available}
    except Exception as e:
        logger.error(f"Error checking username availability for '{username}': {e}")
        raise HTTPException(
            status_code=500,
            detail=t("error_email_verify_username", error=str(e))
        )


@router.post("/refresh")
async def refresh_token(current_user: User = Depends(current_active_user)):
    """
    Renouvelle le token JWT pour l'utilisateur connecte.

    Le token actuel doit etre valide pour obtenir un nouveau token.
    """
    # Generer un nouveau token
    payload = {
        "sub": str(current_user.id),
        "aud": ["fastapi-users:auth"],
        "exp": datetime.now(timezone.utc) + timedelta(seconds=TOKEN_LIFETIME_SECONDS)
    }

    new_token = jwt.encode(payload, SECRET, algorithm="HS256")

    return {
        "access_token": new_token,
        "token_type": "bearer"
    }


@router.post("/resend-verification")
async def resend_verification_email(
    current_user: User = Depends(current_active_user),
    user_manager = Depends(get_user_manager)
):
    """
    Renvoie l'email de verification pour l'utilisateur connecte.

    Utile si l'utilisateur n'a pas recu l'email initial.
    """
    if current_user.is_verified:
        raise HTTPException(
            status_code=400,
            detail=t("error_email_already_verified")
        )

    await user_manager.request_verify(current_user)
    return {"message": t("success_email_verification_sent")}


# =============================================================================
# DEBUG: Inscription avec ecrasement de compte existant
# =============================================================================

def is_debug_overwrite_enabled() -> bool:
    """Verifie si le mode debug avec ecrasement est active.

    Gere exclusivement par la configuration debug en BDD (admin UI).
    """
    from app.features.admin.config.service import _runtime_overrides
    return bool(_runtime_overrides.get('debug_endpoints_enabled', False))


@router.get("/debug/roles", response_model=List[RoleRead], tags=["debug"])
async def get_debug_roles(
    service: AuthDBService = Depends(get_auth_db_service),
):
    """
    [DEBUG ONLY] Liste tous les roles disponibles.

    Active uniquement si debug_endpoints_enabled=true dans la configuration admin.
    """
    if not is_debug_overwrite_enabled():
        raise HTTPException(
            status_code=403,
            detail=t("error_debug_disabled")
        )

    return await service.list_roles()


@router.post("/register/debug", response_model=UserRead, tags=["debug"])
async def debug_register(
    user_create: UserCreate,
    request: Request,
    role_id: int = 2,  # Par defaut: user standard
    service: AuthDBService = Depends(get_auth_db_service),
    user_manager = Depends(get_user_manager)
):
    """
    [DEBUG ONLY] Inscription avec ecrasement du compte existant.

    Si l'email existe deja, supprime le compte et en cree un nouveau.
    Active uniquement si debug_endpoints_enabled=true dans la configuration admin.

    Args:
        role_id: ID du role a attribuer (1=admin, 2=user, 3=contributor, 4=validator)

    ATTENTION: Ne jamais activer en production !
    """
    if not is_debug_overwrite_enabled():
        raise HTTPException(
            status_code=403,
            detail=t("error_debug_disabled")
        )

    # Verifier que le role existe
    if not await service.get_role_by_id(role_id):
        raise HTTPException(
            status_code=400,
            detail=t("error_role_id_not_found", role_id=role_id)
        )

    # Verifier si l'utilisateur existe
    existing_user = await service.get_user_by_email(user_create.email)

    if existing_user:

        # Supprimer la collection ChromaDB (externe, avant la cascade DB)
        try:
            delete_user_collection(str(existing_user.id))
        except Exception:
            pass

        await service.delete_user_cascade(existing_user)

    # Creer le nouvel utilisateur via le user_manager standard
    try:
        new_user = await user_manager.create(user_create, safe=True, request=request)

        # Modifier le role si different de celui par defaut
        new_user = await service.set_user_role(new_user, role_id)

        return new_user
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
