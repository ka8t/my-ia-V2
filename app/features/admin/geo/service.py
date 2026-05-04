"""Service admin pour les donnees geographiques."""
import json
import logging
import os
from typing import Optional, List, Callable, Awaitable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.models import Country, City
from app.features.geo.repository import CountryRepository, CityRepository
from app.features.admin.geo.schemas import (
    ImportResult,
    CountryCreate,
    CountryUpdate,
    GeoStats,
    ExportResult,
    FileInfo,
    GeoFilesStatus
)
from app.features.admin.geo.importer import (
    GeoImporter,
    ProgressCallback,
    get_static_data_dir,
    get_countries_json_path,
    get_cities_json_path
)

logger = logging.getLogger(__name__)


class GeoAdminService:
    """Service admin pour les donnees geographiques."""

    # =========================================================================
    # STATISTICS
    # =========================================================================

    @staticmethod
    async def get_stats(db: AsyncSession) -> GeoStats:
        """Recupere les statistiques geo."""
        # Compter les pays
        countries_total = await CountryRepository.count(db)

        # Compter les pays actifs
        result = await db.execute(
            select(func.count()).select_from(Country).where(Country.is_active == True)
        )
        countries_active = result.scalar() or 0

        # Compter les villes par pays
        result = await db.execute(
            select(City.country_code, func.count(City.id))
            .group_by(City.country_code)
        )
        cities_by_country = dict(result.all())
        cities_total = sum(cities_by_country.values())

        return GeoStats(
            countries_total=countries_total,
            countries_active=countries_active,
            cities_total=cities_total,
            cities_by_country=cities_by_country
        )

    # =========================================================================
    # IMPORT
    # =========================================================================

    @staticmethod
    async def import_countries(
        db: AsyncSession,
        reset: bool = False
    ) -> ImportResult:
        """Importe les pays."""
        return await GeoImporter.import_countries(db, reset)

    @staticmethod
    async def import_cities(
        db: AsyncSession,
        country_code: str,
        reset: bool = False
    ) -> ImportResult:
        """Importe les villes d'un pays."""
        country_code = country_code.upper()

        # Seul FR supporte pour l'instant
        if country_code != "FR":
            return ImportResult(
                success=False,
                entity_type="cities",
                country_code=country_code,
                errors=[f"Import non supporte pour le pays {country_code}. Seul FR est disponible."],
                message=f"Pays {country_code} non supporte"
            )

        return await GeoImporter.import_french_cities(db, reset)

    # =========================================================================
    # CRUD COUNTRIES (admin)
    # =========================================================================

    @staticmethod
    async def get_all_countries(db: AsyncSession):
        """Recupere tous les pays (y compris inactifs)."""
        return await CountryRepository.get_all(db)

    @staticmethod
    async def get_country(db: AsyncSession, code: str) -> Country:
        """Recupere un pays par son code."""
        country = await CountryRepository.get_by_code(db, code)
        if not country:
            raise HTTPException(status_code=404, detail=f"Pays '{code}' non trouve")
        return country

    @staticmethod
    async def create_country(
        db: AsyncSession,
        data: CountryCreate
    ) -> Country:
        """Cree un nouveau pays."""
        existing = await CountryRepository.get_by_code(db, data.code)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Le pays '{data.code}' existe deja"
            )

        country = Country(
            code=data.code.upper(),
            name=data.name,
            flag=data.flag,
            phone_prefix=data.phone_prefix,
            is_active=data.is_active,
            display_order=data.display_order
        )
        return await CountryRepository.create(db, country)

    @staticmethod
    async def update_country(
        db: AsyncSession,
        code: str,
        data: CountryUpdate
    ) -> Country:
        """Met a jour un pays."""
        country = await CountryRepository.get_by_code(db, code)
        if not country:
            raise HTTPException(status_code=404, detail=f"Pays '{code}' non trouve")

        # Mise a jour des champs
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(country, field, value)

        return await CountryRepository.update(db, country)

    @staticmethod
    async def toggle_country_active(
        db: AsyncSession,
        code: str
    ) -> Country:
        """Active/desactive un pays."""
        country = await CountryRepository.get_by_code(db, code)
        if not country:
            raise HTTPException(status_code=404, detail=f"Pays '{code}' non trouve")

        country.is_active = not country.is_active
        return await CountryRepository.update(db, country)

    @staticmethod
    async def delete_country(db: AsyncSession, code: str) -> None:
        """Supprime un pays (et ses villes en cascade)."""
        country = await CountryRepository.get_by_code(db, code)
        if not country:
            raise HTTPException(status_code=404, detail=f"Pays '{code}' non trouve")

        # Avertir si des villes existent
        cities_count = await CityRepository.count(db, code)
        if cities_count > 0:
            logger.warning(
                f"Suppression du pays {code} avec {cities_count} villes associees"
            )

        await CountryRepository.delete(db, country)

    # =========================================================================
    # IMPORT/EXPORT FICHIERS JSON
    # =========================================================================

    @staticmethod
    async def get_files_status(db: AsyncSession) -> GeoFilesStatus:
        """Retourne le statut des fichiers de donnees statiques."""
        static_dir = get_static_data_dir()

        # Info fichier countries.json
        countries_path = get_countries_json_path()
        countries_info = FileInfo(
            filename="countries.json",
            exists=countries_path.exists(),
            filepath=str(countries_path) if countries_path.exists() else None
        )

        if countries_path.exists():
            countries_info.size_bytes = countries_path.stat().st_size
            try:
                with open(countries_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    countries_info.record_count = len(data)
            except Exception:
                pass

        # Info fichiers villes par pays
        cities_files = []
        countries = await CountryRepository.get_all(db)

        for country in countries:
            cities_path = get_cities_json_path(country.code)
            city_info = FileInfo(
                filename=f"{country.code}_cities.json",
                exists=cities_path.exists(),
                filepath=str(cities_path) if cities_path.exists() else None
            )

            if cities_path.exists():
                city_info.size_bytes = cities_path.stat().st_size
                try:
                    with open(cities_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        city_info.record_count = len(data)
                except Exception:
                    pass

            cities_files.append(city_info)

        return GeoFilesStatus(
            static_data_dir=str(static_dir),
            countries_file=countries_info,
            cities_files=cities_files
        )

    @staticmethod
    async def export_countries(db: AsyncSession) -> ExportResult:
        """Exporte les pays vers le fichier JSON."""
        try:
            count, filepath = await GeoImporter.export_countries_to_json(db)
            return ExportResult(
                success=True,
                entity_type="countries",
                exported_count=count,
                filepath=filepath,
                message=f"{count} pays exportes vers {filepath}"
            )
        except Exception as e:
            logger.error(f"Erreur export pays: {e}")
            return ExportResult(
                success=False,
                entity_type="countries",
                message=f"Erreur: {str(e)}"
            )

    @staticmethod
    async def export_cities(
        db: AsyncSession,
        country_code: str
    ) -> ExportResult:
        """Exporte les villes d'un pays vers le fichier JSON."""
        country_code = country_code.upper()

        # Verifier que le pays existe
        country = await CountryRepository.get_by_code(db, country_code)
        if not country:
            return ExportResult(
                success=False,
                entity_type="cities",
                country_code=country_code,
                message=f"Pays {country_code} non trouve"
            )

        try:
            count, filepath = await GeoImporter.export_cities_to_json(db, country_code)
            return ExportResult(
                success=True,
                entity_type="cities",
                country_code=country_code,
                exported_count=count,
                filepath=filepath,
                message=f"{count} villes {country_code} exportees vers {filepath}"
            )
        except Exception as e:
            logger.error(f"Erreur export villes {country_code}: {e}")
            return ExportResult(
                success=False,
                entity_type="cities",
                country_code=country_code,
                message=f"Erreur: {str(e)}"
            )

    @staticmethod
    async def import_countries_from_file(
        db: AsyncSession,
        reset: bool = False
    ) -> ImportResult:
        """Importe les pays depuis le fichier JSON local."""
        return await GeoImporter.import_countries_from_json(db, reset)

    @staticmethod
    async def import_cities_from_file(
        db: AsyncSession,
        country_code: str,
        reset: bool = False
    ) -> ImportResult:
        """Importe les villes depuis le fichier JSON local."""
        return await GeoImporter.import_cities_from_json(db, country_code.upper(), reset)

    @staticmethod
    async def download_and_import_cities(
        db: AsyncSession,
        country_code: str,
        reset: bool = False
    ) -> ImportResult:
        """
        Telecharge les villes depuis l'API externe, les importe,
        puis exporte vers le fichier JSON local.
        """
        country_code = country_code.upper()

        # 1. Import depuis API externe
        if country_code == "FR":
            result = await GeoImporter.import_french_cities(db, reset)
        else:
            return ImportResult(
                success=False,
                entity_type="cities",
                country_code=country_code,
                errors=[f"Telechargement non supporte pour {country_code}"],
                message=f"Seul FR est disponible pour le telechargement"
            )

        # 2. Si succes, exporter vers fichier JSON
        if result.success and result.imported_count > 0:
            try:
                count, filepath = await GeoImporter.export_cities_to_json(db, country_code)
                result.message += f" | Export: {filepath}"
                logger.info(f"Villes {country_code} exportees vers {filepath}")
            except Exception as e:
                logger.warning(f"Export villes {country_code} echoue: {e}")

        return result

    @staticmethod
    async def download_and_import_cities_with_progress(
        db: AsyncSession,
        country_code: str,
        reset: bool = False,
        progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """
        Telecharge les villes depuis l'API externe avec progression.
        """
        country_code = country_code.upper()

        if country_code != "FR":
            return ImportResult(
                success=False,
                entity_type="cities",
                country_code=country_code,
                errors=[f"Telechargement non supporte pour {country_code}"],
                message=f"Seul FR est disponible pour le telechargement"
            )

        result = await GeoImporter.import_french_cities(db, reset, progress_callback)

        # Exporter vers fichier JSON si succes
        if result.success and result.imported_count > 0:
            if progress_callback:
                await progress_callback(result.imported_count, result.imported_count, "saving", "Sauvegarde du fichier JSON...")
            try:
                count, filepath = await GeoImporter.export_cities_to_json(db, country_code)
                result.message += f" | Export: {filepath}"
                logger.info(f"Villes {country_code} exportees vers {filepath}")
            except Exception as e:
                logger.warning(f"Export villes {country_code} echoue: {e}")

        return result

    @staticmethod
    async def import_cities_from_file_with_progress(
        db: AsyncSession,
        country_code: str,
        reset: bool = False,
        progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """
        Importe les villes depuis le fichier JSON avec progression.
        """
        return await GeoImporter.import_cities_from_json(
            db, country_code.upper(), reset, progress_callback
        )
