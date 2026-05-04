"""
Reranking avec cross-encoder léger.

Cross-encoder : prend (query, document) ensemble → score de pertinence.
Plus précis qu'un bi-encoder (embedding séparé) mais plus lent.

Appliqué sur top 20 → garde top 5-8.
Latence cible : < 100ms (sinon désactiver).
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Résultat du reranking."""
    text: str
    score: float
    metadata: Dict[str, Any]
    original_score: float


class LightweightReranker:
    """
    Rerank léger basé sur overlap de mots.

    IMPORTANT - Respect du corpus :
    - Les chunks de corpus DIFFÉRENTS doivent être conservés même si similaires
      (contextes potentiellement différents)
    - La déduplication ne s'applique qu'au sein du MÊME corpus
    """

    def __init__(self, timeout_ms: int = 100, top_k: int = 5):
        """
        Initialise le reranker.

        Args:
            timeout_ms: Timeout max en millisecondes
            top_k: Nombre de résultats après reranking
        """
        self._timeout_ms = timeout_ms
        self._top_k = top_k
        self._enabled = True
        self._total_calls = 0
        self._total_time_ms = 0

    async def reload_config(self, db) -> None:
        """Recharge les paramètres depuis la BDD."""
        try:
            from app.features.system.service import SystemConfigService
            config_service = SystemConfigService(db)

            self._timeout_ms = int(await config_service.get(
                "perf.rerank_timeout_ms", 100
            ))
            self._top_k = int(await config_service.get(
                "perf.rerank_top_k", 5
            ))
            logger.debug(
                f"Reranker config: timeout={self._timeout_ms}ms, top_k={self._top_k}"
            )
        except Exception as e:
            logger.warning(f"Failed to reload reranker config: {e}")

    async def rerank(
        self,
        query: str,
        documents: List[Tuple[str, float, Dict[str, Any]]],
        top_k: Optional[int] = None
    ) -> List[RerankResult]:
        """
        Re-score les documents et retourne les top_k meilleurs.

        Args:
            query: Requête de recherche
            documents: Liste de (text, score, metadata)
            top_k: Nombre de résultats (défaut: self._top_k)

        Returns:
            Liste de RerankResult triée par score décroissant
        """
        if not self._enabled:
            return self._convert_to_results(documents[:top_k or self._top_k])

        effective_top_k = top_k or self._top_k

        if len(documents) <= effective_top_k:
            return self._convert_to_results(documents)

        start_time = time.time()
        query_words = set(query.lower().split())
        scored = []

        for text, original_score, metadata in documents:
            # Vérifier timeout
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > self._timeout_ms:
                logger.warning(
                    f"Rerank timeout after {len(scored)} docs "
                    f"({elapsed_ms:.0f}ms > {self._timeout_ms}ms)"
                )
                break

            # Calcul du score combiné : embedding (70%) + overlap (30%)
            doc_words = set(text.lower().split()[:100])
            overlap = len(query_words & doc_words) / max(len(query_words), 1)
            combined_score = original_score * 0.7 + overlap * 0.3

            scored.append(RerankResult(
                text=text,
                score=combined_score,
                metadata=metadata,
                original_score=original_score
            ))

        # Trier par score décroissant
        scored.sort(key=lambda x: x.score, reverse=True)

        # Stats
        self._total_calls += 1
        self._total_time_ms += (time.time() - start_time) * 1000

        return scored[:effective_top_k]

    def _convert_to_results(
        self,
        documents: List[Tuple[str, float, Dict[str, Any]]]
    ) -> List[RerankResult]:
        """Convertit les tuples en RerankResult."""
        return [
            RerankResult(
                text=text,
                score=score,
                metadata=metadata,
                original_score=score
            )
            for text, score, metadata in documents
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du reranker."""
        avg_time = (
            self._total_time_ms / self._total_calls
            if self._total_calls > 0 else 0
        )
        return {
            "enabled": self._enabled,
            "timeout_ms": self._timeout_ms,
            "top_k": self._top_k,
            "total_calls": self._total_calls,
            "avg_time_ms": round(avg_time, 2)
        }

    def enable(self) -> None:
        """Active le reranker."""
        self._enabled = True
        logger.info("Reranker enabled")

    def disable(self) -> None:
        """Désactive le reranker."""
        self._enabled = False
        logger.info("Reranker disabled")


# Singleton global
reranker = LightweightReranker()
