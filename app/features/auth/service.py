"""
Service d'authentification

Configure FastAPI Users avec le backend JWT.
Fournit AuthDBService pour les operations DB liees a l'authentification.
"""
import logging
import uuid
import jwt
from typing import List, Optional
from uuid import UUID

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, BearerTransport
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Collection, OAuthAccount, Role
from app.features.auth.config import get_jwt_strategy, SECRET
from app.features.user.dependencies import get_user_manager

logger = logging.getLogger(__name__)


# Transports
bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

# Auth Backend
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# FastAPI Users Instance
fastapi_users = FastAPIUsers[User, uuid.UUID](
    get_user_manager,
    [auth_backend],
)

# Dependency pour récupérer l'utilisateur actif (sans vérification email)
current_active_user = fastapi_users.current_user(active=True)

# Dependency pour utilisateur vérifié (email confirmé)
current_verified_user = fastapi_users.current_user(active=True, verified=True)

# Dependency optionnelle - retourne None si pas de user
optional_current_user = fastapi_users.current_user(active=True, optional=True)


async def verify_jwt_token(token: str) -> Optional[dict]:
    """
    Vérifie un token JWT et retourne le payload si valide

    Args:
        token: Token JWT à vérifier

    Returns:
        Payload du token si valide, None sinon
    """
    try:
        payload = jwt.decode(
            token,
            SECRET,
            algorithms=["HS256"],
            audience=["fastapi-users:auth"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


class AuthDBService:
    """Service pour les operations DB liees a l'authentification.

    Encapsule les requetes SQL utilisees par les endpoints auth
    (verification username, listing roles, suppression cascade utilisateur).
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_username_available(
        self, username: str, exclude_user_id: Optional[UUID] = None
    ) -> bool:
        """Verifie si un username est disponible (insensible a la casse).

        Args:
            username: Le username a verifier.
            exclude_user_id: ID utilisateur a exclure (pour l'edition de profil).

        Returns:
            True si le username est libre, False sinon.
        """
        query = select(User.id).where(func.lower(User.username) == username.lower())

        if exclude_user_id:
            query = query.where(User.id != exclude_user_id)

        result = await self.session.execute(query.limit(1))
        return result.scalar_one_or_none() is None

    async def list_roles(self) -> List[Role]:
        """Retourne tous les roles disponibles, tries par ID.

        Returns:
            Liste des roles.
        """
        result = await self.session.execute(select(Role).order_by(Role.id))
        return list(result.scalars().all())

    async def get_role_by_id(self, role_id: int) -> Optional[Role]:
        """Recupere un role par son ID.

        Args:
            role_id: ID du role.

        Returns:
            Le role ou None s'il n'existe pas.
        """
        result = await self.session.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Recupere un utilisateur par son email.

        Args:
            email: Email de l'utilisateur.

        Returns:
            L'utilisateur ou None s'il n'existe pas.
        """
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.unique().scalar_one_or_none()

    async def delete_user_cascade(self, user: User) -> None:
        """Supprime un utilisateur et toutes ses donnees associees en cascade.

        Ordre de suppression (contraintes FK):
        1. Messages (reference conversations)
        2. Conversations (reference collections et users)
        3. Documents (reference collections)
        4. Collections (reference users)
        5. OAuthAccounts (reference users)
        6. User

        Note: la suppression de la collection ChromaDB doit etre faite
        par l'appelant avant d'appeler cette methode.

        Args:
            user: L'utilisateur a supprimer.
        """
        from app.models import Message, Conversation, Document

        # 1. Supprimer les messages des conversations de l'utilisateur
        conversations_subq = select(Conversation.id).where(
            Conversation.user_id == user.id
        ).scalar_subquery()
        await self.session.execute(
            delete(Message).where(Message.conversation_id.in_(conversations_subq))
        )

        # 2. Supprimer les conversations
        await self.session.execute(
            delete(Conversation).where(Conversation.user_id == user.id)
        )

        # 3. Supprimer les documents des collections de l'utilisateur
        collections_subq = select(Collection.id).where(
            Collection.owner_id == user.id
        ).scalar_subquery()
        await self.session.execute(
            delete(Document).where(Document.collection_id.in_(collections_subq))
        )

        # 4. Supprimer les collections en DB
        await self.session.execute(
            delete(Collection).where(Collection.owner_id == user.id)
        )

        # 5. Supprimer les comptes OAuth lies
        await self.session.execute(
            delete(OAuthAccount).where(OAuthAccount.user_id == user.id)
        )

        # 6. Supprimer l'utilisateur
        await self.session.delete(user)
        await self.session.commit()

    async def set_user_role(self, user: User, role_id: int) -> User:
        """Modifie le role d'un utilisateur.

        Args:
            user: L'utilisateur a modifier.
            role_id: ID du nouveau role.

        Returns:
            L'utilisateur mis a jour.
        """
        if role_id != user.role_id:
            user.role_id = role_id
            await self.session.commit()
            await self.session.refresh(user)
        return user
