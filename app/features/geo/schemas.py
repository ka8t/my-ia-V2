"""Schemas Pydantic pour le module geo."""
from typing import Optional, List
from pydantic import BaseModel, Field


# =============================================================================
# COUNTRY SCHEMAS
# =============================================================================

class CountryBase(BaseModel):
    """Base schema pour Country."""
    code: str = Field(..., min_length=2, max_length=2, description="Code ISO 3166-1 alpha-2")
    name: str = Field(..., min_length=1, max_length=100, description="Nom du pays")
    flag: str = Field(..., min_length=1, max_length=10, description="Emoji drapeau")
    phone_prefix: Optional[str] = Field(None, max_length=5, description="Prefixe telephonique")


class CountryRead(CountryBase):
    """Schema lecture Country."""
    is_active: bool = True
    display_order: int = 999

    class Config:
        from_attributes = True


class CountryListItem(BaseModel):
    """Schema simplifie pour liste deroulante."""
    code: str
    name: str
    flag: str
    phone_prefix: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================================
# CITY SCHEMAS
# =============================================================================

class CityBase(BaseModel):
    """Base schema pour City."""
    name: str = Field(..., min_length=1, max_length=200, description="Nom de la ville")
    postal_code: str = Field(..., min_length=1, max_length=10, description="Code postal")
    country_code: str = Field(..., min_length=2, max_length=2, description="Code pays")


class CityRead(CityBase):
    """Schema lecture City."""
    id: int
    department_code: Optional[str] = None
    department_name: Optional[str] = None
    region_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    population: Optional[int] = None

    class Config:
        from_attributes = True


class CityListItem(BaseModel):
    """Schema simplifie pour autocomplete."""
    id: int
    name: str
    postal_code: str
    department_name: Optional[str] = None
    display: str = ""  # Format: "Ville (CP) - Departement"

    class Config:
        from_attributes = True

    @classmethod
    def from_city(cls, city) -> "CityListItem":
        """Cree un item de liste depuis un objet City."""
        dept = f" - {city.department_name}" if city.department_name else ""
        display = f"{city.name} ({city.postal_code}){dept}"
        return cls(
            id=city.id,
            name=city.name,
            postal_code=city.postal_code,
            department_name=city.department_name,
            display=display
        )


class CitySearchParams(BaseModel):
    """Parametres de recherche ville."""
    q: str = Field(..., min_length=2, max_length=100, description="Terme de recherche")
    country_code: str = Field("FR", min_length=2, max_length=2, description="Code pays")
    limit: int = Field(20, ge=1, le=100, description="Nombre max de resultats")
