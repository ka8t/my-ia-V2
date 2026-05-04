"""
Service Health Check

Logique métier pour vérifier l'état des services.
"""
import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.common.utils.rag_config import get_rag_config
from app.common.llm import get_provider

logger = logging.getLogger(__name__)


class HealthService:
    """Service pour vérifier la santé des composants système"""

    @staticmethod
    async def check_llm() -> dict:
        """
        Vérifie si le provider LLM est accessible.

        Utilise le provider configuré (ollama ou llamacpp).

        Returns:
            Dict avec status et détails du provider
        """
        try:
            provider = get_provider()
            return await provider.health_check()
        except Exception as e:
            logger.warning(f"LLM health check failed: {e}")
            return {
                "status": "unhealthy",
                "provider": settings.llm_provider,
                "error": str(e)
            }

    @staticmethod
    async def check_ollama() -> bool:
        """
        Vérifie si Ollama est accessible (rétrocompatibilité).

        Returns:
            True si Ollama répond correctement
        """
        try:
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.get(f"{settings.ollama_url}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    @staticmethod
    async def check_chroma() -> bool:
        """
        Vérifie si ChromaDB est accessible

        Returns:
            True si ChromaDB répond correctement
        """
        try:
            async with httpx.AsyncClient(timeout=settings.health_check_timeout) as client:
                response = await client.get(f"{settings.chroma_url}/api/v2/heartbeat")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"ChromaDB health check failed: {e}")
            return False

    @staticmethod
    async def get_health_status(db: AsyncSession) -> dict:
        """
        Vérifie l'état de tous les services

        Args:
            db: Session de base de données pour récupérer la config

        Returns:
            Dictionnaire avec l'état de chaque service
        """
        llm_health = await HealthService.check_llm()
        chroma_healthy = await HealthService.check_chroma()

        llm_healthy = llm_health.get("status") == "healthy"
        status = "healthy" if (llm_healthy and chroma_healthy) else "degraded"

        # Récupère le modèle LLM configuré dans le backoffice
        try:
            rag_config = await get_rag_config(db)
            model = rag_config.llm_model
        except Exception as e:
            logger.warning(f"Failed to get RAG config, using default: {e}")
            model = settings.llm_model

        return {
            "status": status,
            "llm": llm_health,
            "chroma": chroma_healthy,
            "model": model,
            # Rétrocompatibilité: garde "ollama" pour les anciens clients
            "ollama": llm_healthy,
            # Info GPU pour avertissement performances
            "using_gpu": llm_health.get("using_gpu", False)
        }
