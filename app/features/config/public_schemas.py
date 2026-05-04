"""
Schemas Pydantic pour la configuration publique
"""
from pydantic import BaseModel, Field


class SpeechConfigPublic(BaseModel):
    """Configuration speech publique"""
    enabled: bool = Field(False, description="Transcription vocale activee")
    tts_enabled: bool = Field(False, alias="ttsEnabled", description="Text-to-speech active")
    auto_send_enabled: bool = Field(True, alias="autoSendEnabled", description="Envoi auto apres transcription")
    default_language: str = Field("fr", alias="defaultLanguage", description="Langue par defaut")
    max_duration: int = Field(60, alias="maxDuration", description="Duree max en secondes")
    silence_duration_ms: int = Field(1500, alias="silenceDurationMs", description="Silence detection en ms")

    class Config:
        populate_by_name = True


class PublicConfigResponse(BaseModel):
    """Configuration publique de l'application (accessible sans authentification)"""
    api_url: str = Field(..., alias="apiUrl", description="URL de base de l'API backend")
    app_name: str = Field(..., alias="appName", description="Nom de l'application")
    debug: bool = Field(..., description="Mode debug actif")
    debug_verbose: bool = Field(..., alias="debugVerbose", description="Logging console verbeux actif")
    debug_endpoints_enabled: bool = Field(False, alias="debugEndpointsEnabled", description="Endpoints debug actifs")
    debug_timing_headers: bool = Field(False, alias="debugTimingHeaders", description="Headers X-Debug-* actifs")
    version: str = Field(..., description="Version de l'application")
    speech: SpeechConfigPublic = Field(..., description="Configuration speech/TTS")

    class Config:
        populate_by_name = True
