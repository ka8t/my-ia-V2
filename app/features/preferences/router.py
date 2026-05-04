"""
Router Preferences

Endpoints pour la gestion des préférences utilisateur.
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import User
from app.features.auth.service import current_active_user
from app.features.preferences.service import PreferencesService
from app.features.preferences.schemas import PreferencesRead, PreferencesUpdate
from app.features.audit.service import AuditService
from app.common.schemas.base import ConversationModeRead

logger = logging.getLogger(__name__)

# Mapping role_id -> role_name (évite de charger la relation)
ROLE_NAMES = {1: 'admin', 2: 'user', 3: 'contributor', 4: 'validator'}

def get_role_name(role_id: int) -> str:
    """Retourne le nom du rôle depuis son ID."""
    return ROLE_NAMES.get(role_id, 'unknown')

router = APIRouter(
    prefix="/preferences",
    tags=["preferences"]
)


@router.get(
    "/",
    response_model=PreferencesRead,
    summary="Récupérer mes préférences",
    description="Récupère les préférences de l'utilisateur connecté."
)
async def get_preferences(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> PreferencesRead:
    """
    Récupère les préférences de l'utilisateur.

    Si les préférences n'existent pas, elles sont créées avec les valeurs par défaut.
    """
    return await PreferencesService.get_preferences(db, current_user.id)


@router.patch(
    "/",
    response_model=PreferencesRead,
    summary="Modifier mes préférences",
    description="Met à jour les préférences de l'utilisateur connecté."
)
async def update_preferences(
    data: PreferencesUpdate,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> PreferencesRead:
    """
    Met à jour les préférences de l'utilisateur.

    - **top_k**: Nombre de sources RAG (1-10)
    - **show_sources**: Afficher les sources dans les réponses
    - **theme**: Thème de l'interface (light/dark)
    - **default_mode_id**: Mode de conversation par défaut
    """
    result = await PreferencesService.update_preferences(db, current_user.id, data)

    # Audit
    try:
        # Récupérer les champs modifiés
        details = data.model_dump(exclude_unset=True)
        await AuditService.log_action(
            db=db,
            action_name='preferences_updated',
            user_id=current_user.id,
            resource_type_name='user_preference',
            resource_id=current_user.id,
            details=details,
            request=request,
            user_role=get_role_name(current_user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging preferences update: {e}")

    return result


@router.get(
    "/conversation-modes",
    response_model=List[ConversationModeRead],
    summary="Lister les modes de conversation",
    description="Récupère la liste des modes de conversation disponibles pour les utilisateurs."
)
async def list_conversation_modes(
    db: AsyncSession = Depends(get_async_session),
    _: User = Depends(current_active_user)
) -> List[ConversationModeRead]:
    """
    Liste les modes de conversation disponibles.

    Ces modes sont créés par les administrateurs et définissent le comportement
    du chatbot (prompt système, personnalité, etc.).
    """
    return await PreferencesService.list_conversation_modes(db)
