"""Schemas Pydantic pour l'import geo admin."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ImportStatus(BaseModel):
    """Statut d'une importation."""
    entity_type: str = Field(..., description="Type d'entite (countries, cities)")
    country_code: Optional[str] = Field(None, description="Code pays (pour villes)")
    status: str = Field(..., description="Status: pending, running, completed, failed")
    total_count: int = Field(0, description="Nombre total d'elements")
    imported_count: int = Field(0, description="Nombre d'elements importes")
    error_count: int = Field(0, description="Nombre d'erreurs")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ImportCountriesRequest(BaseModel):
    """Requete d'import des pays."""
    reset: bool = Field(False, description="Supprimer les pays existants avant import")


class ImportCitiesRequest(BaseModel):
    """Requete d'import des villes."""
    country_code: str = Field("FR", min_length=2, max_length=2, description="Code pays")
    reset: bool = Field(False, description="Supprimer les villes existantes avant import")


class ImportResult(BaseModel):
    """Resultat d'une importation."""
    success: bool
    entity_type: str
    country_code: Optional[str] = None
    imported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: List[str] = []
    duration_seconds: float = 0.0
    message: str = ""


class CountryCreate(BaseModel):
    """Schema creation Country (admin)."""
    code: str = Field(..., min_length=2, max_length=2, description="Code ISO")
    name: str = Field(..., min_length=1, max_length=100)
    flag: str = Field(..., min_length=1, max_length=10)
    phone_prefix: Optional[str] = Field(None, max_length=5)
    is_active: bool = True
    display_order: int = 999


class CountryUpdate(BaseModel):
    """Schema mise a jour Country (admin)."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    flag: Optional[str] = Field(None, min_length=1, max_length=10)
    phone_prefix: Optional[str] = Field(None, max_length=5)
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class CountryAdminRead(BaseModel):
    """Schema lecture Country (admin, avec tous les champs)."""
    code: str
    name: str
    flag: str
    phone_prefix: Optional[str] = None
    is_active: bool
    display_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class GeoStats(BaseModel):
    """Statistiques geo."""
    countries_total: int = 0
    countries_active: int = 0
    cities_total: int = 0
    cities_by_country: dict = {}


class ImportSource(BaseModel):
    """Source d'import (fichier local ou API externe)."""
    source: str = Field("api", description="Source: 'file' (JSON local) ou 'api' (API externe)")
    reset: bool = Field(False, description="Supprimer les donnees existantes avant import")


class ImportCountriesFromFileRequest(BaseModel):
    """Requete d'import des pays depuis fichier JSON."""
    reset: bool = Field(False, description="Supprimer les pays existants avant import")


class ImportCitiesFromFileRequest(BaseModel):
    """Requete d'import des villes depuis fichier JSON."""
    country_code: str = Field("FR", min_length=2, max_length=2, description="Code pays")
    reset: bool = Field(False, description="Supprimer les villes existantes avant import")


class ExportResult(BaseModel):
    """Resultat d'un export vers fichier."""
    success: bool
    entity_type: str
    country_code: Optional[str] = None
    exported_count: int = 0
    filepath: str = ""
    message: str = ""


class FileInfo(BaseModel):
    """Informations sur un fichier de donnees statiques."""
    filename: str
    exists: bool
    filepath: Optional[str] = None
    size_bytes: Optional[int] = None
    record_count: Optional[int] = None


class GeoFilesStatus(BaseModel):
    """Statut des fichiers de donnees geographiques."""
    static_data_dir: str
    countries_file: FileInfo
    cities_files: List[FileInfo] = []


class ImportProgress(BaseModel):
    """Progression d'une importation (pour SSE)."""
    event: str = Field(..., description="Type: progress, complete, error")
    progress: int = Field(0, ge=0, le=100, description="Pourcentage 0-100")
    current: int = Field(0, description="Nombre d'elements traites")
    total: int = Field(0, description="Nombre total d'elements")
    status: str = Field("pending", description="pending, downloading, importing, saving, complete, error")
    message: str = Field("", description="Message de statut")
    # Champs pour event=complete
    success: Optional[bool] = None
    imported_count: Optional[int] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None


class StreamImportRequest(BaseModel):
    """Requete d'import avec streaming de progression."""
    country_code: str = Field("FR", min_length=2, max_length=2, description="Code pays")
    source: str = Field("file", description="Source: 'file' (JSON local) ou 'api' (API externe)")
    reset: bool = Field(True, description="Supprimer les villes existantes avant import")
