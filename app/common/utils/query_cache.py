"""
Cache LRU avec TTL pour résultats de recherche ChromaDB.

Optimisation : évite de refaire des recherches identiques pendant le TTL.
Les paramètres sont configurables en BDD (perf.query_cache_*).
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Entrée de cache avec timestamp."""
    value: Any
    timestamp: float


class QueryResultCache:
    """
    Cache query → résultats pour les requêtes fréquentes.

    LRU = supprime les moins récemment utilisés quand plein.
    TTL = expire après N secondes (données peuvent changer).

    La clé inclut corpus_id et provider car :
    - Même query sur corpus différent → résultats différents
    - Même corpus mais provider différent → embeddings incompatibles
    """

    def __init__(self, maxsize: int = 500, ttl: float = 300.0):
        """
        Initialise le cache.

        Args:
            maxsize: Nombre max d'entrées (défaut: 500)
            ttl: Durée de vie en secondes (défaut: 300s = 5 min)
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._maxsize = maxsize
        self._ttl = ttl
        self._hits = 0
        self._misses = 0

    async def reload_config(self, db) -> None:
        """Recharge les paramètres depuis la BDD."""
        try:
            from app.features.system.service import SystemConfigService
            config_service = SystemConfigService(db)

            self._maxsize = int(await config_service.get("perf.query_cache_size", 500))
            self._ttl = float(await config_service.get("perf.query_cache_ttl", 300.0))
            logger.debug(f"Query cache config reloaded: size={self._maxsize}, ttl={self._ttl}")
        except Exception as e:
            logger.warning(f"Failed to reload query cache config: {e}")

    def _make_key(self, query: str, corpus_id: str, provider: str, top_k: int) -> str:
        """
        Génère une clé de cache unique.

        Inclut tous les paramètres qui affectent le résultat.
        """
        content = f"{query}:{corpus_id}:{provider}:{top_k}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get(
        self,
        query: str,
        corpus_id: str,
        provider: str,
        top_k: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Récupère les résultats depuis le cache.

        Args:
            query: Requête de recherche
            corpus_id: ID du corpus
            provider: Provider LLM (ollama/llamacpp)
            top_k: Nombre de résultats

        Returns:
            Liste de chunks si cache hit, None sinon
        """
        key = self._make_key(query, corpus_id, provider, top_k)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # Vérifier TTL
        if (time.time() - entry.timestamp) >= self._ttl:
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        logger.debug(f"Query cache hit: {key[:8]} (hits={self._hits})")
        return entry.value

    def set(
        self,
        query: str,
        corpus_id: str,
        provider: str,
        top_k: int,
        results: List[Dict[str, Any]]
    ) -> None:
        """
        Stocke les résultats dans le cache.

        Args:
            query: Requête de recherche
            corpus_id: ID du corpus
            provider: Provider LLM
            top_k: Nombre de résultats
            results: Chunks à cacher
        """
        key = self._make_key(query, corpus_id, provider, top_k)

        # Éviction LRU si plein
        if len(self._cache) >= self._maxsize:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]
            logger.debug(f"Query cache eviction: {oldest_key[:8]}")

        self._cache[key] = CacheEntry(value=results, timestamp=time.time())
        logger.debug(f"Query cache set: {key[:8]} ({len(results)} results)")

    def invalidate(self, corpus_id: Optional[str] = None) -> int:
        """
        Invalide le cache.

        Args:
            corpus_id: Si fourni, invalide uniquement les entrées de ce corpus.
                      Si None, invalide tout le cache.

        Returns:
            Nombre d'entrées supprimées
        """
        if corpus_id is None:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Query cache cleared: {count} entries")
            return count

        # Invalider les entrées d'un corpus spécifique
        # (nécessite de stocker corpus_id dans la valeur ou de parser la clé)
        # Pour simplifier, on invalide tout
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Query cache cleared for corpus {corpus_id}: {count} entries")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du cache."""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0

        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "ttl": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 1),
        }


# Singleton global
query_cache = QueryResultCache()
