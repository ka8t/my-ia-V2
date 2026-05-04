"""
Repository Admin Users

Opérations de base de données pour la gestion des utilisateurs admin.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload

from app.common.utils.query import paginate_query
from app.models import User, Role, Conversation, Document, City, Country, UserPreference, Collection

logger = logging.getLogger(__name__)


class AdminUserRepository:
    """Repository pour les opérations utilisateurs admin"""

    @staticmethod
    async def get_users_with_stats(
        db: AsyncSession,
        role_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        is_verified: Optional[bool] = None,
        approval_status: Optional[str] = None,
        search: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[dict], int]:
        """
        Récupère les utilisateurs avec statistiques et comptage total.

        Args:
            db: Session de base de données
            role_id: Filtrer par rôle
            is_active: Filtrer par statut actif
            is_verified: Filtrer par vérification
            search: Recherche dans email/username
            created_after: Filtrer par date de création (après)
            created_before: Filtrer par date de création (avant)
            limit: Nombre maximum de résultats
            offset: Décalage pour pagination

        Returns:
            Tuple (liste d'utilisateurs enrichis, total)
        """
        # Requête de base avec jointure sur le rôle
        base_query = select(User).options(joinedload(User.role))

        # Application des filtres
        if role_id is not None:
            base_query = base_query.where(User.role_id == role_id)
        if is_active is not None:
            base_query = base_query.where(User.is_active == is_active)
        if is_verified is not None:
            base_query = base_query.where(User.is_verified == is_verified)
        if approval_status is not None:
            base_query = base_query.where(User.approval_status == approval_status)
        if search:
            search_pattern = f"%{search}%"
            base_query = base_query.where(
                or_(
                    User.email.ilike(search_pattern),
                    User.username.ilike(search_pattern)
                )
            )
        if created_after:
            base_query = base_query.where(User.created_at >= created_after)
        if created_before:
            base_query = base_query.where(User.created_at <= created_before)

        # Pagination
        base_query = base_query.order_by(User.created_at.desc())
        users, pagination = await paginate_query(
            db, base_query, limit=limit, offset=offset, unique=True
        )

        # Enrichir avec les comptages
        users_data = []
        for user in users:
            # Compter les conversations
            conv_count_result = await db.execute(
                select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
            )
            conversations_count = conv_count_result.scalar() or 0

            # Compter les documents
            doc_count_result = await db.execute(
                select(func.count(Document.id)).where(Document.user_id == user.id)
            )
            documents_count = doc_count_result.scalar() or 0

            # Récupérer les préférences pour voice_to_text
            pref_result = await db.execute(
                select(UserPreference).where(UserPreference.user_id == user.id)
            )
            preferences = pref_result.scalar_one_or_none()
            voice_to_text_enabled = preferences.voice_to_text_enabled if preferences else False

            # Vérifier si l'utilisateur a une collection privée
            coll_result = await db.execute(
                select(Collection.id).where(
                    Collection.owner_id == user.id,
                    Collection.type == "private"
                ).limit(1)
            )
            has_collection = coll_result.scalar_one_or_none() is not None

            users_data.append({
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "role_id": user.role_id,
                "role_name": user.role.name if user.role else "unknown",
                "is_active": user.is_active,
                "is_verified": user.is_verified,
                "is_superuser": user.is_superuser,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "last_login": user.last_login,
                "conversations_count": conversations_count,
                "documents_count": documents_count,
                "voice_to_text_enabled": voice_to_text_enabled,
                "has_collection": has_collection,
                "approval_status": user.approval_status
            })

        return users_data, pagination.total

    @staticmethod
    async def get_user_by_id_with_stats(
        db: AsyncSession,
        user_id: uuid.UUID
    ) -> Optional[dict]:
        """
        Récupère un utilisateur par ID avec ses statistiques.

        Args:
            db: Session de base de données
            user_id: UUID de l'utilisateur

        Returns:
            Dictionnaire avec les données utilisateur enrichies ou None
        """
        query = select(User).options(joinedload(User.role)).where(User.id == user_id)
        result = await db.execute(query)
        user = result.unique().scalar_one_or_none()

        if not user:
            return None

        # Compter les conversations
        conv_count_result = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
        )
        conversations_count = conv_count_result.scalar() or 0

        # Compter les documents
        doc_count_result = await db.execute(
            select(func.count(Document.id)).where(Document.user_id == user.id)
        )
        documents_count = doc_count_result.scalar() or 0

        # Récupérer les données géographiques
        city_name = None
        city_postal_code = None
        country_name = None

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

        # Récupérer les préférences pour voice_to_text
        pref_result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user.id)
        )
        preferences = pref_result.scalar_one_or_none()
        voice_to_text_enabled = preferences.voice_to_text_enabled if preferences else False

        # Vérifier si l'utilisateur a une collection privée
        coll_result = await db.execute(
            select(Collection.id).where(
                Collection.owner_id == user.id,
                Collection.type == "private"
            ).limit(1)
        )
        has_collection = coll_result.scalar_one_or_none() is not None

        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "address_line1": user.address_line1,
            "address_line2": user.address_line2,
            "city_id": user.city_id,
            "city_name": city_name,
            "city_postal_code": city_postal_code,
            "country_code": user.country_code,
            "country_name": country_name,
            "role_id": user.role_id,
            "role_name": user.role.name if user.role else "unknown",
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "is_superuser": user.is_superuser,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_login": user.last_login,
            "conversations_count": conversations_count,
            "documents_count": documents_count,
            "voice_to_text_enabled": voice_to_text_enabled,
            "has_collection": has_collection,
            "approval_status": user.approval_status
        }

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        """Récupère un utilisateur par ID (sans stats)"""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """Récupère un utilisateur par email"""
        result = await db.execute(select(User).where(User.email == email))
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
        """Récupère un utilisateur par username"""
        result = await db.execute(select(User).where(User.username == username))
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def count_admins(db: AsyncSession) -> int:
        """Compte le nombre d'administrateurs actifs"""
        result = await db.execute(
            select(func.count(User.id)).where(
                User.role_id == 1,
                User.is_active == True
            )
        )
        return result.scalar() or 0
