"""
Module LLM - Abstraction pour providers LLM (Ollama, llama.cpp).

Ce module fournit une interface unifiée pour interagir avec différents
backends LLM. Le provider actif est déterminé par settings.llm_provider.

Usage:
    from app.common.llm import get_provider, get_embeddings, generate_response

    # API moderne (recommandée)
    provider = get_provider()
    response = await provider.generate(prompt, system_prompt)
    embeddings = await provider.get_embeddings(text)

    # API legacy (compatibilité)
    embeddings = await get_embeddings(text)
    response = await generate_response(query, system_prompt)
"""
from .base import LLMProvider, LLMResponse, EmbeddingResponse
from .factory import (
    get_provider,
    get_embedding_provider,
    close_provider,
    reset_provider,
    set_provider_override,
    set_embedding_provider_override,
    # Fonctions legacy pour compatibilité
    get_embeddings,
    generate_response
)
from .ollama import OllamaProvider, OllamaConfig, get_ollama_config, invalidate_ollama_config_cache
from .llamacpp import LlamaCppProvider, LlamaCppConfig, get_llamacpp_config, invalidate_llamacpp_config_cache

__all__ = [
    # Interface
    "LLMProvider",
    "LLMResponse",
    "EmbeddingResponse",
    # Factory
    "get_provider",
    "get_embedding_provider",
    "close_provider",
    "reset_provider",
    "set_provider_override",
    "set_embedding_provider_override",
    # Legacy API
    "get_embeddings",
    "generate_response",
    # Providers
    "OllamaProvider",
    "LlamaCppProvider",
    # Ollama Config
    "OllamaConfig",
    "get_ollama_config",
    "invalidate_ollama_config_cache",
    # LlamaCpp Config
    "LlamaCppConfig",
    "get_llamacpp_config",
    "invalidate_llamacpp_config_cache",
]
