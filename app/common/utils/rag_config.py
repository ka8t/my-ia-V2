"""
Utilitaires Configuration RAG

Helper pour récupérer la configuration RAG depuis la base de données.
Utilisé par chroma.py et ollama.py pour les paramètres dynamiques.

Optimisation : Cache TTL pour éviter 12+ requêtes DB par chat.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache module-level : (config, timestamp, ttl)
_rag_config_cache: Tuple[Optional["RAGConfig"], float, float] = (None, 0, 30.0)


@dataclass
class RAGConfig:
    """Configuration RAG avec valeurs par défaut"""
    top_k: int = 5
    similarity_threshold: float = 0.7
    temperature: float = 0.7
    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunking_strategy: str = "semantic"
    llm_model: str = "mistral"
    embedding_model: str = "nomic-embed-text:latest"
    # Recherche hybride
    min_chunk_length: int = 50
    keyword_boost: float = 0.15
    stopwords_language: str = "fr"
    # Comportement sans sources
    require_sources: bool = False
    # Compaction - Réduction de la redondance des chunks
    compaction_enabled: bool = False
    compaction_similarity_threshold: float = 0.85
    compaction_extract_enabled: bool = False
    compaction_max_sentences: int = 5
    compaction_fetch_multiplier: int = 3


async def get_rag_config(db: Optional[AsyncSession] = None) -> RAGConfig:
    """
    Récupère la configuration RAG depuis la base de données avec cache TTL.

    Optimisation : Cache de 30s (configurable via perf.rag_config_cache_ttl)
    pour éviter 12+ requêtes DB par chat.

    Args:
        db: Session de base de données (optionnel)

    Returns:
        RAGConfig avec les valeurs actuelles
    """
    global _rag_config_cache

    now = time.time()
    cached_config, cached_time, cached_ttl = _rag_config_cache

    # Retourner le cache si valide
    if cached_config and cached_ttl > 0 and (now - cached_time) < cached_ttl:
        logger.debug("RAG config from cache")
        return cached_config

    # Valeurs par défaut depuis settings
    config = RAGConfig(
        top_k=settings.top_k,
        similarity_threshold=0.7,
        temperature=0.2,  # Température basse pour RAG (factuel)
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        chunking_strategy=settings.chunking_strategy,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model
    )

    if db is None:
        return config

    try:
        from app.features.system.service import SystemConfigService
        config_service = SystemConfigService(db)

        # Charger le TTL du cache (lui-même en BDD)
        cache_ttl = float(await config_service.get("perf.rag_config_cache_ttl", 30.0))

        # Bulk loading : charger toutes les clés rag.* en UNE requête
        rag_configs = await config_service.get_by_prefix("rag.")

        # Appliquer les valeurs avec fallback
        config.top_k = int(rag_configs.get("rag.top_k", config.top_k))
        config.similarity_threshold = float(rag_configs.get("rag.similarity_threshold", config.similarity_threshold))
        config.temperature = float(rag_configs.get("rag.temperature", config.temperature))
        config.chunk_size = int(rag_configs.get("rag.chunk_size", config.chunk_size))
        config.chunk_overlap = int(rag_configs.get("rag.chunk_overlap", config.chunk_overlap))
        config.chunking_strategy = str(rag_configs.get("rag.chunking_strategy", config.chunking_strategy))
        config.llm_model = str(rag_configs.get("rag.llm_model", config.llm_model))
        config.embedding_model = str(rag_configs.get("rag.embedding_model", config.embedding_model))

        # Recherche hybride
        config.min_chunk_length = int(rag_configs.get("rag.min_chunk_length", config.min_chunk_length))
        config.keyword_boost = float(rag_configs.get("rag.keyword_boost", config.keyword_boost))
        config.stopwords_language = str(rag_configs.get("rag.stopwords_language", config.stopwords_language))

        # Comportement sans sources
        require_sources_val = rag_configs.get("rag.require_sources", config.require_sources)
        config.require_sources = require_sources_val in (True, "true", "True", 1, "1")

        # Compaction
        compaction_enabled_val = rag_configs.get("rag.compaction.enabled", config.compaction_enabled)
        config.compaction_enabled = compaction_enabled_val in (True, "true", "True", 1, "1")
        config.compaction_similarity_threshold = float(
            rag_configs.get("rag.compaction.similarity_threshold", config.compaction_similarity_threshold)
        )
        compaction_extract_val = rag_configs.get("rag.compaction.extract_enabled", config.compaction_extract_enabled)
        config.compaction_extract_enabled = compaction_extract_val in (True, "true", "True", 1, "1")
        config.compaction_max_sentences = int(
            rag_configs.get("rag.compaction.max_sentences", config.compaction_max_sentences)
        )
        config.compaction_fetch_multiplier = int(
            rag_configs.get("rag.compaction.fetch_multiplier", config.compaction_fetch_multiplier)
        )

        # Mettre en cache
        _rag_config_cache = (config, now, cache_ttl)

        logger.debug(f"RAG config loaded from DB (1 query): top_k={config.top_k}, "
                    f"threshold={config.similarity_threshold}, temp={config.temperature}")

    except Exception as e:
        logger.warning(f"Error loading RAG config from DB, using defaults: {e}")

    return config


def invalidate_rag_config_cache():
    """Invalide le cache - appelé après modification admin."""
    global _rag_config_cache
    _rag_config_cache = (None, 0, 30.0)
    logger.debug("RAG config cache invalidated")


@dataclass
class RAGMode:
    """
    Mode RAG : Fast (latence prioritaire) vs Full (qualité prioritaire).

    Les paramètres sont 100% configurables en BDD sous le préfixe rag.mode.{name}.*
    """
    name: str
    top_k: int
    rerank_enabled: bool
    max_context_tokens: int
    temperature: float


async def get_rag_mode(mode_name: str, db: AsyncSession) -> RAGMode:
    """
    Charge un mode RAG depuis la BDD.

    Modes disponibles :
    - "fast" : Latence prioritaire (top_k=5, no rerank, 1000 tokens)
    - "full" : Qualité prioritaire (top_k=10, rerank, 2500 tokens)

    Args:
        mode_name: Nom du mode ("fast" ou "full")
        db: Session de base de données

    Returns:
        RAGMode avec les paramètres du mode
    """
    from app.features.system.service import SystemConfigService
    config_service = SystemConfigService(db)

    # Préfixe pour les clés de ce mode
    prefix = f"rag.mode.{mode_name}"

    # Valeurs par défaut selon le mode
    defaults = {
        "fast": {"top_k": 5, "rerank_enabled": False, "max_context_tokens": 1000, "temperature": 0.1},
        "full": {"top_k": 10, "rerank_enabled": True, "max_context_tokens": 2500, "temperature": 0.3},
    }
    mode_defaults = defaults.get(mode_name, defaults["full"])

    # Charger les clés du mode
    top_k = int(await config_service.get(f"{prefix}.top_k", mode_defaults["top_k"]))
    rerank_val = await config_service.get(f"{prefix}.rerank_enabled", mode_defaults["rerank_enabled"])
    rerank_enabled = rerank_val in (True, "true", "True", 1, "1")
    max_context_tokens = int(await config_service.get(
        f"{prefix}.max_context_tokens", mode_defaults["max_context_tokens"]
    ))
    temperature = float(await config_service.get(f"{prefix}.temperature", mode_defaults["temperature"]))

    return RAGMode(
        name=mode_name,
        top_k=top_k,
        rerank_enabled=rerank_enabled,
        max_context_tokens=max_context_tokens,
        temperature=temperature
    )


def detect_query_complexity(query: str) -> str:
    """
    Détecte la complexité d'une requête pour choisir le mode RAG automatiquement.

    Logique :
    - Questions courtes (< 10 mots) sans mots-clés de détail → "fast"
    - Questions longues ou contenant des mots-clés de détail → "full"

    Args:
        query: La question de l'utilisateur

    Returns:
        "fast" ou "full"
    """
    # Normaliser la requête
    query_lower = query.lower().strip()
    words = query_lower.split()
    word_count = len(words)

    # Mots-clés indiquant une demande de détails/analyse approfondie
    # Note: "comment" et "how" sont exclus car trop génériques
    detail_keywords_fr = [
        "détail", "détaille", "détaillé", "détailler",
        "explique", "expliquer", "explication",
        "compare", "comparer", "comparaison", "différence",
        "analyse", "analyser", "approfondi", "approfondis",
        "pourquoi", "complètement", "exhaustif",
        "liste", "énumère", "énumérer", "tous les", "toutes les",
        "avantages", "inconvénients", "pros", "cons",
        "comment fonctionne", "comment faire"
    ]

    detail_keywords_en = [
        "detail", "detailed", "explain", "explanation",
        "compare", "comparison", "difference",
        "analyze", "analyse", "analysis", "thorough",
        "why", "completely", "exhaustive",
        "list", "enumerate", "all the", "pros", "cons",
        "advantages", "disadvantages",
        "how does", "how to"
    ]

    all_keywords = detail_keywords_fr + detail_keywords_en

    # Vérifier la présence de mots-clés de détail
    has_detail_keyword = any(kw in query_lower for kw in all_keywords)

    # Question longue (>= 15 mots) ou avec mots-clés de détail → full
    if word_count >= 15 or has_detail_keyword:
        logger.debug(f"Query complexity: full (words={word_count}, detail_kw={has_detail_keyword})")
        return "full"

    # Question courte (< 10 mots) → fast
    if word_count < 10:
        logger.debug(f"Query complexity: fast (words={word_count})")
        return "fast"

    # Par défaut (10-14 mots sans mots-clés) → fast
    logger.debug(f"Query complexity: fast (default, words={word_count})")
    return "fast"


async def get_effective_rag_mode(
    rag_mode: str,
    query: str,
    db: AsyncSession
) -> RAGMode:
    """
    Retourne le mode RAG effectif basé sur le choix utilisateur.

    Args:
        rag_mode: "auto", "fast" ou "full"
        query: La question de l'utilisateur (pour le mode auto)
        db: Session de base de données

    Returns:
        RAGMode avec les paramètres appropriés
    """
    if rag_mode == "auto":
        detected_mode = detect_query_complexity(query)
        logger.info(f"Auto-detected RAG mode: {detected_mode}")
        return await get_rag_mode(detected_mode, db)

    if rag_mode in ("fast", "full"):
        return await get_rag_mode(rag_mode, db)

    # Fallback vers fast si mode inconnu
    logger.warning(f"Unknown RAG mode '{rag_mode}', falling back to 'fast'")
    return await get_rag_mode("fast", db)
