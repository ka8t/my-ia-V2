"""
Repository pour les politiques de mot de passe.

Operations de base de donnees pour PasswordPolicy et PasswordHistory.
"""
import uuid
import logging
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import PasswordPolicy, PasswordHistory

logger = logging.getLogger(__name__)


class PasswordPolicyRepository:
    """Repository pour les operations sur les politiques de mot de passe."""

    @staticmethod
    async def get_all(db: AsyncSession, include_inactive: bool = False) -> List[PasswordPolicy]:
        """
        Recupere toutes les politiques.

        Args:
            db: Session de base de donnees
            include_inactive: Inclure les politiques inactives

        Returns:
            Liste des politiques
        """
        query = select(PasswordPolicy)
        if not include_inactive:
            query = query.where(PasswordPolicy.is_active == True)
        query = query.order_by(PasswordPolicy.name)

        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, policy_id: int) -> Optional[PasswordPolicy]:
        """Recupere une politique par ID."""
        result = await db.execute(
            select(PasswordPolicy).where(PasswordPolicy.id == policy_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_name(db: AsyncSession, name: str) -> Optional[PasswordPolicy]:
        """Recupere une politique par nom."""
        result = await db.execute(
            select(PasswordPolicy).where(PasswordPolicy.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_default(db: AsyncSession) -> Optional[PasswordPolicy]:
        """Recupere la politique par defaut."""
        return await PasswordPolicyRepository.get_by_name(db, "default")

    @staticmethod
    async def create(db: AsyncSession, policy: PasswordPolicy) -> PasswordPolicy:
        """Cree une nouvelle politique."""
        db.add(policy)
        await db.commit()
        await db.refresh(policy)
        return policy

    @staticmethod
    async def update(db: AsyncSession, policy: PasswordPolicy) -> PasswordPolicy:
        """Met a jour une politique."""
        await db.commit()
        await db.refresh(policy)
        return policy

    @staticmethod
    async def delete(db: AsyncSession, policy: PasswordPolicy) -> bool:
        """Supprime une politique."""
        await db.delete(policy)
        await db.commit()
        return True

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Compte le nombre de politiques."""
        result = await db.execute(select(func.count(PasswordPolicy.id)))
        return result.scalar() or 0


class PasswordHistoryRepository:
    """Repository pour l'historique des mots de passe."""

    @staticmethod
    async def get_user_history(
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 24
    ) -> List[PasswordHistory]:
        """
        Recupere l'historique des mots de passe d'un utilisateur.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            limit: Nombre maximum d'entrees

        Returns:
            Liste des anciens mots de passe (du plus recent au plus ancien)
        """
        result = await db.execute(
            select(PasswordHistory)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def add_to_history(
        db: AsyncSession,
        user_id: uuid.UUID,
        hashed_password: str
    ) -> PasswordHistory:
        """
        Ajoute un mot de passe a l'historique.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            hashed_password: Hash du mot de passe

        Returns:
            Nouvelle entree d'historique
        """
        entry = PasswordHistory(
            user_id=user_id,
            hashed_password=hashed_password
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry

    @staticmethod
    async def cleanup_old_entries(
        db: AsyncSession,
        user_id: uuid.UUID,
        keep_count: int
    ) -> int:
        """
        Supprime les anciennes entrees au-dela du nombre a conserver.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            keep_count: Nombre d'entrees a conserver

        Returns:
            Nombre d'entrees supprimees
        """
        if keep_count <= 0:
            return 0

        # Recuperer les IDs a conserver (les plus recents)
        keep_query = (
            select(PasswordHistory.id)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(keep_count)
        )
        keep_result = await db.execute(keep_query)
        keep_ids = [r[0] for r in keep_result.fetchall()]

        if not keep_ids:
            return 0

        # Compter les entrees a supprimer
        count_result = await db.execute(
            select(func.count(PasswordHistory.id))
            .where(PasswordHistory.user_id == user_id)
            .where(PasswordHistory.id.notin_(keep_ids))
        )
        to_delete = count_result.scalar() or 0

        if to_delete > 0:
            # Supprimer les anciennes entrees
            from sqlalchemy import delete
            await db.execute(
                delete(PasswordHistory)
                .where(PasswordHistory.user_id == user_id)
                .where(PasswordHistory.id.notin_(keep_ids))
            )
            await db.commit()

        return to_delete

    @staticmethod
    async def clear_user_history(db: AsyncSession, user_id: uuid.UUID) -> int:
        """
        Supprime tout l'historique d'un utilisateur.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur

        Returns:
            Nombre d'entrees supprimees
        """
        from sqlalchemy import delete

        result = await db.execute(
            select(func.count(PasswordHistory.id))
            .where(PasswordHistory.user_id == user_id)
        )
        count = result.scalar() or 0

        if count > 0:
            await db.execute(
                delete(PasswordHistory).where(PasswordHistory.user_id == user_id)
            )
            await db.commit()

        return count
