"""
Repository Preferences

Opérations de base de données pour les préférences utilisateur.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import UserPreference


class PreferencesRepository:
    """Repository pour les opérations sur les préférences"""

    @staticmethod
    async def get_by_user_id(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> Optional[UserPreference]:
        """
        Récupère les préférences d'un utilisateur.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur

        Returns:
            Préférences ou None si non trouvées
        """
        result = await db.execute(
            select(UserPreference)
            .options(selectinload(UserPreference.default_mode))
            .where(UserPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: uuid.UUID,
        top_k: int = 4,
        show_sources: bool = True,
        theme: str = "light",
        language: str = "fr",
        default_mode_id: int = 1,
        voice_to_text_enabled: bool = False,
        voice_auto_send: bool = False,
        voice_tts_enabled: bool = False,
        voice_tts_auto_play: bool = False,
        voice_tts_voice: str = "",
        voice_tts_rate: float = 1.0
    ) -> UserPreference:
        """
        Crée les préférences pour un utilisateur.

        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            top_k: Nombre de sources RAG
            show_sources: Afficher les sources
            theme: Thème
            language: Langue (fr/en)
            default_mode_id: Mode par défaut
            voice_to_text_enabled: Transcription vocale activée
            voice_auto_send: Auto-envoi après silence
            voice_tts_enabled: Lecture vocale TTS activée
            voice_tts_auto_play: Lecture automatique sans clic
            voice_tts_voice: Voix TTS sélectionnée
            voice_tts_rate: Vitesse de lecture TTS

        Returns:
            Préférences créées
        """
        preferences = UserPreference(
            user_id=user_id,
            top_k=top_k,
            show_sources=show_sources,
            theme=theme,
            language=language,
            default_mode_id=default_mode_id,
            voice_to_text_enabled=voice_to_text_enabled,
            voice_auto_send=voice_auto_send,
            voice_tts_enabled=voice_tts_enabled,
            voice_tts_auto_play=voice_tts_auto_play,
            voice_tts_voice=voice_tts_voice,
            voice_tts_rate=voice_tts_rate
        )
        db.add(preferences)
        await db.commit()
        await db.refresh(preferences)
        await db.refresh(preferences, ["default_mode"])
        return preferences

    @staticmethod
    async def update(
        db: AsyncSession,
        preferences: UserPreference,
        top_k: Optional[int] = None,
        show_sources: Optional[bool] = None,
        theme: Optional[str] = None,
        language: Optional[str] = None,
        default_mode_id: Optional[int] = None,
        voice_to_text_enabled: Optional[bool] = None,
        voice_auto_send: Optional[bool] = None,
        voice_tts_enabled: Optional[bool] = None,
        voice_tts_auto_play: Optional[bool] = None,
        voice_tts_voice: Optional[str] = None,
        voice_tts_rate: Optional[float] = None
    ) -> UserPreference:
        """
        Met à jour les préférences.

        Args:
            db: Session de base de données
            preferences: Préférences à modifier
            top_k: Nombre de sources RAG (optionnel)
            show_sources: Afficher les sources (optionnel)
            theme: Thème (optionnel)
            language: Langue (optionnel)
            default_mode_id: Mode par défaut (optionnel)
            voice_to_text_enabled: Transcription vocale (optionnel)
            voice_auto_send: Auto-envoi après silence (optionnel)
            voice_tts_enabled: Lecture vocale TTS (optionnel)
            voice_tts_auto_play: Lecture automatique (optionnel)
            voice_tts_voice: Voix TTS (optionnel)
            voice_tts_rate: Vitesse TTS (optionnel)

        Returns:
            Préférences mises à jour
        """
        if top_k is not None:
            preferences.top_k = top_k
        if show_sources is not None:
            preferences.show_sources = show_sources
        if theme is not None:
            preferences.theme = theme
        if language is not None:
            preferences.language = language
        if default_mode_id is not None:
            preferences.default_mode_id = default_mode_id
        if voice_to_text_enabled is not None:
            preferences.voice_to_text_enabled = voice_to_text_enabled
        if voice_auto_send is not None:
            preferences.voice_auto_send = voice_auto_send
        if voice_tts_enabled is not None:
            preferences.voice_tts_enabled = voice_tts_enabled
        if voice_tts_auto_play is not None:
            preferences.voice_tts_auto_play = voice_tts_auto_play
        if voice_tts_voice is not None:
            preferences.voice_tts_voice = voice_tts_voice
        if voice_tts_rate is not None:
            preferences.voice_tts_rate = voice_tts_rate

        await db.commit()
        await db.refresh(preferences)
        await db.refresh(preferences, ["default_mode"])
        return preferences
