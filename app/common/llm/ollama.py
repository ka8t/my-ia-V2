"""
Provider Ollama pour LLM et embeddings.

Implémentation de l'interface LLMProvider utilisant l'API Ollama.
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
# CONFIGURATION OLLAMA DEPUIS BDD
# =============================================================================

@dataclass
class OllamaConfig:
    """Configuration Ollama chargée depuis system_configs."""
    keep_alive: str = "5m"          # Durée avant déchargement modèle
    num_ctx: int = 2048             # Taille contexte en tokens
    num_gpu: int = 999              # Couches GPU (999 = toutes)
    num_parallel: int = 1           # Info seulement (config serveur)
    auto_preload: bool = False      # Précharger modèles au démarrage


# Cache module-level pour la config Ollama
_ollama_config_cache: Tuple[Optional[OllamaConfig], float, float] = (None, 0, 30.0)


async def get_ollama_config(db=None) -> OllamaConfig:
    """
    Récupère la config Ollama depuis BDD avec cache TTL.

    Args:
        db: Session AsyncSession (optionnel, utilise valeurs par défaut si None)

    Returns:
        OllamaConfig avec les valeurs depuis BDD ou défauts
    """
    global _ollama_config_cache

    now = time.time()
    cached_config, cached_time, ttl = _ollama_config_cache

    # Retourner le cache si valide
    if cached_config and ttl > 0 and (now - cached_time) < ttl:
        return cached_config

    # Valeurs par défaut si pas de session DB
    if db is None:
        return OllamaConfig()

    try:
        from app.features.system.service import SystemConfigService
        config_service = SystemConfigService(db)

        config = OllamaConfig(
            keep_alive=str(await config_service.get("llm.ollama.keep_alive", "5m")),
            num_ctx=int(await config_service.get("llm.ollama.num_ctx", 2048)),
            num_gpu=int(await config_service.get("llm.ollama.num_gpu", 999)),
            num_parallel=int(await config_service.get("llm.ollama.num_parallel", 1)),
            auto_preload=str(await config_service.get("llm.ollama.auto_preload", "false")).lower() in ("true", "1", "yes"),
        )

        # Mettre en cache
        _ollama_config_cache = (config, now, 30.0)
        logger.debug(f"[Ollama] Config loaded from DB: keep_alive={config.keep_alive}, num_ctx={config.num_ctx}")
        return config

    except Exception as e:
        logger.warning(f"[Ollama] Failed to load config from DB: {e}, using defaults")
        return OllamaConfig()


def invalidate_ollama_config_cache():
    """Invalide le cache config Ollama (appelé après modification admin)."""
    global _ollama_config_cache
    _ollama_config_cache = (None, 0, 30.0)
    logger.debug("[Ollama] Config cache invalidated")


class OllamaProvider(LLMProvider):
    """
    Provider Ollama pour génération de texte et embeddings.

    Utilise l'API native Ollama:
    - /api/chat pour la génération conversationnelle
    - /api/generate pour la génération simple
    - /api/embeddings pour les embeddings
    - /api/tags pour la liste des modèles
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
        Initialise le provider Ollama.

        Args:
            host: Hôte Ollama (défaut: settings.ollama_host)
            port: Port Ollama (défaut: settings.ollama_port)
            timeout: Timeout HTTP (défaut: settings.ollama_timeout)
            llm_model: Modèle LLM par défaut
            embed_model: Modèle d'embedding par défaut
        """
        self._host = host or settings.ollama_host
        self._port = port or settings.ollama_port
        self._timeout = timeout or settings.ollama_timeout
        self._llm_model = llm_model or settings.llm_model
        self._embed_model = embed_model or settings.embed_model
        self._base_url = f"http://{self._host}:{self._port}"

        # Client HTTP singleton
        self._client: Optional[httpx.AsyncClient] = None

        # Cache embeddings (taille configurable via BDD: perf.embedding_cache_size)
        self._embeddings_cache: Dict[str, List[float]] = {}
        self._cache_max_size = 1000  # Défaut augmenté de 100 à 1000
        self._cache_hits = 0
        self._cache_misses = 0

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

    def _build_system_content(
        self,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Construit le contenu du message system avec contexte RAG."""
        content = system_prompt

        if context:
            content += "\n\n**Contexte disponible :**\n\n"
            for i, ctx in enumerate(context, 1):
                source = ctx.get("metadata", {}).get("source", "Unknown")
                content += f"[Source {i}: {source}]\n{ctx['content']}\n\n"

        return content

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> LLMResponse:
        """Génère une réponse via Ollama (non-streaming)."""
        client = self._get_client()
        llm_model = model or self._llm_model

        # Charger config Ollama depuis cache (BDD)
        ollama_config = await get_ollama_config()

        # Options Ollama (depuis BDD + paramètres)
        ollama_options = {
            "num_ctx": ollama_config.num_ctx,
            "num_gpu": ollama_config.num_gpu,
        }
        if temperature is not None:
            ollama_options["temperature"] = temperature

        # Mode chat avec historique
        if history is not None:
            system_content = self._build_system_content(system_prompt, context)
            messages = [{"role": "system", "content": system_content}]
            messages.extend(history)
            messages.append({"role": "user", "content": prompt})

            logger.info(
                f"[Ollama] Chat request: model={llm_model}, "
                f"temp={temperature}, history={len(history)} messages"
            )

            request_body = {
                "model": llm_model,
                "messages": messages,
                "stream": False,
                "options": ollama_options,
                "keep_alive": ollama_config.keep_alive,
            }

            response = await client.post(
                f"{self._base_url}/api/chat",
                json=request_body,
                timeout=self._timeout
            )
            response.raise_for_status()
            result = response.json()

            return LLMResponse(
                content=result["message"]["content"],
                model=llm_model,
                tokens_used=result.get("eval_count"),
                finish_reason="stop"
            )

        # Mode generate (sans historique)
        full_prompt = system_prompt + "\n\n"
        if context:
            full_prompt += "**Contexte disponible :**\n\n"
            for i, ctx in enumerate(context, 1):
                source = ctx.get("metadata", {}).get("source", "Unknown")
                full_prompt += f"[Source {i}: {source}]\n{ctx['content']}\n\n"
        full_prompt += f"**Question de l'utilisateur :**\n{prompt}\n\n**Réponse :**"

        logger.info(f"[Ollama] Generate request: model={llm_model}, temp={temperature}")

        request_body = {
            "model": llm_model,
            "prompt": full_prompt,
            "stream": False,
            "options": ollama_options,
            "keep_alive": ollama_config.keep_alive,
        }

        response = await client.post(
            f"{self._base_url}/api/generate",
            json=request_body,
            timeout=self._timeout
        )
        response.raise_for_status()
        result = response.json()

        return LLMResponse(
            content=result["response"],
            model=llm_model,
            tokens_used=result.get("eval_count"),
            finish_reason="stop"
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
        """Génère une réponse en streaming via Ollama."""
        client = self._get_client()
        llm_model = model or self._llm_model

        # Charger config Ollama depuis cache (BDD)
        ollama_config = await get_ollama_config()

        # Options Ollama (depuis BDD + paramètres)
        ollama_options = {
            "num_ctx": ollama_config.num_ctx,
            "num_gpu": ollama_config.num_gpu,
        }
        if temperature is not None:
            ollama_options["temperature"] = temperature

        # Mode chat avec historique
        if history is not None:
            system_content = self._build_system_content(system_prompt, context)
            messages = [{"role": "system", "content": system_content}]
            messages.extend(history)
            messages.append({"role": "user", "content": prompt})

            logger.info(f"[Ollama] Stream chat: model={llm_model}, history={len(history)}")

            request_body = {
                "model": llm_model,
                "messages": messages,
                "stream": True,
                "options": ollama_options,
                "keep_alive": ollama_config.keep_alive,
            }

            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=request_body,
                timeout=self._timeout
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
                        if data.get("done"):
                            break
            return

        # Mode generate (sans historique)
        full_prompt = system_prompt + "\n\n"
        if context:
            full_prompt += "**Contexte disponible :**\n\n"
            for i, ctx in enumerate(context, 1):
                source = ctx.get("metadata", {}).get("source", "Unknown")
                full_prompt += f"[Source {i}: {source}]\n{ctx['content']}\n\n"
        full_prompt += f"**Question de l'utilisateur :**\n{prompt}\n\n**Réponse :**"

        logger.info(f"[Ollama] Stream generate: model={llm_model}")

        request_body = {
            "model": llm_model,
            "prompt": full_prompt,
            "stream": True,
            "options": ollama_options,
            "keep_alive": ollama_config.keep_alive,
        }

        async with client.stream(
            "POST",
            f"{self._base_url}/api/generate",
            json=request_body,
            timeout=self._timeout
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    data = json.loads(line)
                    if "response" in data:
                        yield data["response"]
                    if data.get("done"):
                        break

    async def get_embeddings(
        self,
        text: str,
        model: Optional[str] = None
    ) -> EmbeddingResponse:
        """Génère un embedding via Ollama (avec cache)."""
        embed_model = model or self._embed_model

        # Vérifier le cache
        cache_key = self._get_cache_key(text, embed_model)
        cached = self._embeddings_cache.get(cache_key)
        if cached is not None:
            self._cache_hits += 1
            logger.debug(f"[Ollama] Embedding cache hit: {cache_key[:8]} (hits={self._cache_hits})")
            return EmbeddingResponse(
                embedding=cached,
                model=embed_model,
                dimensions=len(cached)
            )

        self._cache_misses += 1

        # Charger config Ollama depuis cache (BDD)
        ollama_config = await get_ollama_config()

        # Appel Ollama avec keep_alive
        client = self._get_client()
        response = await client.post(
            f"{self._base_url}/api/embeddings",
            json={
                "model": embed_model,
                "prompt": text,
                "keep_alive": ollama_config.keep_alive,
            }
        )
        response.raise_for_status()
        embedding = response.json()["embedding"]

        # Normaliser L2 (cohérence avec les documents indexés)
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]

        # Mettre en cache
        self._cache_embedding(cache_key, embedding)
        logger.debug(f"[Ollama] Embedding cached: {cache_key[:8]}")

        return EmbeddingResponse(
            embedding=embedding,
            model=embed_model,
            dimensions=len(embedding)
        )

    async def health_check(self) -> Dict[str, Any]:
        """Vérifie la santé d'Ollama et détecte l'utilisation GPU."""
        try:
            client = self._get_client()
            response = await client.get(
                f"{self._base_url}/api/tags",
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]

            # Détecter l'utilisation GPU
            using_gpu = await self._detect_gpu_usage(client)

            return {
                "status": "healthy",
                "provider": self.provider_name,
                "url": self._base_url,
                "models_available": len(models),
                "models": models,
                "using_gpu": using_gpu
            }
        except Exception as e:
            logger.error(f"[Ollama] Health check failed: {e}")
            return {
                "status": "unhealthy",
                "provider": self.provider_name,
                "url": self._base_url,
                "error": str(e),
                "using_gpu": False
            }

    async def _detect_gpu_usage(self, client: httpx.AsyncClient) -> bool | None:
        """
        Détecte si Ollama utilise le GPU (CUDA, ROCm, ou Metal).

        Stratégie de détection:
        1. Vérifie /api/ps pour les modèles actuellement chargés avec VRAM
        2. Si aucun modèle chargé, fait un mini-test d'embedding pour forcer le chargement
        3. Re-vérifie /api/ps après le test

        Returns:
            True: GPU détecté (VRAM utilisée)
            False: CPU mode (pas de VRAM)
            None: Statut inconnu (erreur de détection)
        """
        # 1. Vérifier les modèles actuellement chargés via /api/ps
        try:
            gpu_status = await self._check_vram_usage(client)
            if gpu_status is not None:
                return gpu_status

            # 2. Aucun modèle chargé - forcer un mini-test pour charger un modèle
            logger.debug("[Ollama] No models loaded, triggering mini-test to detect GPU")

            # Faire un mini embedding pour forcer le chargement du modèle
            try:
                test_response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={
                        "model": self._embed_model,
                        "prompt": "GPU test",
                        "keep_alive": "1m"  # Court pour libérer rapidement
                    },
                    timeout=30.0  # Timeout plus long pour le premier chargement
                )
                if test_response.status_code == 200:
                    # 3. Re-vérifier /api/ps après le chargement
                    gpu_status = await self._check_vram_usage(client)
                    if gpu_status is not None:
                        return gpu_status
            except Exception as e:
                logger.debug(f"[Ollama] Mini-test failed: {e}")

            # Impossible de déterminer
            logger.debug("[Ollama] GPU status unknown after mini-test")
            return None

        except Exception as e:
            logger.debug(f"[Ollama] GPU detection error: {e}")
            return None

    async def _check_vram_usage(self, client: httpx.AsyncClient) -> bool | None:
        """
        Vérifie l'utilisation VRAM via /api/ps.

        Returns:
            True: GPU utilisé (VRAM > 0)
            False: CPU mode (VRAM = 0)
            None: Aucun modèle chargé
        """
        try:
            ps_response = await client.get(
                f"{self._base_url}/api/ps",
                timeout=5.0
            )
            if ps_response.status_code == 200:
                ps_data = ps_response.json()
                models = ps_data.get("models", [])

                if models:
                    for model_info in models:
                        size_vram = model_info.get("size_vram", 0)
                        if size_vram > 0:
                            logger.debug(f"[Ollama] GPU detected via /api/ps (VRAM: {size_vram / 1024 / 1024:.0f} MB)")
                            return True
                    # Modèles chargés mais pas de VRAM → CPU mode
                    logger.debug("[Ollama] CPU mode detected via /api/ps (no VRAM usage)")
                    return False

            return None  # Aucun modèle chargé
        except Exception as e:
            logger.debug(f"[Ollama] Could not check /api/ps: {e}")
            return None

    async def list_models(self) -> List[str]:
        """Liste les modèles disponibles dans Ollama."""
        client = self._get_client()
        response = await client.get(f"{self._base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m["name"] for m in data.get("models", [])]

    async def close(self) -> None:
        """Ferme le client HTTP."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("[Ollama] HTTP client closed")
