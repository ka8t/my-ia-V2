"""
Schemas Admin Export

Schémas Pydantic pour l'export de données.
"""
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum

from pydantic import BaseModel, Field


class ExportFormat(str, Enum):
    """Formats d'export disponibles"""
    CSV = "csv"
    JSON = "json"


class ExportFilter(BaseModel):
    """Filtres pour l'export"""
    created_after: Optional[datetime] = Field(None, description="Créé après cette date")
    created_before: Optional[datetime] = Field(None, description="Créé avant cette date")
    limit: int = Field(default=1000, ge=1, le=10000, description="Nombre max d'éléments")


class ExportResult(BaseModel):
    """Résultat d'un export"""
    filename: str = Field(..., description="Nom du fichier généré")
    format: ExportFormat = Field(..., description="Format du fichier")
    records_count: int = Field(..., description="Nombre d'enregistrements exportés")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
