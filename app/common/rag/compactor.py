"""
Token Compactor - Compactage de contexte RAG

Réduit la redondance entre les chunks pour envoyer plus d'information
au LLM sans saturer le contexte.

Algorithme :
1. Déduplication sémantique : éliminer les chunks quasi-identiques (même corpus)
2. Extraction de phrases clés (optionnel) : garder les phrases les plus pertinentes

Usage:
    compactor = TokenCompactor(config)
    compacted = await compactor.compact(chunks, query)
"""
import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    """Configuration du compactage"""
    enabled: bool = False
    similarity_threshold: float = 0.85
    extract_enabled: bool = False
    max_sentences: int = 5
    min_chunks_for_compaction: int = 3


@dataclass
class CompactionStats:
    """Statistiques de compactage pour les logs/métriques"""
    input_chunks: int
    output_chunks: int
    input_tokens_estimate: int
    output_tokens_estimate: int
    duplicates_removed: int

    @property
    def reduction_percent(self) -> float:
        if self.input_chunks == 0:
            return 0.0
        return (1 - self.output_chunks / self.input_chunks) * 100


class TokenCompactor:
    """
    Compacte les chunks RAG pour maximiser l'information
    tout en minimisant les tokens.
    """

    # Estimation moyenne : 1 token ≈ 4 caractères en français
    CHARS_PER_TOKEN = 4

    def __init__(self, config: CompactionConfig):
        self.config = config
        self._stats: Optional[CompactionStats] = None

    @property
    def stats(self) -> Optional[CompactionStats]:
        """Retourne les statistiques du dernier compactage"""
        return self._stats

    async def compact(
        self,
        chunks: List[Dict[str, Any]],
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Pipeline de compactage principal.

        Args:
            chunks: Liste de chunks avec 'content', 'metadata', optionnel 'embedding'
            query: Question utilisateur (pour l'extraction de phrases)

        Returns:
            Liste de chunks compactés
        """
        if not self.config.enabled:
            logger.debug("Compaction disabled, returning original chunks")
            return chunks

        if len(chunks) < self.config.min_chunks_for_compaction:
            logger.debug(f"Too few chunks ({len(chunks)}) for compaction, skipping")
            return chunks

        input_count = len(chunks)
        input_tokens = self._estimate_tokens(chunks)

        logger.info(f"[Compactor] Starting: {input_count} chunks, ~{input_tokens} tokens")

        # Étape 1 : Déduplication sémantique
        unique_chunks = await self._deduplicate(chunks)
        duplicates_removed = input_count - len(unique_chunks)

        # Étape 2 : Extraction de phrases clés (optionnel)
        if self.config.extract_enabled and query:
            unique_chunks = await self._extract_key_content(unique_chunks, query)

        output_tokens = self._estimate_tokens(unique_chunks)

        # Enregistrer les stats
        self._stats = CompactionStats(
            input_chunks=input_count,
            output_chunks=len(unique_chunks),
            input_tokens_estimate=input_tokens,
            output_tokens_estimate=output_tokens,
            duplicates_removed=duplicates_removed
        )

        logger.info(
            f"[Compactor] Done: {input_count} -> {len(unique_chunks)} chunks "
            f"(~{input_tokens} -> ~{output_tokens} tokens, "
            f"-{self._stats.reduction_percent:.1f}%)"
        )

        return unique_chunks

    def _estimate_tokens(self, chunks: List[Dict[str, Any]]) -> int:
        """Estime le nombre de tokens dans les chunks"""
        total_chars = sum(len(c.get("content", "")) for c in chunks)
        return total_chars // self.CHARS_PER_TOKEN

    async def _deduplicate(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Supprime les chunks dont le contenu est trop similaire.

        Règles :
        - Même corpus : on peut dédupliquer si similarité > seuil
        - Corpus différents : on garde les deux même si similaires

        Algorithme :
        1. Grouper les chunks par corpus_id
        2. Pour chaque groupe, calculer la similarité entre paires
        3. Garder le chunk avec le meilleur score RAG si doublon
        """
        if not chunks:
            return []

        # Vérifier si les embeddings sont disponibles
        has_embeddings = all("embedding" in c for c in chunks)

        if not has_embeddings:
            # Fallback : déduplication par contenu textuel exact
            return self._deduplicate_by_content(chunks)

        # Grouper par corpus_id
        corpus_groups: Dict[str, List[Dict]] = {}
        for chunk in chunks:
            corpus_id = chunk.get("metadata", {}).get("corpus_id", "default")
            if corpus_id not in corpus_groups:
                corpus_groups[corpus_id] = []
            corpus_groups[corpus_id].append(chunk)

        unique_chunks = []

        for corpus_id, group_chunks in corpus_groups.items():
            if len(group_chunks) == 1:
                unique_chunks.append(group_chunks[0])
                continue

            # Dédupliquer au sein du groupe
            group_unique = self._deduplicate_group(group_chunks)
            unique_chunks.extend(group_unique)

        # Trier par score RAG décroissant
        unique_chunks.sort(
            key=lambda c: c.get("score", c.get("metadata", {}).get("score", 0)),
            reverse=True
        )

        return unique_chunks

    def _deduplicate_group(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Déduplique un groupe de chunks du même corpus.

        Utilise la similarité cosinus entre embeddings.
        """
        if len(chunks) <= 1:
            return chunks

        # Extraire les embeddings
        embeddings = []
        for chunk in chunks:
            emb = chunk.get("embedding")
            if emb is not None:
                embeddings.append(np.array(emb))
            else:
                # Si pas d'embedding, utiliser un vecteur nul
                embeddings.append(np.zeros(768))

        embeddings = np.array(embeddings)

        # Normaliser pour le calcul de similarité cosinus
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Éviter division par zéro
        embeddings_norm = embeddings / norms

        # Calculer la matrice de similarité
        similarity_matrix = np.dot(embeddings_norm, embeddings_norm.T)

        # Marquer les chunks à garder
        n = len(chunks)
        keep = [True] * n

        for i in range(n):
            if not keep[i]:
                continue
            for j in range(i + 1, n):
                if not keep[j]:
                    continue

                similarity = similarity_matrix[i, j]

                if similarity > self.config.similarity_threshold:
                    # Garder celui avec le meilleur score
                    score_i = chunks[i].get("score", 0)
                    score_j = chunks[j].get("score", 0)

                    if score_i >= score_j:
                        keep[j] = False
                        logger.debug(
                            f"Removed duplicate chunk (sim={similarity:.3f}): "
                            f"keeping score={score_i:.3f}, removing score={score_j:.3f}"
                        )
                    else:
                        keep[i] = False
                        logger.debug(
                            f"Removed duplicate chunk (sim={similarity:.3f}): "
                            f"keeping score={score_j:.3f}, removing score={score_i:.3f}"
                        )
                        break  # i est marqué comme supprimé, passer au suivant

        return [c for c, k in zip(chunks, keep) if k]

    def _deduplicate_by_content(
        self,
        chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Fallback : déduplication par contenu textuel (hash).

        Utilisé quand les embeddings ne sont pas disponibles.
        """
        seen_content = set()
        unique = []

        for chunk in chunks:
            content = chunk.get("content", "")
            # Normaliser le contenu (minuscules, espaces)
            content_key = " ".join(content.lower().split())

            if content_key not in seen_content:
                seen_content.add(content_key)
                unique.append(chunk)
            else:
                logger.debug(f"Removed exact duplicate chunk: {content[:50]}...")

        return unique

    async def _extract_key_content(
        self,
        chunks: List[Dict[str, Any]],
        query: str
    ) -> List[Dict[str, Any]]:
        """
        Extrait les phrases les plus informatives de chaque chunk.

        Algorithme simplifié (sans dépendance NLP lourde) :
        1. Découper le chunk en phrases
        2. Scorer chaque phrase par rapport à la query (mots communs)
        3. Garder les N meilleures phrases

        Note: Phase 2 - peut être amélioré avec TF-IDF ou TextRank.
        """
        import re

        query_words = set(query.lower().split())

        compacted = []

        for chunk in chunks:
            content = chunk.get("content", "")

            # Découper en phrases (simple regex)
            sentences = re.split(r'[.!?]+\s+', content)
            sentences = [s.strip() for s in sentences if s.strip()]

            if len(sentences) <= self.config.max_sentences:
                # Pas besoin de compacter
                compacted.append(chunk)
                continue

            # Scorer les phrases
            scored_sentences = []
            for sentence in sentences:
                sentence_words = set(sentence.lower().split())
                overlap = len(query_words & sentence_words)
                scored_sentences.append((overlap, sentence))

            # Garder les meilleures phrases
            scored_sentences.sort(reverse=True, key=lambda x: x[0])
            best_sentences = [s for _, s in scored_sentences[:self.config.max_sentences]]

            # Reconstruire le contenu compacté
            compacted_content = ". ".join(best_sentences)
            if not compacted_content.endswith("."):
                compacted_content += "."

            # Créer le chunk compacté
            compacted_chunk = chunk.copy()
            compacted_chunk["content"] = compacted_content
            compacted_chunk["metadata"] = chunk.get("metadata", {}).copy()
            compacted_chunk["metadata"]["compacted"] = True
            compacted_chunk["metadata"]["original_length"] = len(content)

            compacted.append(compacted_chunk)

            logger.debug(
                f"Extracted {self.config.max_sentences} sentences from chunk "
                f"({len(content)} -> {len(compacted_content)} chars)"
            )

        return compacted
