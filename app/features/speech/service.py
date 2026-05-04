"""
Service Speech-to-Text

Transcription vocale via le container faster-whisper-server.
- Appel HTTP au container isolé (pas de modèle en mémoire locale)
- API compatible OpenAI (POST /v1/audio/transcriptions)
- Support des formats audio courants (wav, mp3, webm, ogg, flac, m4a)
- Configuration dynamique via base de données
"""
import logging
import time
import uuid
from typing import Dict, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import UserPreference

logger = logging.getLogger(__name__)

# Configuration par defaut (fallback si BDD non disponible)
DEFAULT_MAX_AUDIO_DURATION = 60  # Secondes max par requete
DEFAULT_WHISPER_TIMEOUT = 120.0  # Timeout pour la transcription
DEFAULT_LANGUAGE = "fr"


class SpeechService:
    """Service de transcription vocale via container externe."""

    _http_client: httpx.AsyncClient | None = None
    _config_cache: Optional[Dict] = None
    _cache_timestamp: float = 0
    CACHE_TTL = 60  # Refresh config toutes les 60s

    @classmethod
    def _get_whisper_url(cls) -> str:
        """Retourne l'URL du service Whisper interne au réseau Docker."""
        host = getattr(settings, 'whisper_host', 'whisper')
        # Utilise toujours le port 8000 (interne au container whisper)
        # Indépendamment du port exposé sur l'hôte (9001)
        return f"http://{host}:8000"

    @classmethod
    async def _get_client(cls, timeout: float = DEFAULT_WHISPER_TIMEOUT) -> httpx.AsyncClient:
        """Retourne le client HTTP, le crée si nécessaire."""
        if cls._http_client is None or cls._http_client.is_closed:
            cls._http_client = httpx.AsyncClient(timeout=timeout)
        return cls._http_client

    @classmethod
    async def get_config_from_db(cls, db: AsyncSession) -> Dict:
        """
        Recupere la configuration speech depuis la BDD avec cache.
        """
        now = time.time()
        if cls._config_cache and (now - cls._cache_timestamp) < cls.CACHE_TTL:
            return cls._config_cache

        try:
            from app.features.system.service import SystemConfigService
            config_service = SystemConfigService(db)

            enabled = await config_service.get("speech.enabled", True)
            model = await config_service.get("speech.model", "small")
            default_language = await config_service.get("speech.default_language", DEFAULT_LANGUAGE)
            max_duration = await config_service.get("speech.max_duration", DEFAULT_MAX_AUDIO_DURATION)
            timeout = await config_service.get("speech.timeout", DEFAULT_WHISPER_TIMEOUT)

            cls._config_cache = {
                "enabled": bool(enabled),
                "model": str(model),
                "default_language": str(default_language),
                "max_duration": int(max_duration),
                "timeout": int(timeout),
            }
            cls._cache_timestamp = now

            return cls._config_cache

        except Exception as e:
            logger.warning(f"Could not load speech config from DB: {e}, using defaults")
            return {
                "enabled": True,
                "model": "small",
                "default_language": DEFAULT_LANGUAGE,
                "max_duration": DEFAULT_MAX_AUDIO_DURATION,
                "timeout": int(DEFAULT_WHISPER_TIMEOUT),
            }

    @classmethod
    async def is_enabled(cls, db: AsyncSession) -> bool:
        """Verifie si le service speech est active globalement."""
        config = await cls.get_config_from_db(db)
        return config.get("enabled", True)

    @classmethod
    async def get_user_voice_preference(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> Optional[UserPreference]:
        """
        Recupere les preferences vocales de l'utilisateur.

        Args:
            db: Session de base de donnees
            user_id: ID de l'utilisateur

        Returns:
            UserPreference ou None si non trouvees
        """
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    def invalidate_cache(cls) -> None:
        """Invalide le cache de configuration."""
        cls._config_cache = None
        cls._cache_timestamp = 0

    @classmethod
    def is_model_loaded(cls) -> bool:
        """
        Vérifie si le service Whisper est disponible.
        Note: Le modèle est géré par le container, pas localement.
        """
        # Le container gère le modèle, on retourne toujours False
        # car on ne charge rien localement
        return False

    @classmethod
    def force_unload(cls) -> None:
        """
        Force le déchargement du client HTTP.
        Note: Le modèle est géré par le container.
        """
        if cls._http_client is not None:
            # On ne peut pas await dans une méthode sync, on laisse le GC gérer
            cls._http_client = None
            logger.info("HTTP client reference cleared")

    @classmethod
    async def check_health(cls) -> bool:
        """Vérifie que le service Whisper est accessible."""
        try:
            client = await cls._get_client()
            url = f"{cls._get_whisper_url()}/health"
            response = await client.get(url, timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Whisper health check failed: {e}")
            return False

    @classmethod
    async def transcribe(
        cls,
        audio_bytes: bytes,
        filename: str = "audio.webm",
        language: str | None = None,
        db: Optional[AsyncSession] = None
    ) -> Tuple[str, str, float, float]:
        """
        Transcrit un fichier audio en texte via le container Whisper.

        Args:
            audio_bytes: Contenu binaire du fichier audio
            filename: Nom du fichier (pour le content-type)
            language: Code langue ISO (fr, en, etc.) pour forcer la detection
            db: Session DB pour charger la config (optionnel)

        Returns:
            Tuple (text, language, duration, processing_time)

        Raises:
            RuntimeError: Si le service Whisper n'est pas accessible
            ValueError: Si l'audio est invalide
        """
        start_time = time.time()

        # Charger la config depuis la BDD si disponible
        if db:
            config = await cls.get_config_from_db(db)
            max_duration = config.get("max_duration", DEFAULT_MAX_AUDIO_DURATION)
            timeout = float(config.get("timeout", DEFAULT_WHISPER_TIMEOUT))
        else:
            max_duration = DEFAULT_MAX_AUDIO_DURATION
            timeout = DEFAULT_WHISPER_TIMEOUT

        # Determiner le content-type
        content_type = cls._get_content_type(filename)

        try:
            client = await cls._get_client(timeout=timeout)
            url = f"{cls._get_whisper_url()}/v1/audio/transcriptions"

            # Preparer le fichier pour multipart
            files = {
                "file": (filename, audio_bytes, content_type)
            }

            # Parametres optionnels
            data = {
                "response_format": "verbose_json"  # Pour avoir la duree et la langue
            }

            # Forcer la langue si specifiee
            if language:
                data["language"] = language

            logger.debug(f"Sending audio to Whisper: {len(audio_bytes)} bytes, {content_type}, lang={language}, timeout={timeout}s")

            response = await client.post(url, files=files, data=data, timeout=timeout)

            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Whisper API error {response.status_code}: {error_text}")
                raise RuntimeError(f"Whisper transcription failed: {error_text}")

            result = response.json()

            # Extraire les donnees de la reponse
            text = result.get("text", "").strip()
            detected_language = result.get("language", "unknown")
            duration = result.get("duration", 0.0)

            # Verifier la duree
            if duration > max_duration:
                raise ValueError(f"Audio trop long ({duration:.1f}s > {max_duration}s)")

            processing_time = time.time() - start_time

            logger.info(
                f"Transcription completed: {len(text)} chars, "
                f"lang={detected_language}, duration={duration:.1f}s, "
                f"processing={processing_time:.2f}s"
            )

            return text, detected_language, duration, processing_time

        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Whisper service: {e}")
            raise RuntimeError("Service de transcription indisponible (connexion refusée)")
        except httpx.TimeoutException as e:
            logger.error(f"Whisper service timeout: {e}")
            raise RuntimeError("Service de transcription indisponible (timeout)")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise RuntimeError(f"Erreur lors de la transcription: {str(e)}")

    @classmethod
    def _get_content_type(cls, filename: str) -> str:
        """Détermine le content-type basé sur l'extension."""
        ext = filename.lower().split(".")[-1] if "." in filename else "webm"
        content_types = {
            "webm": "audio/webm",
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
            "mp4": "audio/mp4",
        }
        return content_types.get(ext, "audio/webm")

    @classmethod
    async def get_config_async(cls, db: AsyncSession) -> dict:
        """Retourne la configuration du service depuis la BDD, incluant auto-send et TTS."""
        config = await cls.get_config_from_db(db)

        # Charger les clés auto-send et TTS
        try:
            from app.features.system.service import SystemConfigService
            config_service = SystemConfigService(db)

            auto_send_enabled = await config_service.get("speech.auto_send_enabled", True)
            silence_duration_ms = await config_service.get("speech.silence_duration_ms", 1500)
            silence_threshold = await config_service.get("speech.silence_threshold", 0.01)
            tts_enabled = await config_service.get("speech.tts_enabled", True)
            tts_mode = await config_service.get("speech.tts_mode", "native")
            tts_default_rate = await config_service.get("speech.tts_default_rate", 1.0)
        except Exception as e:
            logger.warning(f"Could not load speech voice config: {e}")
            auto_send_enabled = True
            silence_duration_ms = 1500
            silence_threshold = 0.01
            tts_enabled = True
            tts_mode = "native"
            tts_default_rate = 1.0

        return {
            "enabled": config.get("enabled", True),
            "model_loaded": False,  # Modele gere par le container
            "model_name": config.get("model", "small"),
            "max_audio_duration": config.get("max_duration", DEFAULT_MAX_AUDIO_DURATION),
            "service_url": cls._get_whisper_url(),
            "auto_send_enabled": bool(auto_send_enabled),
            "silence_duration_ms": int(silence_duration_ms),
            "silence_threshold": float(silence_threshold),
            "tts_enabled": bool(tts_enabled),
            "tts_mode": str(tts_mode),
            "tts_default_rate": float(tts_default_rate),
        }

    @classmethod
    def get_config(cls) -> dict:
        """Retourne la configuration du service (version sync, valeurs par defaut)."""
        return {
            "enabled": True,
            "model_loaded": False,  # Modele gere par le container
            "model_name": "whisper-container",
            "max_audio_duration": DEFAULT_MAX_AUDIO_DURATION,
            "service_url": cls._get_whisper_url()
        }

    @classmethod
    async def get_default_language(cls, db: AsyncSession) -> str:
        """Retourne la langue par defaut depuis la config."""
        config = await cls.get_config_from_db(db)
        return config.get("default_language", DEFAULT_LANGUAGE)
