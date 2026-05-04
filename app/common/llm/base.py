"""
Interface abstraite pour les fournisseurs LLM.

Ce module définit le contrat que doivent respecter tous les providers LLM
(Ollama, llama.cpp, etc.) pour garantir l'interchangeabilité.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Réponse standardisée d'un LLM."""
    content: str
    model: str
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None


@dataclass
class EmbeddingResponse:
    """Réponse standardisée pour les embeddings."""
    embedding: List[float]
    model: str
    dimensions: int


class LLMProvider(ABC):
    """
    Interface abstraite pour les fournisseurs LLM.

    Tous les providers (Ollama, llama.cpp) doivent implémenter cette interface
    pour garantir la compatibilité avec le reste de l'application.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> LLMResponse:
        """
        Génère une réponse textuelle (mode non-streaming).

        Args:
            prompt: Question de l'utilisateur
            system_prompt: Prompt système
            context: Contexte RAG optionnel [{content, metadata}, ...]
            temperature: Température (0-2)
            model: Modèle à utiliser (fallback sur config)
            history: Historique conversationnel [{role, content}, ...]

        Returns:
            LLMResponse avec le contenu généré
        """
        pass

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: str,
        context: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> AsyncIterator[str]:
        """
        Génère une réponse en streaming (SSE).

        Args:
            prompt: Question de l'utilisateur
            system_prompt: Prompt système
            context: Contexte RAG optionnel
            temperature: Température (0-2)
            model: Modèle à utiliser
            history: Historique conversationnel

        Yields:
            Chunks de texte au fur et à mesure
        """
        pass

    @abstractmethod
    async def get_embeddings(
        self,
        text: str,
        model: Optional[str] = None
    ) -> EmbeddingResponse:
        """
        Génère un vecteur d'embedding pour un texte.

        Args:
            text: Texte à vectoriser
            model: Modèle d'embedding (fallback sur config)

        Returns:
            EmbeddingResponse avec le vecteur normalisé (L2 norm = 1)
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Vérifie la santé du provider.

        Returns:
            Dict avec status, version, models disponibles, etc.
        """
        pass

    @abstractmethod
    async def list_models(self) -> List[str]:
        """
        Liste les modèles disponibles.

        Returns:
            Liste des noms de modèles
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Ferme proprement les connexions du provider.
        À appeler au shutdown de l'application.
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Nom du provider (ollama, llamacpp)."""
        pass
