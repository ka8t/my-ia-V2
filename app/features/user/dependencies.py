"""
Dépendances pour la gestion des utilisateurs

Contient les dépendances FastAPI pour l'accès à la base de données utilisateurs.
"""
from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import User, OAuthAccount
from app.features.user.service import UserManager


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    """
    Dépendance pour obtenir la base de données utilisateurs

    Args:
        session: Session SQLAlchemy asynchrone

    Yields:
        SQLAlchemyUserDatabase: Instance de la base de données utilisateurs avec support OAuth
    """
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    """
    Dépendance pour obtenir le gestionnaire d'utilisateurs

    Args:
        user_db: Base de données utilisateurs

    Yields:
        UserManager: Instance du gestionnaire d'utilisateurs
    """
    yield UserManager(user_db)
