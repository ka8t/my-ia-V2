"""
Utilitaires Ollama - Module de compatibilité

Ce module maintient la rétrocompatibilité avec le code existant.
Toutes les fonctions délèguent au nouveau module app.common.llm.

Migration:
    # Ancien import (fonctionne toujours)
    from app.common.utils.ollama import get_embeddings, generate_response

    # Nouvel import (recommandé)
    from app.common.llm import get_provider, get_embeddings, generate_response
"""
import logging
from typing import List, Dict, Any, Optional

from app.common.llm import (
    get_provider,
    close_provider,
    get_embeddings as _get_embeddings,
    generate_response as _generate_response
)

logger = logging.getLogger(__name__)

# =============================================================================
# FONCTIONS DE COMPATIBILITÉ
# =============================================================================


async def get_embeddings(text: str, model: Optional[str] = None) -> List[float]:
    """
    Génère des embeddings (compatibilité avec l'ancienne API).

    Args:
        text: Texte à transformer en embedding
        model: Nom du modèle d'embedding (fallback sur settings.embed_model)

    Returns:
        Liste de floats représentant l'embedding normalisé (L2 norm = 1)
    """
    return await _get_embeddings(text, model)


async def generate_response(
    query: str,
    system_prompt: str,
    context: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    temperature: Optional[float] = None,
    model: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None
):
    """
    Génère une réponse via le provider LLM configuré.

    Args:
        query: Question de l'utilisateur
        system_prompt: Prompt système
        context: Contexte RAG optionnel
        stream: Mode streaming ou non
        temperature: Température du LLM (0-2)
        model: Nom du modèle LLM (fallback sur settings.llm_model)
        history: Historique conversationnel optionnel

    Returns:
        - Si stream=False: str (contenu de la réponse)
        - Si stream=True: AsyncIterator[str] (chunks de texte)
    """
    return await _generate_response(
        query=query,
        system_prompt=system_prompt,
        context=context,
        stream=stream,
        temperature=temperature,
        model=model,
        history=history
    )


async def close_http_client():
    """
    Ferme le client HTTP du provider (compatibilité).

    Délègue à close_provider() du nouveau module.
    """
    await close_provider()


def get_http_client():
    """
    Retourne le client HTTP du provider actif (compatibilité).

    Note: Cette fonction est dépréciée. Utilisez get_provider() directement.
    """
    provider = get_provider()
    return provider._get_client()
