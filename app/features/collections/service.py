"""
Service Collections User - Acces utilisateur aux collections.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Collection, User, Document, CorpusSource, ContextSource, CorpusDocument
from app.features.system.service import SystemConfigService
from app.features.collections.schemas import (
    CollectionSummary,
    AvailableCollectionsResponse,
    MyCollectionStatsResponse,
)
from app.common.i18n import t
from app.core.config import settings

logger = logging.getLogger(__name__)

# Duree de validite du cache des suggestions (en heures)
SUGGESTIONS_CACHE_HOURS = 24


class CollectionService:
    """Service utilisateur pour les collections."""

    def __init__(self, session: AsyncSession, chroma_client=None):
        self.session = session
        self.chroma = chroma_client

    async def get_available_collections(
        self, user: User
    ) -> AvailableCollectionsResponse:
        """
        Liste les collections disponibles pour l'utilisateur.

        Filtre les collections publiques par provider courant :
        seules les collections dont le corpus a du contenu indexé
        avec le provider actif (ou non indexé) sont retournées.
        """
        # Récupérer le provider courant
        config_service = SystemConfigService(self.session)
        current_provider = await config_service.get("llm.provider", "ollama")

        # Ma bibliothèque privée (pas de filtre provider pour ma propre collection)
        my_result = await self.session.execute(
            select(Collection).where(
                Collection.owner_id == user.id,
                Collection.type == "private"
            )
        )
        my_collection = my_result.scalar_one_or_none()

        # Collections publiques
        public_result = await self.session.execute(
            select(Collection).where(Collection.type == "public")
            .order_by(Collection.display_name)
        )
        all_public_collections = list(public_result.scalars().all())

        # Filtrer les collections publiques par provider
        public_collections = await self._filter_collections_by_provider(
            all_public_collections, current_provider
        )

        # Charger les stats des corpus pour toutes les collections
        all_collections = ([my_collection] if my_collection else []) + public_collections
        corpus_stats = await self._get_corpus_stats_for_collections(
            all_collections, provider_filter=current_provider
        )

        return AvailableCollectionsResponse(
            my_collection=self._to_summary(my_collection, is_mine=True, corpus_stats=corpus_stats.get(my_collection.corpus_id) if my_collection and my_collection.corpus_id else None) if my_collection else None,
            public_collections=[
                self._to_summary(c, is_mine=False, corpus_stats=corpus_stats.get(c.corpus_id) if c.corpus_id else None)
                for c in public_collections
            ],
        )

    async def get_my_collection_stats(self, user: User) -> MyCollectionStatsResponse:
        """Stats de ma collection privee."""
        result = await self.session.execute(
            select(Collection).where(
                Collection.owner_id == user.id,
                Collection.type == "private"
            )
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail=t("error_collection_private_not_found"))

        # Count live ChromaDB
        chroma_count = 0
        if self.chroma:
            try:
                chroma_coll = self.chroma.get_collection(name=collection.name)
                chroma_count = chroma_coll.count()
            except Exception as e:
                logger.warning(f"ChromaDB non accessible: {e}")

        return MyCollectionStatsResponse(
            id=collection.id,
            name=collection.name,
            display_name=collection.display_name,
            document_count=collection.document_count,
            chunk_count=collection.chunk_count,
            chroma_count=chroma_count,
            created_at=collection.created_at,
        )

    async def can_access_collection(self, user: User, collection_id: UUID) -> bool:
        """Verifie si l'utilisateur peut acceder a une collection."""
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            return False

        # Public = tout le monde
        if collection.type == "public":
            return True

        # Privee = proprietaire uniquement
        return collection.owner_id == user.id

    async def get_collection_by_id(self, collection_id: UUID) -> Collection:
        """Recupere une collection par ID."""
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail=t("error_collection_not_found"))

        return collection

    async def get_user_private_collection(self, user_id: UUID) -> Collection:
        """Recupere la collection privee d'un utilisateur."""
        result = await self.session.execute(
            select(Collection).where(
                Collection.owner_id == user_id,
                Collection.type == "private"
            )
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail=t("error_collection_private_not_found"))

        return collection

    def _to_summary(
        self, collection: Collection, is_mine: bool, corpus_stats: dict = None
    ) -> CollectionSummary:
        """Convertit un model en summary avec stats du corpus si disponible."""
        return CollectionSummary(
            id=collection.id,
            name=collection.name,
            display_name=collection.display_name,
            description=collection.description,
            type=collection.type,
            is_mine=is_mine,
            document_count=collection.document_count,
            chunk_count=collection.chunk_count,
            # Stats du corpus associé
            corpus_id=collection.corpus_id,
            corpus_document_count=corpus_stats["document_count"] if corpus_stats else None,
            corpus_source_count=corpus_stats["source_count"] if corpus_stats else None,
            corpus_chunk_count=corpus_stats["chunk_count"] if corpus_stats else None,
        )

    async def _filter_collections_by_provider(
        self, collections: list, provider: str
    ) -> list:
        """
        Filtre les collections pour ne garder que celles compatibles avec le provider.

        Une collection est compatible si:
        - Elle a un corpus avec au moins un document ou source indexé avec le provider
        - Elle a un corpus avec au moins un document ou source non indexé (NULL)

        Les collections sans corpus sont exclues (pas de contenu RAG).

        Args:
            collections: Liste des collections à filtrer
            provider: Provider courant (ollama ou llamacpp)

        Returns:
            Liste des collections compatibles
        """
        if not collections:
            return []

        compatible_collections = []

        for collection in collections:
            # Collection sans corpus = exclue (pas de contenu RAG)
            if not collection.corpus_id:
                continue

            # Vérifier si le corpus a du contenu compatible
            # Documents avec provider courant ou NULL (via table pivot corpus_documents)
            doc_result = await self.session.execute(
                select(func.count(Document.id))
                .select_from(Document)
                .join(CorpusDocument, CorpusDocument.document_id == Document.id)
                .where(
                    CorpusDocument.corpus_id == collection.corpus_id,
                    or_(
                        Document.indexed_provider == provider,
                        Document.indexed_provider.is_(None)
                    )
                )
            )
            doc_count = doc_result.scalar() or 0

            # Sources avec provider courant ou NULL
            source_result = await self.session.execute(
                select(func.count(CorpusSource.id))
                .select_from(CorpusSource)
                .join(ContextSource, CorpusSource.source_id == ContextSource.id)
                .where(
                    CorpusSource.corpus_id == collection.corpus_id,
                    or_(
                        ContextSource.indexed_provider == provider,
                        ContextSource.indexed_provider.is_(None)
                    )
                )
            )
            source_count = source_result.scalar() or 0

            # Compatible si au moins un élément
            if doc_count > 0 or source_count > 0:
                compatible_collections.append(collection)

        return compatible_collections

    async def _get_corpus_stats_for_collections(
        self, collections: list, provider_filter: str = None
    ) -> dict:
        """
        Calcule les stats des corpus pour une liste de collections.

        Args:
            collections: Liste des collections
            provider_filter: Si fourni, ne compte que les éléments de ce provider (ou NULL)

        Returns:
            Dict[corpus_id, {"document_count": int, "source_count": int, "chunk_count": int}]
        """
        # Récupérer les IDs des corpus uniques
        corpus_ids = {c.corpus_id for c in collections if c and c.corpus_id}
        if not corpus_ids:
            return {}

        stats = {}

        # Calculer les stats pour chaque corpus
        for corpus_id in corpus_ids:
            # Requête de base pour documents (via table pivot corpus_documents)
            doc_query = (
                select(
                    func.count(Document.id),
                    func.coalesce(func.sum(Document.chunk_count), 0)
                )
                .select_from(Document)
                .join(CorpusDocument, CorpusDocument.document_id == Document.id)
                .where(CorpusDocument.corpus_id == corpus_id)
            )

            # Filtrer par provider si demandé
            if provider_filter:
                doc_query = doc_query.where(
                    or_(
                        Document.indexed_provider == provider_filter,
                        Document.indexed_provider.is_(None)
                    )
                )

            doc_result = await self.session.execute(doc_query)
            doc_row = doc_result.one()
            doc_count = doc_row[0] or 0
            doc_chunks = doc_row[1] or 0

            # Requête de base pour sources
            source_query = (
                select(
                    func.count(CorpusSource.id),
                    func.coalesce(func.sum(ContextSource.chunk_count), 0)
                )
                .select_from(CorpusSource)
                .join(ContextSource, CorpusSource.source_id == ContextSource.id)
                .where(CorpusSource.corpus_id == corpus_id)
            )

            # Filtrer par provider si demandé
            if provider_filter:
                source_query = source_query.where(
                    or_(
                        ContextSource.indexed_provider == provider_filter,
                        ContextSource.indexed_provider.is_(None)
                    )
                )

            source_result = await self.session.execute(source_query)
            source_row = source_result.one()
            source_count = source_row[0] or 0
            source_chunks = source_row[1] or 0

            stats[corpus_id] = {
                "document_count": doc_count,
                "source_count": source_count,
                "chunk_count": int(doc_chunks) + int(source_chunks),
            }

        return stats

    async def get_suggestions(
        self, collection_id: UUID, force_refresh: bool = False
    ) -> List[str]:
        """
        Recupere les questions suggerees pour une collection.
        Utilise le cache si disponible, sinon genere via Ollama.

        Args:
            collection_id: ID de la collection
            force_refresh: Forcer la regeneration meme si le cache est valide

        Returns:
            Liste de 3 questions suggerees
        """
        # Recuperer la collection
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()

        if not collection:
            raise HTTPException(status_code=404, detail=t("error_collection_not_found"))

        # Verifier le cache
        if not force_refresh and collection.suggested_questions:
            if collection.suggestions_generated_at:
                cache_age = datetime.now(timezone.utc) - collection.suggestions_generated_at
                if cache_age < timedelta(hours=SUGGESTIONS_CACHE_HOURS):
                    logger.info(f"Suggestions cache hit for collection {collection.name}")
                    return collection.suggested_questions

        # Generer les suggestions via Ollama
        suggestions = await self._generate_suggestions(collection)

        # Mettre en cache
        collection.suggested_questions = suggestions
        collection.suggestions_generated_at = datetime.now(timezone.utc)
        await self.session.commit()

        logger.info(f"Generated and cached suggestions for collection {collection.name}")
        return suggestions

    async def _generate_suggestions(self, collection: Collection) -> List[str]:
        """
        Genere 3 questions suggerees via Ollama basees sur les documents de la collection.

        Args:
            collection: Collection pour laquelle generer les suggestions

        Returns:
            Liste de 3 questions
        """
        # Recuperer les noms des documents de la collection
        docs_result = await self.session.execute(
            select(Document.filename, Document.file_type)
            .where(Document.collection_id == collection.id, Document.is_indexed == True)
            .limit(20)
        )
        documents = docs_result.fetchall()

        if not documents:
            # Collection vide - retourner des suggestions generiques
            return [
                "Quels types de documents puis-je ajouter ?",
                "Comment fonctionne la recherche ?",
                "Comment ajouter des documents ?"
            ]

        # Construire la liste des documents
        doc_list = "\n".join([f"- {doc.filename} ({doc.file_type})" for doc in documents])

        # Prompt pour Ollama
        prompt = f"""Tu es un assistant qui aide les utilisateurs a explorer une base de connaissances.

La collection "{collection.display_name}" contient les documents suivants:
{doc_list}

Genere exactement 3 questions pertinentes que l'utilisateur pourrait poser sur ces documents.
Les questions doivent etre courtes (max 10 mots), en francais, et commencer par un verbe ou un mot interrogatif.

Reponds UNIQUEMENT avec les 3 questions, une par ligne, sans numerotation ni tiret."""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={
                        "model": settings.llm_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.7}
                    }
                )
                response.raise_for_status()
                data = response.json()

                # Parser la reponse
                raw_response = data.get("response", "")
                lines = [line.strip() for line in raw_response.strip().split("\n") if line.strip()]

                # Nettoyer les lignes (enlever numerotation, tirets, etc.)
                questions = []
                for line in lines:
                    # Enlever numerotation type "1.", "1)", "-", "*"
                    cleaned = line.lstrip("0123456789.-)*• ").strip()
                    if cleaned and len(cleaned) > 5:
                        questions.append(cleaned)
                    if len(questions) >= 3:
                        break

                if len(questions) < 3:
                    # Completer avec des questions generiques
                    default_questions = [
                        f"Que contient la documentation ?",
                        f"Quels sont les concepts cles ?",
                        f"Comment utiliser ces informations ?"
                    ]
                    questions.extend(default_questions[:(3 - len(questions))])

                return questions[:3]

        except Exception as e:
            logger.error(f"Error generating suggestions: {e}")
            # Fallback generique
            return [
                f"Que contient {collection.display_name} ?",
                "Quels documents sont disponibles ?",
                "Comment puis-je vous aider ?"
            ]
