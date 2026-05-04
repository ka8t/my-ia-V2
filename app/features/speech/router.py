"""
Router Speech-to-Text

Endpoints pour la transcription vocale.
"""
import logging
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import User
from app.features.auth.service import current_active_user
from app.features.speech.schemas import TranscriptionResponse, SpeechConfigResponse
from app.features.speech.service import SpeechService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["Speech-to-Text"])

# Formats audio acceptes
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
}

# Taille max: 10 Mo
MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    summary="Transcrire un fichier audio",
    description="Transcrit un fichier audio en texte via Whisper. Necessite que voice_to_text soit active pour l'utilisateur."
)
async def transcribe_audio(
    file: UploadFile = File(..., description="Fichier audio (webm, wav, mp3, ogg)"),
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
) -> TranscriptionResponse:
    """
    Transcrit un fichier audio en texte.

    - Verifie que le service est active globalement
    - Verifie que l'utilisateur a voice_to_text_enabled = true
    - Accepte les formats: webm, wav, mp3, ogg, flac, m4a
    - Taille max: 10 Mo
    - Duree max: configurable via admin
    """
    # Verifier que le service est active globalement
    if not await SpeechService.is_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le service de transcription est desactive par l'administrateur"
        )

    # Verifier que l'utilisateur a active la fonctionnalite
    preference = await SpeechService.get_user_voice_preference(db, user.id)

    if not preference or not preference.voice_to_text_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La transcription vocale n'est pas activee pour votre compte"
        )

    # Verifier le type de fichier
    content_type = file.content_type or ""
    if content_type not in ALLOWED_AUDIO_TYPES:
        # Accepter aussi si l'extension est correcte
        filename_lower = (file.filename or "").lower()
        valid_extensions = (".webm", ".wav", ".mp3", ".ogg", ".flac", ".m4a", ".mp4")
        if not filename_lower.endswith(valid_extensions):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Format audio non supporte: {content_type}. Formats acceptes: webm, wav, mp3, ogg, flac, m4a"
            )

    # Lire le contenu
    try:
        audio_bytes = await file.read()
    except Exception as e:
        logger.error(f"Error reading audio file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Erreur lors de la lecture du fichier audio"
        )

    # Verifier la taille
    if len(audio_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop volumineux ({len(audio_bytes) / 1024 / 1024:.1f} Mo > 10 Mo)"
        )

    if len(audio_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier audio vide"
        )

    # Recuperer la langue : preference utilisateur OU defaut config
    user_language = None
    if preference and preference.language:
        user_language = preference.language
    else:
        user_language = await SpeechService.get_default_language(db)

    # Transcrire
    try:
        text, language, duration, processing_time = await SpeechService.transcribe(
            audio_bytes,
            filename=file.filename or "audio.webm",
            language=user_language,
            db=db
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        logger.error(f"Speech service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service de transcription indisponible"
        )
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la transcription"
        )

    return TranscriptionResponse(
        text=text,
        language=language,
        duration=duration,
        processing_time=processing_time
    )


@router.get(
    "/config",
    response_model=SpeechConfigResponse,
    summary="Configuration du service Speech-to-Text",
    description="Retourne l'etat du service de transcription vocale"
)
async def get_speech_config(
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user)
) -> SpeechConfigResponse:
    """Retourne la configuration du service Speech-to-Text."""
    config = await SpeechService.get_config_async(db)
    return SpeechConfigResponse(**config)


@router.post(
    "/unload",
    summary="Decharger le modele Whisper",
    description="Force le dechargement du modele Whisper pour liberer la memoire (admin uniquement)"
)
async def unload_model(
    user: User = Depends(current_active_user)
) -> dict:
    """
    Force le dechargement du modele Whisper.
    Reserve aux administrateurs.
    """
    if user.role_id not in (1, 3):  # admin ou superuser
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action reservee aux administrateurs"
        )

    was_loaded = SpeechService.is_model_loaded()
    SpeechService.force_unload()

    return {
        "success": True,
        "was_loaded": was_loaded,
        "message": "Modele decharge" if was_loaded else "Modele n'etait pas charge"
    }
