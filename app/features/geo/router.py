"""Endpoints publics pour les donnees geographiques."""
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.features.geo.service import GeoService
from app.features.geo.schemas import (
    CountryListItem,
    CityListItem,
    CityRead
)

router = APIRouter()


# =============================================================================
# ENDPOINTS COUNTRIES
# =============================================================================

@router.get(
    "/countries",
    response_model=List[CountryListItem],
    summary="Liste des pays actifs"
)
async def list_countries(
    db: AsyncSession = Depends(get_db)
) -> List[CountryListItem]:
    """
    Retourne la liste des pays actifs pour selection.

    Les pays sont tries par ordre d'affichage (France en premier).
    """
    return await GeoService.get_countries(db)


@router.get(
    "/countries/{code}",
    response_model=CountryListItem,
    summary="Detail d'un pays"
)
async def get_country(
    code: str,
    db: AsyncSession = Depends(get_db)
) -> CountryListItem:
    """Recupere les details d'un pays par son code ISO."""
    country = await GeoService.get_country(db, code)
    return CountryListItem.model_validate(country)


# =============================================================================
# ENDPOINTS CITIES
# =============================================================================

@router.get(
    "/cities",
    response_model=List[CityListItem],
    summary="Recherche de villes"
)
async def search_cities(
    q: str = Query(..., min_length=2, max_length=100, description="Terme de recherche"),
    country: str = Query("FR", min_length=2, max_length=2, description="Code pays"),
    limit: int = Query(20, ge=1, le=100, description="Nombre max de resultats"),
    db: AsyncSession = Depends(get_db)
) -> List[CityListItem]:
    """
    Recherche des villes par nom ou code postal.

    - **q**: Terme de recherche (nom de ville ou debut de code postal)
    - **country**: Code ISO du pays (defaut: FR)
    - **limit**: Nombre maximum de resultats (defaut: 20)

    Les resultats sont tries par population decroissante.
    """
    return await GeoService.search_cities(db, q, country, limit)


@router.get(
    "/cities/{city_id}",
    response_model=CityRead,
    summary="Detail d'une ville"
)
async def get_city(
    city_id: int,
    db: AsyncSession = Depends(get_db)
) -> CityRead:
    """Recupere les details d'une ville par son ID."""
    city = await GeoService.get_city(db, city_id)
    return CityRead.model_validate(city)


@router.get(
    "/cities/by-postal-code/{postal_code}",
    response_model=List[CityListItem],
    summary="Villes par code postal"
)
async def get_cities_by_postal_code(
    postal_code: str,
    country: str = Query("FR", min_length=2, max_length=2, description="Code pays"),
    db: AsyncSession = Depends(get_db)
) -> List[CityListItem]:
    """
    Recupere les villes correspondant a un code postal.

    Un code postal peut correspondre a plusieurs villes.
    """
    return await GeoService.get_cities_by_postal_code(db, postal_code, country)
