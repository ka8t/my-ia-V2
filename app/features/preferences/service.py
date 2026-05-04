"""
Service Preferences

Logique métier pour la gestion des préférences utilisateur.
"""
import uuid
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConversationMode
from app.features.preferences.repository import PreferencesRepository
from app.features.preferences.schemas import PreferencesRead, PreferencesUpdate

logger = logging.getLogger(__name__)


class PreferencesService:
    """Service pour la gestion des préférences"""

    @staticmethod
    async def get_preferences(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> PreferencesRead:
        """
        Récupère les préférences de l'utilisateur.
        Crée les préférences par défaut si elles n'existent pas.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur

        Returns:
            Préférences de l'utilisateur
        """
        preferences = await PreferencesRepository.get_by_user_id(db, user_id)

        # Créer les préférences par défaut si inexistantes
        if not preferences:
            logger.info(f"Creating default preferences for user {user_id}")
            preferences = await PreferencesRepository.create(db, user_id)

        return PreferencesRead(
            top_k=preferences.top_k,
            show_sources=preferences.show_sources,
            theme=preferences.theme,
            language=preferences.language,
            default_mode_id=preferences.default_mode_id,
            default_mode_name=preferences.default_mode.name if preferences.default_mode else None,
            voice_to_text_enabled=preferences.voice_to_text_enabled,
            voice_auto_send=preferences.voice_auto_send,
            voice_tts_enabled=preferences.voice_tts_enabled,
            voice_tts_auto_play=preferences.voice_tts_auto_play,
            voice_tts_voice=preferences.voice_tts_voice,
            voice_tts_rate=preferences.voice_tts_rate
        )

    @staticmethod
    async def update_preferences(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: PreferencesUpdate
    ) -> PreferencesRead:
        """
        Met à jour les préférences de l'utilisateur.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            data: Données de mise à jour

        Returns:
            Préférences mises à jour
        """
        preferences = await PreferencesRepository.get_by_user_id(db, user_id)

        # Créer les préférences si inexistantes
        if not preferences:
            preferences = await PreferencesRepository.create(db, user_id)

        # Mettre à jour
        updated = await PreferencesRepository.update(
            db,
            preferences,
            top_k=data.top_k,
            show_sources=data.show_sources,
            theme=data.theme,
            language=data.language,
            default_mode_id=data.default_mode_id,
            voice_to_text_enabled=data.voice_to_text_enabled,
            voice_auto_send=data.voice_auto_send,
            voice_tts_enabled=data.voice_tts_enabled,
            voice_tts_auto_play=data.voice_tts_auto_play,
            voice_tts_voice=data.voice_tts_voice,
            voice_tts_rate=data.voice_tts_rate
        )

        logger.info(f"Preferences updated for user {user_id}")

        return PreferencesRead(
            top_k=updated.top_k,
            show_sources=updated.show_sources,
            theme=updated.theme,
            language=updated.language,
            default_mode_id=updated.default_mode_id,
            default_mode_name=updated.default_mode.name if updated.default_mode else None,
            voice_to_text_enabled=updated.voice_to_text_enabled,
            voice_auto_send=updated.voice_auto_send,
            voice_tts_enabled=updated.voice_tts_enabled,
            voice_tts_auto_play=updated.voice_tts_auto_play,
            voice_tts_voice=updated.voice_tts_voice,
            voice_tts_rate=updated.voice_tts_rate
        )

    @staticmethod
    async def list_conversation_modes(
        db: AsyncSession
    ) -> List[ConversationMode]:
        """
        Liste les modes de conversation disponibles, triés par ID.

        Args:
            db: Session de base de données

        Returns:
            Liste des modes de conversation
        """
        result = await db.execute(
            select(ConversationMode).order_by(ConversationMode.id)
        )
        return result.scalars().all()
