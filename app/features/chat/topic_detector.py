"""
Détection de changement de sujet

Compare l'embedding de la question courante avec la moyenne des embeddings
des questions précédentes pour détecter un changement de sujet dans la
conversation. Utilise la similarité cosinus comme mesure.
"""
import logging
import math
from typing import List, Dict, Optional

from app.common.utils.ollama import get_embeddings

logger = logging.getLogger(__name__)

# Seuil par défaut (utilisé si SystemConfig absent)
DEFAULT_SIMILARITY_THRESHOLD = 0.3


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Calcule la similarité cosinus entre deux vecteurs.

    Args:
        vec_a: Premier vecteur
        vec_b: Deuxième vecteur

    Returns:
        Similarité cosinus entre -1 et 1 (1 = identique, 0 = orthogonal)
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def _average_embedding(embeddings: List[List[float]]) -> List[float]:
    """
    Calcule la moyenne de plusieurs vecteurs d'embedding.

    Args:
        embeddings: Liste de vecteurs d'embedding

    Returns:
        Vecteur moyen
    """
    if not embeddings:
        return []

    dim = len(embeddings[0])
    avg = [0.0] * dim
    count = len(embeddings)

    for emb in embeddings:
        for i in range(dim):
            avg[i] += emb[i]

    return [v / count for v in avg]


class TopicDetector:
    """
    Détecte les changements de sujet dans une conversation.

    Compare l'embedding de la question courante avec la moyenne des
    embeddings des questions précédentes (messages user uniquement).
    Si la similarité cosinus est en dessous du seuil, un changement
    de sujet est détecté.
    """

    @staticmethod
    async def is_topic_change(
        current_query: str,
        history: List[Dict[str, str]],
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    ) -> bool:
        """
        Détecte si la question courante change de sujet par rapport à l'historique.

        Args:
            current_query: Question actuelle de l'utilisateur
            history: Historique conversationnel [{"role": "user"|"assistant", "content": "..."}]
            threshold: Seuil de similarité en dessous duquel on détecte un changement

        Returns:
            True si changement de sujet détecté, False sinon
        """
        # Extraire les questions précédentes (messages user uniquement)
        previous_questions = [
            msg["content"] for msg in history
            if msg["role"] == "user"
        ]

        if not previous_questions:
            return False

        try:
            # Générer l'embedding de la question courante
            current_embedding = await get_embeddings(current_query)

            # Générer les embeddings des questions précédentes
            # Limiter à 5 dernières questions pour performance
            recent_questions = previous_questions[-5:]
            question_embeddings = []
            for question in recent_questions:
                emb = await get_embeddings(question)
                question_embeddings.append(emb)

            # Calculer la moyenne des embeddings précédents
            avg_embedding = _average_embedding(question_embeddings)

            # Comparer par similarité cosinus
            similarity = _cosine_similarity(current_embedding, avg_embedding)

            logger.info(
                f"Topic detection: similarity={similarity:.3f}, "
                f"threshold={threshold}, "
                f"topic_changed={similarity < threshold}"
            )

            return similarity < threshold

        except Exception as e:
            logger.warning(f"Error in topic detection, defaulting to no change: {e}")
            return False
