"""
Service ChromaDB pour les collections

Fonctions utilitaires pour gérer les collections ChromaDB.
Séparé de deps.py pour éviter les imports circulaires.
"""
import logging
from typing import Optional

import chromadb
from chromadb.config import Settings

from app.core.config import settings

logger = logging.getLogger(__name__)

# Client ChromaDB singleton
_chroma_client: Optional[chromadb.HttpClient] = None


def get_chroma_client() -> Optional[chromadb.HttpClient]:
    """
    Retourne le client ChromaDB (singleton).
    Initialise la connexion si nécessaire.
    """
    global _chroma_client

    if _chroma_client is None:
        try:
            _chroma_client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info(f"ChromaDB client connected to {settings.chroma_host}:{settings.chroma_port}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB client: {e}")
            return None

    return _chroma_client


def create_user_collection(user_id: str, provider: Optional[str] = None) -> bool:
    """
    Crée la collection privée ChromaDB pour un utilisateur.

    La collection est suffixée avec le provider LLM actif pour éviter
    les conflits de dimension entre embeddings de providers différents.

    Args:
        user_id: UUID de l'utilisateur
        provider: Provider LLM (optionnel, défaut depuis settings)

    Returns:
        True si créée avec succès, False sinon
    """
    effective_provider = provider or settings.llm_provider
    collection_name = f"user_{user_id}_{effective_provider}"

    try:
        client = get_chroma_client()
        if client:
            client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "type": "private",
                    "owner_id": user_id,
                    "provider": effective_provider,
                    "hnsw:space": "cosine",           # Distance cosine pour similarité
                    "hnsw:M": 16,                     # Connexions par noeud
                    "hnsw:construction_ef": 100,      # Qualité construction index
                    "hnsw:search_ef": 50              # Qualité recherche (équilibre)
                }
            )
            logger.info(f"ChromaDB collection created: {collection_name}")
            return True
    except Exception as e:
        logger.error(f"Error creating ChromaDB collection {collection_name}: {e}")

    return False


def delete_user_collection(user_id: str, provider: Optional[str] = None, all_providers: bool = True) -> None:
    """
    Supprime la collection privée ChromaDB d'un utilisateur.

    Par défaut, supprime les collections de TOUS les providers pour assurer
    un nettoyage complet. Si all_providers=False, supprime uniquement la
    collection du provider spécifié ou actif.

    Args:
        user_id: UUID de l'utilisateur
        provider: Provider LLM spécifique (optionnel)
        all_providers: Si True, supprime les collections de tous les providers

    Raises:
        RuntimeError: Si le client ChromaDB est indisponible ou si la suppression échoue
    """
    providers_to_delete = ["ollama", "llamacpp"] if all_providers else [provider or settings.llm_provider]

    client = get_chroma_client()
    if client is None:
        raise RuntimeError("ChromaDB client unavailable")

    for prov in providers_to_delete:
        collection_name = f"user_{user_id}_{prov}"
        try:
            client.delete_collection(name=collection_name)
            logger.info(f"ChromaDB collection deleted: {collection_name}")
        except Exception as e:
            # Collection inexistante = état désiré atteint, pas d'erreur
            error_msg = str(e).lower()
            if "does not exist" in error_msg or isinstance(e, ValueError):
                logger.debug(f"ChromaDB collection {collection_name} already absent")
            else:
                raise
