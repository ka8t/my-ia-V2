"""Service pour la gestion du profil utilisateur."""
import logging
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_users.password import PasswordHelper

from app.models import User, City, Country
from app.common.crypto.search import update_user_search_indexes
from app.features.admin.password_policy.service import PasswordPolicyService
from app.features.user.profile.schemas import ProfileRead, ProfileUpdate
from app.common.i18n import t

logger = logging.getLogger(__name__)
password_helper = PasswordHelper()


class ProfileService:
    """Service pour la gestion du profil utilisateur."""

    # =========================================================================
    # GET PROFILE
    # =========================================================================

    @staticmethod
    async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> ProfileRead:
        """Recupere le profil complet d'un utilisateur."""
        # Charger l'utilisateur avec les relations
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.unique().scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail=t("error_user_not_found"))

        # Charger les donnees geo si presentes
        city_name = None
        city_postal_code = None
        country_name = None
        country_flag = None

        if user.city_id:
            city_result = await db.execute(
                select(City).where(City.id == user.city_id)
            )
            city = city_result.scalar_one_or_none()
            if city:
                city_name = city.name
                city_postal_code = city.postal_code

        if user.country_code:
            country_result = await db.execute(
                select(Country).where(Country.code == user.country_code)
            )
            country = country_result.scalar_one_or_none()
            if country:
                country_name = country.name
                country_flag = country.flag

        return ProfileRead(
            email=user.email,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            phone=user.phone,
            address_line1=user.address_line1,
            address_line2=user.address_line2,
            city_id=user.city_id,
            city_name=city_name,
            city_postal_code=city_postal_code,
            country_code=user.country_code,
            country_name=country_name,
            country_flag=country_flag,
            is_verified=user.is_verified,
            created_at=user.created_at,
            updated_at=user.updated_at
        )

    # =========================================================================
    # UPDATE PROFILE
    # =========================================================================

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: ProfileUpdate
    ) -> ProfileRead:
        """Met a jour le profil d'un utilisateur."""
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.unique().scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail=t("error_user_not_found"))

        # Extraire les donnees a mettre a jour
        update_data = data.model_dump(exclude_unset=True)

        # Verifier que le pays existe si fourni
        if 'country_code' in update_data and update_data['country_code']:
            country_result = await db.execute(
                select(Country).where(
                    Country.code == update_data['country_code'],
                    Country.is_active == True
                )
            )
            if not country_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail=t("error_country_inactive", code=update_data['country_code'])
                )

        # Verifier que la ville existe si fournie
        if 'city_id' in update_data and update_data['city_id']:
            city_result = await db.execute(
                select(City).where(City.id == update_data['city_id'])
            )
            city = city_result.scalar_one_or_none()
            if not city:
                raise HTTPException(
                    status_code=400,
                    detail=t("error_city_not_found", city_id=update_data['city_id'])
                )
            # Si pas de country_code fourni, utiliser celui de la ville
            if 'country_code' not in update_data:
                update_data['country_code'] = city.country_code

        # Mettre a jour les champs
        for field, value in update_data.items():
            setattr(user, field, value)

        # Mettre a jour les index de recherche si necessaire
        update_user_search_indexes(
            user,
            first_name=update_data.get('first_name'),
            last_name=update_data.get('last_name'),
            phone=update_data.get('phone')
        )

        await db.commit()
        await db.refresh(user)

        logger.info(f"Profil mis a jour pour user {user_id}")

        return await ProfileService.get_profile(db, user_id)

    # =========================================================================
    # CHANGE PASSWORD
    # =========================================================================

    @staticmethod
    async def change_password(
        db: AsyncSession,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        policy_name: str = "default"
    ) -> bool:
        """
        Change le mot de passe d'un utilisateur.

        Args:
            db: Session DB
            user_id: ID de l'utilisateur
            current_password: Mot de passe actuel
            new_password: Nouveau mot de passe
            policy_name: Nom de la politique a appliquer

        Returns:
            True si succes

        Raises:
            HTTPException: Si le mot de passe actuel est incorrect ou
                           si le nouveau mot de passe ne respecte pas la politique
        """
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.unique().scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail=t("error_user_not_found"))

        # Verifier le mot de passe actuel
        verified, _ = password_helper.verify_and_update(current_password, user.hashed_password)
        if not verified:
            raise HTTPException(
                status_code=400,
                detail=t("error_current_password_incorrect")
            )

        # Valider le nouveau mot de passe contre la politique
        validation = await PasswordPolicyService.validate_password(
            db, new_password, policy_name
        )

        if not validation.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": t("error_password_policy_violated"),
                    "errors": validation.errors,
                    "suggestions": validation.suggestions
                }
            )

        # Verifier l'historique des mots de passe
        is_in_history = await PasswordPolicyService.check_password_history(
            db, user_id, new_password, policy_name
        )

        if is_in_history:
            raise HTTPException(
                status_code=400,
                detail=t("error_password_recently_used")
            )

        # Hasher et sauvegarder le nouveau mot de passe
        new_hashed = password_helper.hash(new_password)

        # Ajouter l'ancien mot de passe a l'historique
        await PasswordPolicyService.add_password_to_history(
            db, user_id, user.hashed_password, policy_name
        )

        # Mettre a jour le mot de passe
        user.hashed_password = new_hashed
        await db.commit()

        logger.info(f"Mot de passe change pour user {user_id}")

        return True

    # =========================================================================
    # ADMIN: GET USER PROFILE
    # =========================================================================

    @staticmethod
    async def get_user_profile_admin(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> ProfileRead:
        """Recupere le profil d'un utilisateur (admin)."""
        return await ProfileService.get_profile(db, user_id)

    @staticmethod
    async def update_user_profile_admin(
        db: AsyncSession,
        user_id: uuid.UUID,
        data: ProfileUpdate
    ) -> ProfileRead:
        """Met a jour le profil d'un utilisateur (admin)."""
        return await ProfileService.update_profile(db, user_id, data)
