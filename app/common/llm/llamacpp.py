"""
Provider llama.cpp pour LLM et embeddings.

Implémentation de l'interface LLMProvider utilisant l'API OpenAI-compatible
de llama-server (llama.cpp).
Configuration chargée depuis BDD (system_configs).
"""
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, AsyncIterator, Tuple

import httpx

from app.core.config import settings
from .base import LLMProvider, LLMResponse, EmbeddingResponse

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION LLAMA.CPP DEPUIS BDD
# =============================================================================

@dataclass
class LlamaCppConfig:
    """Configuration llama.cpp chargée depuis system_configs."""
    host: str = "host.docker.internal"  # Hôte llama-server (depuis Docker)
    port: int = 8085                     # Port llama-server
    ctx_size: int = 4096                 # Taille contexte (tokens)
    batch_size: int = 2048               # Taille batch prompt
    gpu_layers: int = 99                 # Couches sur GPU (99 = toutes)
    parallel: int = -1                   # Slots parallèles (-1 = auto)
    threads: int = -1                    # Threads CPU (-1 = auto)
    mmap: bool = True                    # Memory-mapped model
    mlock: bool = False                  # Lock model in RAM
    flash_attn: str = "auto"             # Flash attention (auto, on, off)
    embedding_mode: bool = True          # Activer endpoint /v1/embeddings
    metrics_enabled: bool = True         # Activer endpoint /metrics
    llm_model: str = ""                  # Fichier modèle GGUF
    embedding_model: str = ""            # Fichier modèle embedding


# Cache module-level pour la config llama.cpp
_llamacpp_config_cache: Tuple[Optional[LlamaCppConfig], float, float] = (None, 0, 30.0)


async def get_llamacpp_config(db=None) -> LlamaCppConfig:
    """
    Récupère la config llama.cpp depuis BDD avec cache TTL.

    Args:
        db: Session AsyncSession (optionnel, utilise valeurs par défaut si None)

    Returns:
        LlamaCppConfig avec les valeurs depuis BDD ou défauts
    """
    global _llamacpp_config_cache

    now = time.time()
    cached_config, cached_time, ttl = _llamacpp_config_cache

    # Retourner le cache si valide
    if cached_config and ttl > 0 and (now - cached_time) < ttl:
        return cached_config

    # Valeurs par défaut si pas de session DB
    if db is None:
        return LlamaCppConfig()

    try:
        from app.features.system.service import SystemConfigService
        config_service = SystemConfigService(db)

        config = LlamaCppConfig(
            host=str(await config_service.get("llm.llamacpp.host", "host.docker.internal")),
            port=int(await config_service.get("llm.llamacpp.port", 8085)),
            ctx_size=int(await config_service.get("llm.llamacpp.ctx_size", 4096)),
            batch_size=int(await config_service.get("llm.llamacpp.batch_size", 2048)),
            gpu_layers=int(await config_service.get("llm.llamacpp.gpu_layers", 99)),
            parallel=int(await config_service.get("llm.llamacpp.parallel", -1)),
            threads=int(await config_service.get("llm.llamacpp.threads", -1)),
            mmap=str(await config_service.get("llm.llamacpp.mmap", "true")).lower() in ("true", "1", "yes"),
            mlock=str(await config_service.get("llm.llamacpp.mlock", "false")).lower() in ("true", "1", "yes"),
            flash_attn=str(await config_service.get("llm.llamacpp.flash_attn", "auto")),
            embedding_mode=str(await config_service.get("llm.llamacpp.embedding_mode", "true")).lower() in ("true", "1", "yes"),
            metrics_enabled=str(await config_service.get("llm.llamacpp.metrics_enabled", "true")).lower() in ("true", "1", "yes"),
            llm_model=str(await config_service.get("llm.llamacpp.llm_model", "")),
            embedding_model=str(await config_service.get("llm.llamacpp.embedding_model", "")),
        )

        # Mettre en cache
        _llamacpp_config_cache = (config, now, 30.0)
        logger.debug(f"[llama.cpp] Config loaded from DB: host={config.host}:{config.port}, ctx_size={config.ctx_size}")
        return config

    except Exception as e:
        logger.warning(f"[llama.cpp] Failed to load config from DB: {e}, using defaults")
        return LlamaCppConfig()


