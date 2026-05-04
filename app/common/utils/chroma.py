"""
Utilitaires ChromaDB

Fonctions helpers pour interagir avec ChromaDB (recherche de contexte).
"""
import logging
from typing import List, Dict, Any, Optional, Set, TypedDict
from uuid import UUID

from app.core.config import settings
from app.core.deps import get_chroma_client
from app.common.utils.ollama import get_embeddings
from app.common.utils.rag_config import get_rag_config

logger = logging.getLogger(__name__)


class SearchDiagnostics(TypedDict):
    """Diagnostics de la recherche RAG"""
    total_found: int              # Resultats bruts ChromaDB
    filtered_by_threshold: int    # Filtres par seuil similarite
    filtered_by_length: int       # Filtres par longueur minimale
    final_count: int              # Resultats finaux
    similarity_threshold: float   # Seuil utilise
    collection_name: str          # Collection cible
    has_documents: bool           # Collection non vide


# Stopwords par langue pour l'extraction de mots-clés
STOPWORDS = {
    "fr": {
        "le", "la", "les", "un", "une", "des", "du", "de", "ce", "cette", "ces",
        "qui", "que", "quoi", "quel", "quelle", "quels", "quelles",
        "est", "sont", "être", "avoir", "fait", "faire",
        "pour", "par", "sur", "avec", "dans", "sans", "sous",
        "mais", "ou", "et", "donc", "car", "ni", "comme",
        "je", "tu", "il", "elle", "nous", "vous", "ils", "elles", "on",
        "mon", "ton", "son", "ma", "ta", "sa", "mes", "tes", "ses",
        "notre", "votre", "leur", "nos", "vos", "leurs",
        "moi", "toi", "lui", "elle", "soi", "eux",
        "ceci", "cela", "ça", "tout", "tous", "toute", "toutes",
        "quelque", "quelques", "chaque", "autre", "autres",
        "ici", "là", "où", "quand", "comment", "pourquoi",
        "plus", "moins", "très", "bien", "mal", "peu", "beaucoup", "trop",
        "aussi", "encore", "toujours", "jamais", "déjà", "souvent",
        "oui", "non", "peut", "être", "doit", "faut",
    },
    "en": {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
        "be", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "must", "shall", "can",
        "this", "that", "these", "those", "it", "its", "they", "them", "their",
        "he", "she", "him", "her", "his", "hers", "i", "me", "my", "we", "us",
        "you", "your", "who", "what", "which", "where", "when", "why", "how",
        "all", "each", "every", "both", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
        "very", "just", "also", "now", "here", "there", "then", "once",
    },
    "none": set(),  # Pas de filtrage
}

# Synonymes numériques pour améliorer le matching
NUMBER_SYNONYMS = {
    "100": ["cent", "centaine"],
    "10": ["dix", "dizaine"],
    "1000": ["mille", "millier"],
}


def _extract_keywords(query: str, stopwords_language: str = "fr") -> set:
    """
    Extrait les mots-clés significatifs d'une requête.

    Args:
        query: Requête utilisateur
        stopwords_language: Langue des stopwords (fr/en/none)

    Returns:
        Set de mots-clés significatifs
    """
    import re
    # Normaliser et tokeniser (inclut les nombres)
    words = re.findall(r'\b[a-zA-ZÀ-ÿ0-9]{2,}\b', query.lower())

    # Récupérer les stopwords pour la langue
    stopwords = STOPWORDS.get(stopwords_language, STOPWORDS["fr"])

    # Filtrer les stopwords
    keywords = {w for w in words if w not in stopwords}

    # Ajouter les synonymes numériques
    expanded = set(keywords)
    for kw in keywords:
        if kw in NUMBER_SYNONYMS:
            expanded.update(NUMBER_SYNONYMS[kw])

    return expanded


class SearchResult(TypedDict):
    """Resultat de recherche avec diagnostics"""
    context: List[Dict[str, Any]]
    diagnostics: SearchDiagnostics


