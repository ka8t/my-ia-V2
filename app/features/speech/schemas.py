"""
Schemas Pydantic pour le module Speech-to-Text
"""
from typing import Optional

from pydantic import BaseModel, Field


class TranscriptionResponse(BaseModel):
    """Reponse de transcription audio"""
    text: str = Field(..., description="Texte transcrit")
    language: str = Field(..., description="Langue detectee (code ISO)")
    duration: float = Field(..., description="Duree de l'audio en secondes")
    processing_time: float = Field(..., description="Temps de traitement en secondes")


class SpeechConfigResponse(BaseModel):
    """Configuration du service Speech-to-Text (endpoint utilisateur)"""
    enabled: bool = Field(..., description="Service actif")
    model_loaded: bool = Field(..., description="Modele charge (toujours false car géré par container)")
    model_name: str = Field(..., description="Nom du modele Whisper")
    max_audio_duration: int = Field(..., description="Duree max audio en secondes")
    service_url: str = Field(..., description="URL du service Whisper")
    # Auto-envoi (STT)
    auto_send_enabled: bool = Field(True, description="Auto-envoi apres silence active globalement")
    silence_duration_ms: int = Field(1500, description="Duree de silence avant arret (ms)")
    silence_threshold: float = Field(0.01, description="Seuil RMS de detection du silence")
    # TTS
    tts_enabled: bool = Field(True, description="Lecture vocale TTS active globalement")
    tts_mode: str = Field("native", description="Mode TTS : native ou server")
    tts_default_rate: float = Field(1.0, description="Vitesse de lecture TTS par defaut")
