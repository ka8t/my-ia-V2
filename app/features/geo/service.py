"""Service pour les donnees geographiques."""
import logging
from typing import Optional, List

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Country, City
from app.features.geo.repository import CountryRepository, CityRepository
from app.features.geo.schemas import CountryListItem, CityListItem

logger = logging.getLogger(__name__)


class GeoService:
    """Service pour les donnees geographiques."""

    # =========================================================================
    # COUNTRIES
    # =========================================================================

    @staticmethod
    async def get_countries(db: AsyncSession) -> List[CountryListItem]:
        """Recupere la liste des pays actifs pour affichage."""
        countries = await CountryRepository.get_all_active(db)
        return [CountryListItem.model_validate(c) for c in countries]

    @staticmethod
    async def get_country(db: AsyncSession, code: str) -> Country:
        """Recupere un pays par son code."""
        country = await CountryRepository.get_by_code(db, code)
        if not country:
            raise HTTPException(status_code=404, detail=f"Pays '{code}' non trouve")
        return country

    # =========================================================================
    # CITIES
    # =========================================================================

    @staticmethod
    async def search_cities(
        db: AsyncSession,
        query: str,
        country_code: str = "FR",
        limit: int = 20
    ) -> List[CityListItem]:
        """Recherche des villes par nom ou code postal."""
        if len(query) < 2:
            return []

        cities = await CityRepository.search(db, query, country_code, limit)
        return [CityListItem.from_city(c) for c in cities]

    @staticmethod
    async def get_city(db: AsyncSession, city_id: int) -> City:
        """Recupere une ville par son ID."""
        city = await CityRepository.get_by_id(db, city_id)
        if not city:
            raise HTTPException(status_code=404, detail=f"Ville ID {city_id} non trouvee")
        return city

    @staticmethod
    async def get_cities_by_postal_code(
        db: AsyncSession,
        postal_code: str,
        country_code: str = "FR"
    ) -> List[CityListItem]:
        """Recupere les villes par code postal."""
        cities = await CityRepository.get_by_postal_code(db, postal_code, country_code)
        return [CityListItem.from_city(c) for c in cities]