async def get_provider_collection_name(
    base_name: str,
    db_session = None
) -> str:
    """
    Retourne le nom de collection suffixé avec le provider LLM actif.

    Chaque provider (ollama, llamacpp) utilise des modèles d'embedding différents
    qui produisent des vecteurs incompatibles. Les collections sont donc séparées
    pour éviter les problèmes de dimension mismatch.

    Args:
        base_name: Nom de base de la collection (ex: "external_sources")
        db_session: Session DB pour lire le provider actif (optionnel)

    Returns:
        Nom suffixé (ex: "external_sources_ollama")
    """
    from app.features.system.service import SystemConfigService

    provider = settings.llm_provider  # Défaut depuis settings

    if db_session:
        try:
            config_service = SystemConfigService(db_session)
            provider = await config_service.get("llm.provider", provider)
        except Exception as e:
            logger.warning(f"Could not read provider from DB, using default: {e}")

    return f"{base_name}_{provider}"


async def get_indexed_document_hashes(db_session) -> Set[str]:
    """
    Recupere les hashes des documents indexes (is_indexed=True) depuis PostgreSQL

    Args:
        db_session: Session SQLAlchemy async

    Returns:
        Set des file_hash des documents indexes
    """
    from sqlalchemy import select
    from app.models import Document

    try:
        result = await db_session.execute(
            select(Document.file_hash).where(Document.is_indexed == True)
        )
        return {row[0] for row in result.fetchall()}
    except Exception as e:
        logger.error(f"Error fetching indexed document hashes: {e}")
        return set()


