"""
Schemas Preferences

Schémas Pydantic pour les préférences utilisateur.
"""
from typing import Optional

from pydantic import BaseModel, Field


class PreferencesRead(BaseModel):
    """Schéma de lecture des préférences"""
    top_k: int = Field(description="Nombre de sources RAG à utiliser")
    show_sources: bool = Field(description="Afficher les sources dans les réponses")
    theme: str = Field(description="Thème visuel de l'interface")
    language: str = Field(description="Langue de l'interface (fr/en)")
    default_mode_id: int = Field(description="Mode de conversation par défaut")
    default_mode_name: Optional[str] = Field(None, description="Nom du mode par défaut")
    voice_to_text_enabled: bool = Field(description="Transcription vocale activée")
    voice_auto_send: bool = Field(description="Auto-envoi après silence détecté")
    voice_tts_enabled: bool = Field(description="Lecture vocale des réponses activée")
    voice_tts_auto_play: bool = Field(description="Lecture automatique sans clic")
    voice_tts_voice: str = Field(description="Voix TTS sélectionnée")
    voice_tts_rate: float = Field(description="Vitesse de lecture TTS (0.5-2.0)")
    rag_mode: str = Field(default="auto", description="Mode RAG: auto, fast, full")

    class Config:
        from_attributes = True


class PreferencesUpdate(BaseModel):
    """Schéma de mise à jour des préférences"""
    top_k: Optional[int] = Field(None, ge=1, le=10, description="Nombre de sources RAG (1-10)")
    show_sources: Optional[bool] = Field(None, description="Afficher les sources")
    theme: Optional[str] = Field(
        None,
        pattern="^(default|light|dark|corporate|corporate-dark|nature|nature-dark|sunset|sunset-dark|royal|royal-dark)$",
        description="Thème visuel (light est un alias de default)"
    )
    language: Optional[str] = Field(None, pattern="^(fr|en)$", description="Langue (fr/en)")
    default_mode_id: Optional[int] = Field(None, ge=1, description="Mode par défaut")
    voice_to_text_enabled: Optional[bool] = Field(None, description="Activer la transcription vocale")
    voice_auto_send: Optional[bool] = Field(None, description="Auto-envoi après silence")
    voice_tts_enabled: Optional[bool] = Field(None, description="Lecture vocale des réponses")
    voice_tts_auto_play: Optional[bool] = Field(None, description="Lecture automatique")
    voice_tts_voice: Optional[str] = Field(None, max_length=100, description="Voix TTS")
    voice_tts_rate: Optional[float] = Field(None, ge=0.5, le=2.0, description="Vitesse TTS (0.5-2.0)")
    rag_mode: Optional[str] = Field(None, pattern="^(auto|fast|full)$", description="Mode RAG: auto, fast, full")
