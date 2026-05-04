"""
Router pour la configuration publique

Endpoint accessible sans authentification pour permettre aux frontends
de configurer dynamiquement l'URL de l'API et autres parametres publics.
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.config.public_schemas import PublicConfigResponse, SpeechConfigPublic
from app.features.system.service import SystemConfigService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["Configuration"])


@router.get(
    "/public",
    response_model=PublicConfigResponse,
    summary="Configuration publique",
    description="Retourne la configuration publique de l'application (accessible sans authentification)"
)
async def get_public_config(
    db: AsyncSession = Depends(get_async_session)
) -> PublicConfigResponse:
    """
    Retourne la configuration publique de l'application.

    Cet endpoint est accessible sans authentification et permet aux frontends
    de configurer dynamiquement l'URL de l'API et autres parametres publics.
    """
    config_service = SystemConfigService(db)

    # Recuperer les configs de la categorie 'app'
    api_url = await config_service.get("app.api_url", "http://localhost:8080")
    app_name = await config_service.get("app.name", "MY-IA")
    debug = await config_service.get("app.debug", False)
    version = await config_service.get("app.version", "1.0.0")

    # Debug config depuis la config admin (BDD + runtime_overrides)
    debug_verbose = await config_service.get("debug.verbose_logging", False)

    # Lire les runtime_overrides pour les flags debug en memoire
    from app.features.admin.config.service import _runtime_overrides
    debug_endpoints_enabled = _runtime_overrides.get('debug_endpoints_enabled', False)
    debug_timing_headers = _runtime_overrides.get('debug_timing_headers', False)

    # Config speech
    speech_enabled = await config_service.get("speech.enabled", False)
    speech_tts_enabled = await config_service.get("speech.tts_enabled", False)
    speech_auto_send = await config_service.get("speech.auto_send_enabled", True)
    speech_language = await config_service.get("speech.default_language", "fr")
    speech_max_duration = await config_service.get("speech.max_duration", 60)
    speech_silence_ms = await config_service.get("speech.silence_duration_ms", 1500)

    logger.debug(f"Public config requested: apiUrl={api_url}, speech_enabled={speech_enabled}")

    def to_bool(val: object) -> bool:
        """Convertit une valeur en bool (supporte str, bool, int)."""
        if isinstance(val, bool):
            return val
        return str(val).lower() == "true"

    return PublicConfigResponse(
        apiUrl=str(api_url),
        appName=str(app_name),
        debug=to_bool(debug),
        debugVerbose=to_bool(debug_verbose),
        debugEndpointsEnabled=bool(debug_endpoints_enabled),
        debugTimingHeaders=bool(debug_timing_headers),
        version=str(version),
        speech=SpeechConfigPublic(
            enabled=to_bool(speech_enabled),
            tts_enabled=to_bool(speech_tts_enabled),
            auto_send_enabled=to_bool(speech_auto_send),
            default_language=str(speech_language),
            max_duration=int(speech_max_duration),
            silence_duration_ms=int(speech_silence_ms)
        )
    )
