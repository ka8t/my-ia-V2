"""
Factory pour les providers LLM.

Ce module gère l'instanciation et le cycle de vie des providers LLM.
Il fournit une instance singleton configurable via la base de données
(clé llm.provider) avec fallback sur settings.llm_provider.
"""
import logging
from typing import Optional

from app.core.config import settings
from .base import LLMProvider
from .ollama import OllamaProvider
from .llamacpp import LlamaCppProvider

logger = logging.getLogger(__name__)

# Instance singleton du provider actif (chat/génération)
_provider_instance: Optional[LLMProvider] = None

# Provider override (mis à jour par set_provider_override() lors du changement en BDD)
_provider_override: Optional[str] = None

# Instance singleton du provider d'embedding (peut être différent du provider chat)
_embedding_provider_instance: Optional[LLMProvider] = None

# Embedding provider override (si None, utilise le provider principal)
_embedding_provider_override: Optional[str] = None


def set_provider_override(provider_name: str) -> None:
    """
    Définit le provider à utiliser (appelé après mise à jour BDD).

    Args:
        provider_name: "ollama" ou "llamacpp"
    """
    global _provider_override
    _provider_override = provider_name
    logger.info(f"[LLM Factory] Provider override set to: {provider_name}")


def set_embedding_provider_override(provider_name: Optional[str]) -> None:
    """
    Définit le provider d'embedding à utiliser (appelé après mise à jour BDD).

    Args:
        provider_name: "ollama", "llamacpp", ou None (utilise le provider principal)
    """
    global _embedding_provider_override, _embedding_provider_instance
    _embedding_provider_override = provider_name
    _embedding_provider_instance = None  # Reset pour forcer la réinstanciation
    if provider_name:
        logger.info(f"[LLM Factory] Embedding provider override set to: {provider_name}")
    else:
        logger.info("[LLM Factory] Embedding provider override cleared (using main provider)")


def get_provider_name() -> str:
    """
    Retourne le nom du provider configuré.

    Priorité:
    1. _provider_override (défini après changement BDD)
    2. settings.llm_provider (variable d'environnement)
    3. "ollama" (défaut)
    """
    if _provider_override:
        return _provider_override
    return getattr(settings, 'llm_provider', 'ollama')


def get_provider() -> LLMProvider:
    """
    Retourne le provider LLM configuré (singleton).

    Le provider est déterminé par:
    1. _provider_override (si défini via set_provider_override)
    2. settings.llm_provider (variable d'environnement)
    3. "ollama" (défaut)

    Returns:
        Instance du provider LLM

    Raises:
        ValueError: Si le provider configuré est inconnu
    """
    global _provider_instance

    if _provider_instance is None:
        provider_name = get_provider_name()

        if provider_name == "ollama":
            logger.info("[LLM Factory] Initializing Ollama provider")
            _provider_instance = OllamaProvider()

        elif provider_name == "llamacpp":
            logger.info("[LLM Factory] Initializing llama.cpp provider")
            _provider_instance = LlamaCppProvider()

        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        logger.info(f"[LLM Factory] Provider ready: {_provider_instance.provider_name}")

    return _provider_instance


def get_embedding_provider() -> LLMProvider:
    """
    Retourne le provider d'embedding (peut être différent du provider chat).

    Si llm.embedding_provider est configuré, utilise ce provider.
    Sinon, utilise le provider principal (get_provider()).

    Returns:
        Instance du provider pour les embeddings
    """
    global _embedding_provider_instance

    # Si pas de provider d'embedding spécifique, utiliser le provider principal
    if _embedding_provider_override is None:
        return get_provider()

    # Sinon, instancier le provider d'embedding séparé
    if _embedding_provider_instance is None:
        if _embedding_provider_override == "ollama":
            logger.info("[LLM Factory] Initializing Ollama as embedding provider")
            _embedding_provider_instance = OllamaProvider()

        elif _embedding_provider_override == "llamacpp":
            logger.info("[LLM Factory] Initializing llama.cpp as embedding provider")
            _embedding_provider_instance = LlamaCppProvider()

        else:
            raise ValueError(f"Unknown embedding provider: {_embedding_provider_override}")

        logger.info(f"[LLM Factory] Embedding provider ready: {_embedding_provider_instance.provider_name}")

    return _embedding_provider_instance


async def close_provider() -> None:
    """
    Ferme proprement les providers actifs.

    À appeler au shutdown de l'application.
    """
    global _provider_instance, _embedding_provider_instance

    if _provider_instance is not None:
        logger.info(f"[LLM Factory] Closing provider: {_provider_instance.provider_name}")
        await _provider_instance.close()
        _provider_instance = None

    if _embedding_provider_instance is not None:
        logger.info(f"[LLM Factory] Closing embedding provider: {_embedding_provider_instance.provider_name}")
        await _embedding_provider_instance.close()
        _embedding_provider_instance = None


def reset_provider() -> None:
    """
    Réinitialise les providers (utile pour les tests).

    Ne ferme pas les providers existants - utilisez close_provider() d'abord.
    """
    global _provider_instance, _embedding_provider_instance
    _provider_instance = None
    _embedding_provider_instance = None


# ============================================================================
# FONCTIONS DE COMPATIBILITÉ (API legacy)
# ============================================================================
# Ces fonctions maintiennent la compatibilité avec le code existant
# qui importe depuis app.common.utils.ollama

async def get_embeddings(text: str, model: Optional[str] = None) -> list:
    """
    Génère des embeddings (compatibilité avec l'ancienne API).

    Utilise le provider d'embedding configuré (llm.embedding_provider).
    Si non configuré, utilise le provider principal (llm.provider).

    Args:
        text: Texte à vectoriser
        model: Modèle d'embedding (optionnel)

    Returns:
        Liste de floats (embedding normalisé)
    """
    provider = get_embedding_provider()
    response = await provider.get_embeddings(text, model)
    return response.embedding


async def generate_response(
    query: str,
    system_prompt: str,
    context=None,
    stream: bool = False,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    history=None
):
    """
    Génère une réponse LLM (compatibilité avec l'ancienne API).

    Args:
        query: Question de l'utilisateur
        system_prompt: Prompt système
        context: Contexte RAG optionnel
        stream: Mode streaming
        temperature: Température (0-2)
        model: Modèle LLM
        history: Historique conversationnel

    Returns:
        - Si stream=False: str (contenu de la réponse)
        - Si stream=True: AsyncIterator[str]
    """
    provider = get_provider()

    if stream:
        return provider.generate_stream(
            prompt=query,
            system_prompt=system_prompt,
            context=context,
            temperature=temperature,
            model=model,
            history=history
        )
    else:
        response = await provider.generate(
            prompt=query,
            system_prompt=system_prompt,
            context=context,
            temperature=temperature,
            model=model,
            history=history
        )
        return response.content
