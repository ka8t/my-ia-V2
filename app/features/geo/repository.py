"""Repository pour les donnees geographiques."""
import unicodedata
from typing import Optional, List

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Country, City


def normalize_search_text(text: str) -> str:
    """Normalise le texte pour la recherche (sans accents, minuscules)."""
    # Supprime les accents
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    return ascii_text.lower().strip()


class CountryRepository:
    """Repository pour les pays."""

    @staticmethod
    async def get_all_active(db: AsyncSession) -> List[Country]:
        """Recupere tous les pays actifs, tries par ordre d'affichage."""
        result = await db.execute(
            select(Country)
            .where(Country.is_active == True)
            .order_by(Country.display_order, Country.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all(db: AsyncSession) -> List[Country]:
        """Recupere tous les pays (admin)."""
        result = await db.execute(
            select(Country).order_by(Country.display_order, Country.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_code(db: AsyncSession, code: str) -> Optional[Country]:
        """Recupere un pays par son code."""
        result = await db.execute(
            select(Country).where(Country.code == code.upper())
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, country: Country) -> Country:
        """Cree un pays."""
        db.add(country)
        await db.commit()
        await db.refresh(country)
        return country

    @staticmethod
    async def create_batch(db: AsyncSession, countries: List[Country]) -> int:
        """Cree plusieurs pays en batch."""
        db.add_all(countries)
        await db.commit()
        return len(countries)

    @staticmethod
    async def update(db: AsyncSession, country: Country) -> Country:
        """Met a jour un pays."""
        await db.commit()
        await db.refresh(country)
        return country

    @staticmethod
    async def delete(db: AsyncSession, country: Country) -> None:
        """Supprime un pays."""
        await db.delete(country)
        await db.commit()

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Compte le nombre de pays."""
        result = await db.execute(select(func.count()).select_from(Country))
        return result.scalar() or 0


class CityRepository:
    """Repository pour les villes."""

    @staticmethod
    async def search(
        db: AsyncSession,
        query: str,
        country_code: str = "FR",
        limit: int = 20
    ) -> List[City]:
        """Recherche des villes par nom ou code postal."""
        search_term = normalize_search_text(query)

        # Recherche sur search_name (normalise) ou postal_code
        result = await db.execute(
            select(City)
            .where(
                City.country_code == country_code.upper(),
                or_(
                    City.search_name.ilike(f"{search_term}%"),
                    City.postal_code.startswith(query)
                )
            )
            .order_by(
                # Priorite aux grandes villes
                City.population.desc().nulls_last(),
                City.name
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, city_id: int) -> Optional[City]:
        """Recupere une ville par son ID."""
        result = await db.execute(
            select(City).where(City.id == city_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_postal_code(
        db: AsyncSession,
        postal_code: str,
        country_code: str = "FR"
    ) -> List[City]:
        """Recupere les villes par code postal."""
        result = await db.execute(
            select(City)
            .where(
                City.country_code == country_code.upper(),
                City.postal_code == postal_code
            )
            .order_by(City.population.desc().nulls_last(), City.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create(db: AsyncSession, city: City) -> City:
        """Cree une ville."""
        db.add(city)
        await db.commit()
        await db.refresh(city)
        return city

    @staticmethod
    async def create_batch(db: AsyncSession, cities: List[City]) -> int:
        """Cree plusieurs villes en batch."""
        if not cities:
            return 0
        db.add_all(cities)
        await db.commit()
        return len(cities)

    @staticmethod
    async def delete_by_country(db: AsyncSession, country_code: str) -> int:
        """Supprime toutes les villes d'un pays."""
        result = await db.execute(
            select(City).where(City.country_code == country_code.upper())
        )
        cities = result.scalars().all()
        count = len(list(cities))
        for city in cities:
            await db.delete(city)
        await db.commit()
        return count

    @staticmethod
    async def count(db: AsyncSession, country_code: Optional[str] = None) -> int:
        """Compte le nombre de villes."""
        stmt = select(func.count()).select_from(City)
        if country_code:
            stmt = stmt.where(City.country_code == country_code.upper())
        result = await db.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    async def get_all_by_country(db: AsyncSession, country_code: str) -> List[City]:
        """Recupere toutes les villes d'un pays."""
        result = await db.execute(
            select(City)
            .where(City.country_code == country_code.upper())
            .order_by(City.name)
        )
        return list(result.scalars().all())
