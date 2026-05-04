from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# URL de la base de données normalisée (identifiants PostgreSQL en minuscules)
# La normalisation est effectuée dans app/core/config.py via le validateur
DATABASE_URL = settings.database_url

# Configuration du pool de connexions PostgreSQL
# - pool_size: Nombre de connexions maintenues ouvertes (réutilisées)
# - max_overflow: Connexions temporaires supplémentaires autorisées
# - pool_pre_ping: Vérifie que la connexion est valide avant utilisation
# - pool_recycle: Recycle les connexions après N secondes (évite les déconnexions)
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,          # 5 connexions persistantes
    max_overflow=10,      # +10 connexions temporaires si besoin
    pool_pre_ping=True,   # Vérifie la connexion (évite les erreurs)
    pool_recycle=3600,    # Recycle après 1h (évite les déconnexions PostgreSQL)
    echo=False            # Pas de log SQL (performance)
)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
