"""
Service pour la gestion des politiques de mot de passe.

Logique metier pour CRUD des politiques et gestion de l'historique.
"""
import uuid
import logging
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from fastapi_users.password import PasswordHelper

from app.models import PasswordPolicy
from app.features.admin.password_policy.repository import (
    PasswordPolicyRepository,
    PasswordHistoryRepository
)
from app.features.admin.password_policy.validator import PasswordValidator, ValidationResult

logger = logging.getLogger(__name__)

# Password hasher (meme instance que FastAPI Users : pwdlib/argon2id)
password_helper = PasswordHelper()


class PasswordPolicyService:
    """Service pour les operations sur les politiques de mot de passe."""

    # ========================================================================
    # CRUD POLICIES
    # ========================================================================

    @staticmethod
    async def get_all_policies(
        db: AsyncSession,
        include_inactive: bool = False
    ) -> List[PasswordPolicy]:
        """
        Recupere toutes les politiques.

        Args:
            db: Session de base de donnees
            include_inactive: Inclure les politiques inactives

        Returns:
            Liste des politiques
        """
        return await PasswordPolicyRepository.get_all(db, include_inactive)

    @staticmethod
    async def get_policy(db: AsyncSession, policy_id: int) -> PasswordPolicy:
        """
        Recupere une politique par ID.

        Args:
            db: Session de base de donnees
            policy_id: ID de la politique

        Returns:
            Politique

        Raises:
            HTTPException 404 si non trouvee
        """
        policy = await PasswordPolicyRepository.get_by_id(db, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Password policy not found")
        return policy

    @staticmethod
    async def get_policy_by_name(db: AsyncSession, name: str) -> PasswordPolicy:
        """
        Recupere une politique par nom.

        Args:
            db: Session de base de donnees
            name: Nom de la politique

        Returns:
            Politique

        Raises:
            HTTPException 404 si non trouvee
        """
        policy = await PasswordPolicyRepository.get_by_name(db, name)
        if not policy:
            raise HTTPException(status_code=404, detail=f"Password policy '{name}' not found")
        return policy

    @staticmethod
    async def create_policy(
        db: AsyncSession,
        name: str,
        min_length: int = 8,
        max_length: int = 128,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_digit: bool = True,
        require_special: bool = True,
        special_characters: str = "!@#$%^&*()_+-=[]{}|;:,.<>?",
        expire_days: int = 0,
        history_count: int = 0,
        max_failed_attempts: int = 5,
        lockout_duration_minutes: int = 30,
        is_active: bool = True
    ) -> PasswordPolicy:
        """
        Cree une nouvelle politique de mot de passe.

        Args:
            db: Session de base de donnees
            name: Nom unique de la politique
            ... autres parametres de la politique

        Returns:
            Politique creee

        Raises:
            HTTPException 409 si le nom existe deja
        """
        # Verifier unicite du nom
        existing = await PasswordPolicyRepository.get_by_name(db, name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Password policy with name '{name}' already exists"
            )

        policy = PasswordPolicy(
            name=name,
            min_length=min_length,
            max_length=max_length,
            require_uppercase=require_uppercase,
            require_lowercase=require_lowercase,
            require_digit=require_digit,
            require_special=require_special,
            special_characters=special_characters,
            expire_days=expire_days,
            history_count=history_count,
            max_failed_attempts=max_failed_attempts,
            lockout_duration_minutes=lockout_duration_minutes,
            is_active=is_active
        )

        policy = await PasswordPolicyRepository.create(db, policy)
        logger.info(f"Password policy created: {name}")
        return policy

    @staticmethod
    async def update_policy(
        db: AsyncSession,
        policy_id: int,
        **kwargs
    ) -> PasswordPolicy:
        """
        Met a jour une politique de mot de passe.

        Args:
            db: Session de base de donnees
            policy_id: ID de la politique
            **kwargs: Champs a mettre a jour

        Returns:
            Politique mise a jour

        Raises:
            HTTPException 404 si non trouvee
            HTTPException 409 si le nouveau nom existe deja
        """
        policy = await PasswordPolicyRepository.get_by_id(db, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Password policy not found")

        # Verifier unicite du nom si modifie
        if 'name' in kwargs and kwargs['name'] != policy.name:
            existing = await PasswordPolicyRepository.get_by_name(db, kwargs['name'])
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Password policy with name '{kwargs['name']}' already exists"
                )

        # Appliquer les modifications
        for key, value in kwargs.items():
            if value is not None and hasattr(policy, key):
                setattr(policy, key, value)

        policy = await PasswordPolicyRepository.update(db, policy)
        logger.info(f"Password policy updated: {policy.name}")
        return policy

    @staticmethod
    async def delete_policy(db: AsyncSession, policy_id: int) -> bool:
        """
        Supprime une politique de mot de passe.

        Args:
            db: Session de base de donnees
            policy_id: ID de la politique

        Returns:
            True si supprimee

        Raises:
            HTTPException 404 si non trouvee
            HTTPException 403 si c'est la politique par defaut
        """
        policy = await PasswordPolicyRepository.get_by_id(db, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="Password policy not found")

        # Empecher suppression de "default"
        if policy.name == "default":
            raise HTTPException(
                status_code=403,
                detail="Cannot delete the default password policy"
            )

        await PasswordPolicyRepository.delete(db, policy)
        logger.info(f"Password policy deleted: {policy.name}")
        return True

    # ========================================================================
    # VALIDATION
    # ========================================================================

    @staticmethod
    async def validate_password(
        db: AsyncSession,
        password: str,
        policy_name: str = "default"
    ) -> ValidationResult:
        """
        Valide un mot de passe contre une politique.

        Args:
            db: Session de base de donnees
            password: Mot de passe en clair
            policy_name: Nom de la politique

        Returns:
            ValidationResult
        """
        return await PasswordValidator.validate_password(db, password, policy_name)

    @staticmethod
    async def validate_password_change(
        db: AsyncSession,
        user_id: uuid.UUID,
        new_password: str,
        policy_name: str = "default"
    ) -> ValidationResult:
        """
        Valide un changement de mot de passe (avec historique).

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            new_password: Nouveau mot de passe
            policy_name: Nom de la politique

        Returns:
            ValidationResult
        """
        return await PasswordValidator.validate_password_change(
            db, user_id, new_password, policy_name
        )

    @staticmethod
    async def get_requirements(
        db: AsyncSession,
        policy_name: str = "default"
    ) -> dict:
        """
        Retourne les exigences d'une politique pour le frontend.

        Args:
            db: Session de base de donnees
            policy_name: Nom de la politique

        Returns:
            Dictionnaire des exigences
        """
        return await PasswordValidator.get_requirements(db, policy_name)

    # ========================================================================
    # HISTORIQUE
    # ========================================================================

    @staticmethod
    async def add_password_to_history(
        db: AsyncSession,
        user_id: uuid.UUID,
        hashed_password: str,
        policy_name: str = "default"
    ) -> None:
        """
        Ajoute un mot de passe a l'historique et nettoie les anciens.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            hashed_password: Hash du mot de passe
            policy_name: Nom de la politique pour determiner history_count
        """
        # Recuperer la politique pour savoir combien conserver
        policy = await PasswordPolicyRepository.get_by_name(db, policy_name)
        keep_count = policy.history_count if policy else 0

        if keep_count > 0:
            # Ajouter a l'historique
            await PasswordHistoryRepository.add_to_history(db, user_id, hashed_password)

            # Nettoyer les anciennes entrees
            deleted = await PasswordHistoryRepository.cleanup_old_entries(
                db, user_id, keep_count
            )
            if deleted > 0:
                logger.debug(f"Cleaned up {deleted} old password entries for user {user_id}")

    @staticmethod
    async def clear_password_history(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> int:
        """
        Supprime tout l'historique de mots de passe d'un utilisateur.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur

        Returns:
            Nombre d'entrees supprimees
        """
        count = await PasswordHistoryRepository.clear_user_history(db, user_id)
        if count > 0:
            logger.info(f"Cleared {count} password history entries for user {user_id}")
        return count

    @staticmethod
    async def check_password_history(
        db: AsyncSession,
        user_id: uuid.UUID,
        password: str,
        policy_name: str = "default"
    ) -> bool:
        """
        Verifie si un mot de passe est dans l'historique recent.

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            password: Mot de passe en clair a verifier
            policy_name: Nom de la politique

        Returns:
            True si le mot de passe est dans l'historique (deja utilise)
        """
        # Recuperer la politique
        policy = await PasswordPolicyRepository.get_by_name(db, policy_name)
        if not policy or policy.history_count == 0:
            return False

        # Recuperer l'historique
        history = await PasswordHistoryRepository.get_user_history(
            db, user_id, policy.history_count
        )

        # Verifier si le mot de passe correspond a l'un des anciens
        for entry in history:
            verified, _ = password_helper.verify_and_update(password, entry.hashed_password)
            if verified:
                return True

        return False