def invalidate_llamacpp_config_cache():
    """Invalide le cache config llama.cpp (appelé après modification admin)."""
    global _llamacpp_config_cache
    _llamacpp_config_cache = (None, 0, 30.0)
    logger.debug("[llama.cpp] Config cache invalidated")


class LlamaCppProvider(LLMProvider):
    """
    Provider llama.cpp pour génération de texte et embeddings.

    Utilise l'API OpenAI-compatible de llama-server:
    - /v1/chat/completions pour la génération
    - /v1/embeddings pour les embeddings
    - /health pour le health check
    - /v1/models pour la liste des modèles

    Architecture:
    - L'application tourne dans Docker
    - llama-server tourne en natif sur l'hôte (accès GPU Metal)
    - Communication via host.docker.internal
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: Optional[float] = None,
        llm_model: Optional[str] = None,
        embed_model: Optional[str] = None
    ):
        """
        Initialise le provider llama.cpp.

        Args:
            host: Hôte llama-server (défaut: depuis BDD ou host.docker.internal)
            port: Port llama-server (défaut: depuis BDD ou 8085)
            timeout: Timeout HTTP (défaut: settings.ollama_timeout)
            llm_model: Modèle LLM par défaut
            embed_model: Modèle d'embedding par défaut
        """
        # Valeurs initiales (seront surchargées par config BDD si disponible)
        self._host = host or getattr(settings, 'llamacpp_host', 'host.docker.internal')
        self._port = port or getattr(settings, 'llamacpp_port', 8085)
        self._timeout = timeout or settings.ollama_timeout
        self._llm_model = llm_model or getattr(settings, 'llamacpp_model', settings.llm_model)
        self._embed_model = embed_model or getattr(settings, 'llamacpp_embed_model', settings.embed_model)

        # Client HTTP singleton
        self._client: Optional[httpx.AsyncClient] = None

        # Cache embeddings
        self._embeddings_cache: Dict[str, List[float]] = {}
        self._cache_max_size = 100

    async def _get_base_url(self) -> str:
        """
        Retourne l'URL de base depuis la config BDD (avec cache).

        La config est chargée depuis le cache TTL ou les valeurs par défaut.
        Le cache est alimenté par les appels avec session DB depuis les services.
        """
        config = await get_llamacpp_config()
        return f"http://{config.host}:{config.port}"

    async def _get_config(self) -> LlamaCppConfig:
        """Retourne la config llama.cpp depuis le cache."""
        return await get_llamacpp_config()

    def _get_client(self) -> httpx.AsyncClient:
        """Retourne le client HTTP (lazy init)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5
                )
            )
        return self._client

    def _get_cache_key(self, text: str, model: str) -> str:
        """Génère une clé de cache pour un embedding."""
        content = f"{model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _cache_embedding(self, key: str, embedding: List[float]) -> None:
        """Ajoute un embedding au cache avec éviction LRU."""
        if len(self._embeddings_cache) >= self._cache_max_size:
            oldest_key = next(iter(self._embeddings_cache))
            del self._embeddings_cache[oldest_key]
        self._embeddings_cache[key] = embedding

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> List[Dict[str, str]]:
        """
        Construit la liste des messages pour l'API chat/completions.

        Format OpenAI: [{"role": "system|user|assistant", "content": "..."}]
        """
        # Message système avec contexte RAG
        system_content = system_prompt
        if context:
            system_content += "\n\n**Contexte disponible :**\n\n"
            for i, ctx in enumerate(context, 1):
                source = ctx.get("metadata", {}).get("source", "Unknown")
                system_content += f"[Source {i}: {source}]\n{ctx['content']}\n\n"

        messages = [{"role": "system", "content": system_content}]

        # Historique conversationnel
        if history:
            messages.extend(history)

        # Question courante
        messages.append({"role": "user", "content": prompt})

        return messages

    @property
    def provider_name(self) -> str:
        return "llamacpp"

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> LLMResponse:
        """Génère une réponse via llama.cpp (non-streaming)."""
        client = self._get_client()
        base_url = await self._get_base_url()
        llm_model = model or self._llm_model

        messages = self._build_messages(prompt, system_prompt, context, history)

        logger.info(
            f"[llama.cpp] Chat request: model={llm_model}, "
            f"temp={temperature}, messages={len(messages)}"
        )

        request_body = {
            "model": llm_model,
            "messages": messages,
            "stream": False
        }
        if temperature is not None:
            request_body["temperature"] = temperature

        response = await client.post(
            f"{base_url}/v1/chat/completions",
            json=request_body,
            timeout=self._timeout
        )
        response.raise_for_status()
        result = response.json()

        choice = result["choices"][0]
        usage = result.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=result.get("model", llm_model),
            tokens_used=usage.get("total_tokens"),
            finish_reason=choice.get("finish_reason", "stop")
        )

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncIterator[str]:
        """Génère une réponse en streaming via llama.cpp (SSE)."""
        client = self._get_client()
        base_url = await self._get_base_url()
        llm_model = model or self._llm_model

        messages = self._build_messages(prompt, system_prompt, context, history)

        logger.info(f"[llama.cpp] Stream chat: model={llm_model}, messages={len(messages)}")

        request_body = {
            "model": llm_model,
            "messages": messages,
            "stream": True
        }
        if temperature is not None:
            request_body["temperature"] = temperature

        async with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            json=request_body,
            timeout=self._timeout
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                # Format SSE: "data: {...}" ou "data: [DONE]"
                if line.startswith("data: "):
                    data_str = line[6:]  # Retirer "data: "
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue

    async def get_embeddings(
        self,
        text: str,
        model: Optional[str] = None
    ) -> EmbeddingResponse:
        """Génère un embedding via llama.cpp (avec cache)."""
        embed_model = model or self._embed_model

        # Vérifier le cache
        cache_key = self._get_cache_key(text, embed_model)
        cached = self._embeddings_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"[llama.cpp] Embedding cache hit: {cache_key[:8]}")
            return EmbeddingResponse(
                embedding=cached,
                model=embed_model,
                dimensions=len(cached)
            )

        # Appel llama-server (API OpenAI-compatible)
        client = self._get_client()
        base_url = await self._get_base_url()
        response = await client.post(
            f"{base_url}/v1/embeddings",
            json={
                "model": embed_model,
                "input": text
            }
        )
        response.raise_for_status()
        result = response.json()

        # Format OpenAI: {"data": [{"embedding": [...]}]}
        embedding = result["data"][0]["embedding"]

        # Normaliser L2 pour cohérence avec ChromaDB
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]

        # Mettre en cache
        self._cache_embedding(cache_key, embedding)
        logger.debug(f"[llama.cpp] Embedding cached: {cache_key[:8]}")

        return EmbeddingResponse(
            embedding=embedding,
            model=embed_model,
            dimensions=len(embedding)
        )

    async def health_check(self) -> Dict[str, Any]:
        """Vérifie la santé de llama-server."""
        # Compter les modèles GGUF disponibles
        models_available = self._count_gguf_models()
        base_url = await self._get_base_url()

        # Déterminer si GPU est utilisé (gpu_layers > 0)
        config = await get_llamacpp_config()
        using_gpu = config.gpu_layers > 0 if config else True  # Assume GPU si config indisponible

        try:
            client = self._get_client()
            response = await client.get(
                f"{base_url}/health",
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()

            return {
                "status": "healthy" if data.get("status") == "ok" else "degraded",
                "provider": self.provider_name,
                "url": base_url,
                "slots_idle": data.get("slots_idle", 0),
                "slots_processing": data.get("slots_processing", 0),
                "models_available": models_available,
                "model_loaded": self._llm_model,
                "using_gpu": using_gpu
            }
        except Exception as e:
            logger.error(f"[llama.cpp] Health check failed: {e}")
            return {
                "status": "unhealthy",
                "provider": self.provider_name,
                "url": base_url,
                "error": str(e),
                "models_available": models_available,
                "using_gpu": False
            }

    def _count_gguf_models(self) -> int:
        """Compte les fichiers GGUF dans le dossier models/gguf."""
        from pathlib import Path
        models_dir = Path("models/gguf")
        if not models_dir.exists():
            return 0
        return len(list(models_dir.glob("**/*.gguf")))

    async def list_models(self) -> List[str]:
        """Liste les modèles disponibles (llama-server = 1 modèle chargé)."""
        try:
            client = self._get_client()
            base_url = await self._get_base_url()
            response = await client.get(f"{base_url}/v1/models")
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            # llama-server peut ne pas supporter /v1/models
            return [self._llm_model]

    async def close(self) -> None:
        """Ferme le client HTTP."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("[llama.cpp] HTTP client closed")
