"""
Service de statistiques de timing pour le monitoring des performances.

Stocke les métriques en mémoire avec calcul d'agrégats (min, max, avg, p95).
"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from threading import Lock

logger = logging.getLogger(__name__)

# Nombre max d'échantillons conservés par métrique
MAX_SAMPLES = 1000


@dataclass
class MetricSample:
    """Un échantillon de timing"""
    value_ms: int
    timestamp: float


@dataclass
class MetricStats:
    """Statistiques agrégées pour une métrique"""
    count: int = 0
    min_ms: int = 0
    max_ms: int = 0
    avg_ms: float = 0.0
    p50_ms: int = 0  # Médiane - 50% des requêtes plus rapides
    p95_ms: int = 0  # 95% des requêtes plus rapides (capture outliers)
    last_ms: int = 0
    samples_kept: int = 0


class TimingStatsService:
    """
    Service singleton pour collecter et agréger les statistiques de timing.

    Thread-safe avec verrou pour les opérations d'écriture.
    """

    _instance: Optional['TimingStatsService'] = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._metrics: Dict[str, deque] = {}
        self._total_counts: Dict[str, int] = {}
        self._data_lock = Lock()
        self._initialized = True
        logger.info("TimingStatsService initialized")

    def record(self, metric_name: str, value_ms: int) -> None:
        """
        Enregistre une valeur de timing pour une métrique.

        Args:
            metric_name: Nom de la métrique (ex: "chat.total", "chat.chroma")
            value_ms: Valeur en millisecondes
        """
        with self._data_lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = deque(maxlen=MAX_SAMPLES)
                self._total_counts[metric_name] = 0

            self._metrics[metric_name].append(MetricSample(
                value_ms=value_ms,
                timestamp=time.time()
            ))
            self._total_counts[metric_name] += 1

    def record_batch(self, timings: Dict[str, int], prefix: str = "") -> None:
        """
        Enregistre plusieurs métriques en une fois.

        Args:
            timings: Dictionnaire {nom: valeur_ms}
            prefix: Préfixe à ajouter aux noms (ex: "chat.")
        """
        for name, value in timings.items():
            if value is not None and value >= 0:
                full_name = f"{prefix}{name}" if prefix else name
                self.record(full_name, value)

    def get_stats(self, metric_name: str) -> MetricStats:
        """
        Calcule les statistiques pour une métrique.

        Args:
            metric_name: Nom de la métrique

        Returns:
            MetricStats avec min, max, avg, p95, etc.
        """
        with self._data_lock:
            if metric_name not in self._metrics or not self._metrics[metric_name]:
                return MetricStats()

            samples = list(self._metrics[metric_name])
            values = [s.value_ms for s in samples]
            values_sorted = sorted(values)

            count = self._total_counts.get(metric_name, len(values))

            # Calcul des percentiles P50 (médiane) et P95
            n = len(values_sorted)
            p50_index = int(n * 0.50)
            p95_index = int(n * 0.95)
            p50 = values_sorted[min(p50_index, n - 1)]
            p95 = values_sorted[min(p95_index, n - 1)]

            return MetricStats(
                count=count,
                min_ms=min(values),
                max_ms=max(values),
                avg_ms=round(sum(values) / len(values), 1),
                p50_ms=p50,
                p95_ms=p95,
                last_ms=values[-1],
                samples_kept=len(values)
            )

    def get_all_stats(self) -> Dict[str, Dict]:
        """
        Retourne les statistiques de toutes les métriques.

        Returns:
            Dictionnaire {metric_name: stats_dict}
        """
        with self._data_lock:
            metric_names = list(self._metrics.keys())

        result = {}
        for name in metric_names:
            stats = self.get_stats(name)
            result[name] = {
                "count": stats.count,
                "min_ms": stats.min_ms,
                "max_ms": stats.max_ms,
                "avg_ms": stats.avg_ms,
                "p50_ms": stats.p50_ms,
                "p95_ms": stats.p95_ms,
                "last_ms": stats.last_ms,
                "samples_kept": stats.samples_kept
            }

        return result

    def get_summary(self) -> Dict:
        """
        Retourne un résumé des performances.

        Returns:
            Dictionnaire avec résumé global et par catégorie
        """
        all_stats = self.get_all_stats()

        # Grouper par catégorie (préfixe avant le premier point)
        categories = {}
        for name, stats in all_stats.items():
            parts = name.split(".")
            category = parts[0] if len(parts) > 1 else "other"
            metric = parts[1] if len(parts) > 1 else parts[0]

            if category not in categories:
                categories[category] = {}
            categories[category][metric] = stats

        # Calculer le total si disponible
        total_stats = all_stats.get("chat.pre_llm", {})

        return {
            "total_requests": total_stats.get("count", 0),
            "avg_pre_llm_ms": total_stats.get("avg_ms", 0),
            "p50_pre_llm_ms": total_stats.get("p50_ms", 0),
            "p95_pre_llm_ms": total_stats.get("p95_ms", 0),
            "categories": categories,
            "metrics": all_stats
        }

    def reset(self) -> None:
        """Réinitialise toutes les statistiques."""
        with self._data_lock:
            self._metrics.clear()
            self._total_counts.clear()
        logger.info("TimingStatsService reset")

    def reset_metric(self, metric_name: str) -> bool:
        """
        Réinitialise une métrique spécifique.

        Args:
            metric_name: Nom de la métrique à réinitialiser

        Returns:
            True si la métrique existait, False sinon
        """
        with self._data_lock:
            if metric_name in self._metrics:
                del self._metrics[metric_name]
                del self._total_counts[metric_name]
                return True
            return False


# Instance singleton globale
timing_stats = TimingStatsService()
