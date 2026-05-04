"""
Repository Sources - Operations base de donnees
"""
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ContextSource, CorpusSource

logger = logging.getLogger(__name__)


class SourceRepository:
    """Operations CRUD pour les sources de contexte"""

    @staticmethod
    async def get_all(
        db: AsyncSession,
        is_enabled: Optional[bool] = None,
        source_type: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        provider_filter: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> tuple[List[ContextSource], int]:
        """Recupere toutes les sources avec filtres optionnels et pagination

        Args:
            provider_filter: Si fourni, filtre par indexed_provider = provider OR IS NULL
        """
        from sqlalchemy import or_

        # Base query avec filtres et chargement des relations corpus
        base_query = select(ContextSource).options(
            selectinload(ContextSource.corpus_sources).selectinload(CorpusSource.corpus)
        )

        if is_enabled is not None:
            base_query = base_query.where(ContextSource.is_enabled == is_enabled)
        if source_type:
            base_query = base_query.where(ContextSource.source_type == source_type)
        if source_ids:
            uuid_ids = [UUID(sid) for sid in source_ids]
            base_query = base_query.where(ContextSource.id.in_(uuid_ids))
        if search:
            search_pattern = f"%{search}%"
            base_query = base_query.where(
                ContextSource.name.ilike(search_pattern) |
                ContextSource.description.ilike(search_pattern)
            )
        # Filtre par provider courant (inclut les sources non encore indexées)
        if provider_filter:
            base_query = base_query.where(
                or_(
                    ContextSource.indexed_provider == provider_filter,
                    ContextSource.indexed_provider.is_(None)
                )
            )

        # Compter le total
        count_query = select(func.count()).select_from(base_query.subquery())
        total = await db.scalar(count_query) or 0

        # Appliquer tri et pagination
        query = base_query.order_by(ContextSource.priority)
        if limit:
            query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all()), total

    @staticmethod
    async def get_by_id(db: AsyncSession, source_id: UUID) -> Optional[ContextSource]:
        """Recupere une source par son ID"""
        result = await db.execute(
            select(ContextSource)
            .options(selectinload(ContextSource.corpus_sources).selectinload(CorpusSource.corpus))
            .where(ContextSource.id == source_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_name(db: AsyncSession, name: str) -> Optional[ContextSource]:
        """Recupere une source par son nom"""
        result = await db.execute(
            select(ContextSource).where(ContextSource.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, source: ContextSource) -> ContextSource:
        """Cree une nouvelle source"""
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source

    @staticmethod
    async def update(
        db: AsyncSession,
        source_id: UUID,
        data: dict
    ) -> Optional[ContextSource]:
        """Met a jour une source"""
        await db.execute(
            update(ContextSource)
            .where(ContextSource.id == source_id)
            .values(**data)
        )
        await db.commit()
        return await SourceRepository.get_by_id(db, source_id)

    @staticmethod
    async def delete(db: AsyncSession, source_id: UUID) -> bool:
        """Supprime une source"""
        result = await db.execute(
            delete(ContextSource).where(ContextSource.id == source_id)
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def toggle(db: AsyncSession, source_id: UUID) -> Optional[ContextSource]:
        """Inverse l'etat is_enabled d'une source"""
        source = await SourceRepository.get_by_id(db, source_id)
        if source:
            source.is_enabled = not source.is_enabled
            await db.commit()
            await db.refresh(source)
        return source
