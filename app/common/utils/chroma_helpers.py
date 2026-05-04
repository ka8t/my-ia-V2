"""
Helpers pour les opérations ChromaDB.

Centralise la gestion des erreurs "collection not found"
lors des opérations de suppression et nettoyage.
"""
import logging

logger = logging.getLogger(__name__)


def is_chroma_not_found(error: Exception) -> bool:
    """Vérifie si une erreur ChromaDB est de type 'collection not found'."""
    return "does not exist" in str(error).lower()


def safe_chroma_delete(chroma_client, collection_name: str) -> bool:
    """
    Supprime une collection ChromaDB de manière sûre.

    Ignore silencieusement si la collection n'existe pas.

    Args:
        chroma_client: Client ChromaDB
        collection_name: Nom de la collection à supprimer

    Returns:
        True si supprimée, False si déjà absente

    Raises:
        RuntimeError: Si l'erreur n'est pas un "not found"
    """
    try:
        chroma_client.delete_collection(name=collection_name)
        logger.info(f"ChromaDB collection supprimée: {collection_name}")
        return True
    except Exception as e:
        if is_chroma_not_found(e):
            logger.info(f"ChromaDB collection {collection_name} déjà absente")
            return False
        logger.error(f"Échec suppression ChromaDB pour {collection_name}: {e}")
        raise RuntimeError(
            f"ChromaDB delete failed for collection {collection_name}: {e}"
        ) from e


def safe_chroma_clear(chroma_client, collection_name: str) -> int:
    """
    Supprime tous les documents d'une collection ChromaDB sans la supprimer.

    Ignore silencieusement si la collection n'existe pas.

    Args:
        chroma_client: Client ChromaDB
        collection_name: Nom de la collection à vider

    Returns:
        Nombre de chunks supprimés (0 si collection absente)

    Raises:
        RuntimeError: Si l'erreur n'est pas un "not found"
    """
    try:
        chroma_coll = chroma_client.get_collection(name=collection_name)
        all_docs = chroma_coll.get()
        if all_docs.get("ids"):
            count = len(all_docs["ids"])
            chroma_coll.delete(ids=all_docs["ids"])
            logger.info(f"ChromaDB: {count} chunks supprimés de {collection_name}")
            return count
        return 0
    except Exception as e:
        if is_chroma_not_found(e):
            logger.info(f"ChromaDB collection {collection_name} déjà absente")
            return 0
        logger.error(f"Échec clear ChromaDB pour {collection_name}: {e}")
        raise RuntimeError(
            f"ChromaDB clear failed for collection {collection_name}: {e}"
        ) from e


def clear_chunks_by_filter(
    chroma_client,
    collection_name: str,
    where_filter: dict,
    provider: str = None
) -> int:
    """
    Supprime les chunks d'une collection ChromaDB selon un filtre.

    Supporte l'architecture multi-provider en ajoutant le suffixe au nom.

    Args:
        chroma_client: Client ChromaDB
        collection_name: Nom de base de la collection
        where_filter: Filtre ChromaDB (ex: {"document_hash": "xxx"})
        provider: Provider optionnel ("ollama", "llamacpp") pour suffixer le nom

    Returns:
        Nombre de chunks supprimés (0 si collection absente ou rien à supprimer)
    """
    # Construire le nom avec suffixe provider si fourni
    full_name = f"{collection_name}_{provider}" if provider else collection_name

    try:
        chroma_coll = chroma_client.get_collection(name=full_name)
        # Récupérer les IDs correspondant au filtre
        results = chroma_coll.get(where=where_filter)
        if results.get("ids"):
            count = len(results["ids"])
            chroma_coll.delete(ids=results["ids"])
            logger.info(f"ChromaDB {full_name}: {count} chunks supprimés (filtre: {where_filter})")
            return count
        return 0
    except Exception as e:
        if is_chroma_not_found(e):
            logger.debug(f"ChromaDB collection {full_name} absente")
            return 0
        logger.warning(f"Erreur clear ChromaDB {full_name}: {e}")
        return 0


def clear_document_chunks(
    chroma_client,
    collection_name: str,
    document_hash: str,
    all_providers: bool = True
) -> int:
    """
    Supprime les chunks d'un document spécifique de ChromaDB.

    Args:
        chroma_client: Client ChromaDB
        collection_name: Nom de base de la collection
        document_hash: Hash du document à supprimer
        all_providers: Si True, supprime de toutes les collections provider

    Returns:
        Nombre total de chunks supprimés
    """
    if not document_hash:
        return 0

    where_filter = {"document_hash": document_hash}
    total = 0

    if all_providers:
        for provider in ["ollama", "llamacpp"]:
            total += clear_chunks_by_filter(chroma_client, collection_name, where_filter, provider)
    else:
        total += clear_chunks_by_filter(chroma_client, collection_name, where_filter)

    return total


def clear_source_chunks(
    chroma_client,
    source_name: str,
    all_providers: bool = True
) -> int:
    """
    Supprime les chunks d'une source externe de ChromaDB.

    Les sources sont stockées dans la collection 'external_sources_{provider}'.

    Args:
        chroma_client: Client ChromaDB
        source_name: Nom de la source
        all_providers: Si True, supprime de toutes les collections provider

    Returns:
        Nombre total de chunks supprimés
    """
    if not source_name:
        return 0

    where_filter = {"source_name": source_name}
    total = 0

    if all_providers:
        for provider in ["ollama", "llamacpp"]:
            total += clear_chunks_by_filter(chroma_client, "external_sources", where_filter, provider)
    else:
        total += clear_chunks_by_filter(chroma_client, "external_sources", where_filter)

    return total


def clear_collection_all_providers(chroma_client, collection_name: str) -> int:
    """
    Vide une collection pour tous les providers.

    Args:
        chroma_client: Client ChromaDB
        collection_name: Nom de base de la collection

    Returns:
        Nombre total de chunks supprimés
    """
    total = 0
    for provider in ["ollama", "llamacpp"]:
        full_name = f"{collection_name}_{provider}"
        total += safe_chroma_clear(chroma_client, full_name)
    return total