async def search_context(
    query: str,
    top_k: Optional[int] = None,
    user_id: Optional[str] = None,
    db_session = None,
    collection_name: Optional[str] = None,
    similarity_threshold: Optional[float] = None
) -> SearchResult:
    """
    Recherche de contexte dans ChromaDB avec filtrage par visibilite

    Logique de visibilite:
    - Documents "public" : accessibles a tous
    - Documents "private" : accessibles uniquement au proprietaire (user_id)
    - Documents non indexes (is_indexed=False) : exclus de la recherche

    Args:
        query: Question de l'utilisateur
        top_k: Nombre de resultats a retourner (defaut: depuis BDD ou settings.top_k)
        user_id: UUID de l'utilisateur connecte (pour filtrer les docs prives)
        db_session: Session DB pour verifier is_indexed et charger config RAG
        collection_name: Nom de la collection ChromaDB cible (defaut: settings.collection_name)
        similarity_threshold: Seuil de similarite minimum (defaut: depuis BDD ou 0.7)

    Returns:
        SearchResult avec contexte et diagnostics
    """
    # Valeurs par defaut pour les diagnostics en cas d'erreur
    empty_result: SearchResult = {
        "context": [],
        "diagnostics": {
            "total_found": 0,
            "filtered_by_threshold": 0,
            "filtered_by_length": 0,
            "final_count": 0,
            "similarity_threshold": similarity_threshold or 0.7,
            "collection_name": collection_name or settings.collection_name,
            "has_documents": False,
            "error": None,
            "error_type": None
        }
    }

    try:
        # Charger la config RAG depuis la BDD
        rag_config = await get_rag_config(db_session)

        if top_k is None:
            top_k = rag_config.top_k

        if similarity_threshold is None:
            similarity_threshold = rag_config.similarity_threshold

        chroma_client = get_chroma_client()
        if chroma_client is None:
            logger.error("ChromaDB client not initialized")
            return empty_result

        # Générer l'embedding de la query avec le modèle depuis la config
        query_embedding = await get_embeddings(query, model=rag_config.embedding_model)

        # Recuperer la collection (suffixée avec le provider actif, fallback sur nom de base)
        base_collection = collection_name or settings.collection_name
        target_collection = await get_provider_collection_name(base_collection, db_session)
        collection = None
        try:
            collection = chroma_client.get_collection(name=target_collection)
        except Exception:
            # Fallback: essayer le nom de base (collections existantes sans suffix)
            try:
                collection = chroma_client.get_collection(name=base_collection)
                target_collection = base_collection  # Utiliser le nom réel pour les diagnostics
                logger.debug(f"Using legacy collection '{base_collection}' (no provider suffix)")
            except Exception as e:
                logger.error(f"Collection '{target_collection}' not found: {e}")
                empty_result["diagnostics"]["collection_name"] = target_collection
                return empty_result

        # Verifier si la collection a des documents
        collection_count = collection.count()
        has_documents = collection_count > 0

        # Construire le filtre de visibilite pour ChromaDB
        # On recupere beaucoup plus de resultats pour compenser:
        # 1. Les chunks courts (noms de societes) qui polluent les resultats haut
        # 2. Les noms propres mal geres par l'embedding qui se retrouvent en bas
        # Le fetch est limite par le nombre total de documents dans la collection
        min_fetch = min(collection_count, 500)  # Max 500 ou taille collection
        fetch_count = max(top_k * 50, min_fetch)  # 50x le top_k demande

        # Filtre ChromaDB: public OU (private ET meme user)
        where_filter = None
        if user_id:
            # User connecte: voir public + ses propres documents prives
            where_filter = {
                "$or": [
                    {"visibility": "public"},
                    {"$and": [
                        {"visibility": "private"},
                        {"user_id": user_id}
                    ]}
                ]
            }
        else:
            # Pas de user: uniquement public
            where_filter = {"visibility": "public"}

        # Recherche dans ChromaDB avec filtre
        # Inclure les embeddings pour permettre la déduplication sémantique (compaction)
        try:
            results_data = collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_count,
                where=where_filter,
                include=["documents", "metadatas", "distances", "embeddings"]
            )
        except Exception as e:
            # Fallback sans filtre si erreur (documents legacy sans visibility)
            logger.warning(f"Query with filter failed, fallback without filter: {e}")
            results_data = collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_count,
                include=["documents", "metadatas", "distances", "embeddings"]
            )

        # Recuperer les documents indexes si db_session fournie
        indexed_hashes = None
        if db_session:
            indexed_hashes = await get_indexed_document_hashes(db_session)

        # Extraire les mots-clés de la requête pour boost hybride
        query_keywords = _extract_keywords(query, rag_config.stopwords_language)
        logger.debug(f"Query keywords (lang={rag_config.stopwords_language}): {query_keywords}")

        candidates = []  # Tous les candidats valides (avant selection top_k)
        filtered_by_threshold = 0
        filtered_by_length = 0

        # Compter le total de resultats bruts
        total_found = len(results_data.get("documents", [[]])[0]) if results_data.get("documents") else 0

        if results_data.get("documents") and results_data["documents"][0]:
            for i, doc in enumerate(results_data["documents"][0]):
                metadata = results_data.get("metadatas", [[]])[0][i] if results_data.get("metadatas") else {}
                distance = results_data.get("distances", [[]])[0][i] if results_data.get("distances") else None

                # Filtrer par longueur minimale (exclut les chunks trop courts)
                if len(doc) < rag_config.min_chunk_length:
                    filtered_by_length += 1
                    continue  # Chunk trop court, pas de valeur informationnelle

                # Filtrer par seuil de similarite
                # ChromaDB cosine distance: 0 = identique, 2 = oppose
                # Conversion: similarity = 1 - (distance / 2)
                if distance is not None:
                    similarity = 1 - (distance / 2)
                    if similarity < similarity_threshold:
                        filtered_by_threshold += 1
                        continue  # Score trop bas, on ignore

                # Filtrer par is_indexed si on a la session DB
                if indexed_hashes is not None:
                    doc_hash = metadata.get("document_hash")
                    if doc_hash and doc_hash not in indexed_hashes:
                        continue  # Document desindexe, on l'ignore

                # Verifier la visibilite (double check)
                visibility = metadata.get("visibility", "public")
                doc_user_id = metadata.get("user_id")

                if visibility == "private" and doc_user_id != user_id:
                    continue  # Document prive d'un autre user

                # Calculer le boost par mots-clés (recherche hybride)
                keyword_boost = 0.0
                if query_keywords and rag_config.keyword_boost > 0:
                    doc_lower = doc.lower()
                    matching_keywords = sum(1 for kw in query_keywords if kw in doc_lower)
                    if matching_keywords > 0:
                        # Boost proportionnel au nombre de mots-clés trouvés
                        keyword_boost = rag_config.keyword_boost * (matching_keywords / len(query_keywords))

                base_similarity = 1 - (distance / 2) if distance is not None else 0.5
                boosted_similarity = min(1.0, base_similarity + keyword_boost)  # Cap à 1.0

                # Inclure l'embedding pour la déduplication sémantique (compaction)
                embedding = None
                if results_data.get("embeddings") and len(results_data["embeddings"]) > 0 and len(results_data["embeddings"][0]) > i:
                    embedding = results_data["embeddings"][0][i]

                candidates.append({
                    "content": doc,
                    "metadata": metadata,
                    "distance": distance,
                    "similarity": base_similarity,
                    "boosted_similarity": boosted_similarity,
                    "keyword_boost": keyword_boost,
                    "embedding": embedding,
                    "score": boosted_similarity  # Alias pour le compactor
                })

        # Trier par similarité boostée (hybride semantique + mots-cles)
        candidates.sort(key=lambda x: x["boosted_similarity"], reverse=True)

        # Prendre les top_k meilleurs
        results = candidates[:top_k]

        # Log si boost applique
        boosted_count = sum(1 for r in results if r.get("keyword_boost", 0) > 0)
        if boosted_count > 0:
            logger.info(f"Keyword boost applied to {boosted_count}/{len(results)} results")

        logger.info(f"Found {len(results)} context results for query "
                   f"(user_id={user_id}, threshold={similarity_threshold}, "
                   f"filtered_threshold={filtered_by_threshold}, filtered_length={filtered_by_length})")

        return {
            "context": results,
            "diagnostics": {
                "total_found": total_found,
                "filtered_by_threshold": filtered_by_threshold,
                "filtered_by_length": filtered_by_length,
                "final_count": len(results),
                "similarity_threshold": similarity_threshold,
                "collection_name": target_collection,
                "has_documents": has_documents
            }
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error searching context: {error_msg}")
        empty_result["diagnostics"]["error"] = error_msg
        if "dimension" in error_msg.lower():
            empty_result["diagnostics"]["error_type"] = "dimension_mismatch"
        else:
            empty_result["diagnostics"]["error_type"] = "search_error"
        return empty_result


async def get_corpus_collection_names(db_session, corpus_id: UUID) -> List[str]:
    """
    Recupere les noms des collections ChromaDB associees a un corpus.

    Utilise la table pivot corpus_collections pour la relation N-to-N.

    Args:
        db_session: Session SQLAlchemy async
        corpus_id: UUID du corpus

    Returns:
        Liste des noms de collections ChromaDB, ordonnee par priorite
    """
    from sqlalchemy import select
    from app.models import Collection, CorpusCollection

    try:
        result = await db_session.execute(
            select(Collection.name)
            .join(CorpusCollection, CorpusCollection.collection_id == Collection.id)
            .where(CorpusCollection.corpus_id == corpus_id)
            .order_by(CorpusCollection.priority)
        )
        return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching corpus collections: {e}")
        return []


async def search_corpus_context(
    query: str,
    corpus_id: UUID,
    top_k: Optional[int] = None,
    user_id: Optional[str] = None,
    db_session=None,
    similarity_threshold: Optional[float] = None
) -> SearchResult:
    """
    Recherche de contexte dans toutes les collections d'un corpus.

    Quand rag.use_corpus=true et qu'une collection a un corpus assigne,
    cette fonction cherche dans TOUTES les collections du corpus et
    fusionne les resultats par similarite.

    Args:
        query: Question de l'utilisateur
        corpus_id: UUID du corpus cible
        top_k: Nombre total de resultats a retourner
        user_id: UUID de l'utilisateur (filtrage docs prives)
        db_session: Session DB obligatoire (pour recuperer les collections)
        similarity_threshold: Seuil de similarite minimum

    Returns:
        SearchResult avec contexte fusionne et diagnostics agreges
    """
    if not db_session:
        logger.error("db_session required for corpus search")
        return {
            "context": [],
            "diagnostics": {
                "total_found": 0,
                "filtered_by_threshold": 0,
                "filtered_by_length": 0,
                "final_count": 0,
                "similarity_threshold": similarity_threshold or 0.7,
                "collection_name": f"corpus:{corpus_id}",
                "has_documents": False,
                "error": "db_session required",
                "error_type": "config_error"
            }
        }

    # Charger config RAG
    rag_config = await get_rag_config(db_session)
    if top_k is None:
        top_k = rag_config.top_k
    if similarity_threshold is None:
        similarity_threshold = rag_config.similarity_threshold

    # Recuperer les collections du corpus
    collection_names = await get_corpus_collection_names(db_session, corpus_id)

    if not collection_names:
        logger.warning(f"No collections found for corpus {corpus_id}")
        return {
            "context": [],
            "diagnostics": {
                "total_found": 0,
                "filtered_by_threshold": 0,
                "filtered_by_length": 0,
                "final_count": 0,
                "similarity_threshold": similarity_threshold,
                "collection_name": f"corpus:{corpus_id}",
                "has_documents": False,
                "corpus_collections": []
            }
        }

    logger.info(f"Corpus search: {len(collection_names)} collections for corpus {corpus_id}")

    # Chercher dans chaque collection (top_k * 2 par collection pour avoir assez de candidats)
    all_candidates = []
    total_found = 0
    filtered_by_threshold = 0
    filtered_by_length = 0
    has_documents = False
    errors = []

    for coll_name in collection_names:
        try:
            result = await search_context(
                query=query,
                top_k=top_k * 2,  # Plus de resultats par collection
                user_id=user_id,
                db_session=db_session,
                collection_name=coll_name,
                similarity_threshold=similarity_threshold
            )

            # Agreger les diagnostics
            diag = result["diagnostics"]
            total_found += diag.get("total_found", 0)
            filtered_by_threshold += diag.get("filtered_by_threshold", 0)
            filtered_by_length += diag.get("filtered_by_length", 0)
            if diag.get("has_documents"):
                has_documents = True
            if diag.get("error"):
                errors.append(f"{coll_name}: {diag['error']}")

            # Ajouter les resultats avec la collection source
            for ctx in result["context"]:
                ctx["metadata"]["corpus_collection"] = coll_name
                all_candidates.append(ctx)

        except Exception as e:
            logger.error(f"Error searching collection {coll_name}: {e}")
            errors.append(f"{coll_name}: {str(e)}")

    # Trier tous les candidats par similarite boostee
    all_candidates.sort(key=lambda x: x.get("boosted_similarity", x.get("similarity", 0)), reverse=True)

    # Prendre les top_k meilleurs
    final_results = all_candidates[:top_k]

    logger.info(f"Corpus search complete: {len(final_results)} results from {len(collection_names)} collections")

    return {
        "context": final_results,
        "diagnostics": {
            "total_found": total_found,
            "filtered_by_threshold": filtered_by_threshold,
            "filtered_by_length": filtered_by_length,
            "final_count": len(final_results),
            "similarity_threshold": similarity_threshold,
            "collection_name": f"corpus:{corpus_id}",
            "has_documents": has_documents,
            "corpus_collections": collection_names,
            "errors": errors if errors else None
        }
    }
