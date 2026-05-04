"""Importeur de donnees geographiques."""
import json
import logging
import time
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Awaitable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Country, City
from app.features.geo.repository import CountryRepository, CityRepository
from app.features.admin.geo.schemas import ImportResult

# Type pour callback de progression
# Signature: async def callback(current: int, total: int, status: str, message: str)
ProgressCallback = Callable[[int, int, str, str], Awaitable[None]]

logger = logging.getLogger(__name__)


def get_static_data_dir() -> Path:
    """Retourne le chemin du dossier des donnees statiques."""
    return Path(settings.static_data_dir)


def get_countries_json_path() -> Path:
    """Retourne le chemin du fichier JSON des pays."""
    return get_static_data_dir() / "countries.json"


def get_cities_json_path(country_code: str) -> Path:
    """Retourne le chemin du fichier JSON des villes pour un pays."""
    return get_static_data_dir() / f"{country_code}_cities.json"


# =============================================================================
# DONNEES STATIQUES - PAYS ISO 3166-1
# =============================================================================

# Liste des pays avec drapeaux emoji et prefixes telephoniques
# Format: (code, nom, drapeau, prefixe, ordre_affichage)
COUNTRIES_DATA: List[Tuple[str, str, str, str, int]] = [
    # Pays prioritaires (ordre d'affichage bas = en premier)
    ("FR", "France", "\U0001F1EB\U0001F1F7", "+33", 1),
    ("BE", "Belgique", "\U0001F1E7\U0001F1EA", "+32", 2),
    ("CH", "Suisse", "\U0001F1E8\U0001F1ED", "+41", 3),
    ("LU", "Luxembourg", "\U0001F1F1\U0001F1FA", "+352", 4),
    ("MC", "Monaco", "\U0001F1F2\U0001F1E8", "+377", 5),
    ("CA", "Canada", "\U0001F1E8\U0001F1E6", "+1", 6),

    # Europe
    ("DE", "Allemagne", "\U0001F1E9\U0001F1EA", "+49", 10),
    ("ES", "Espagne", "\U0001F1EA\U0001F1F8", "+34", 11),
    ("IT", "Italie", "\U0001F1EE\U0001F1F9", "+39", 12),
    ("GB", "Royaume-Uni", "\U0001F1EC\U0001F1E7", "+44", 13),
    ("NL", "Pays-Bas", "\U0001F1F3\U0001F1F1", "+31", 14),
    ("PT", "Portugal", "\U0001F1F5\U0001F1F9", "+351", 15),
    ("AT", "Autriche", "\U0001F1E6\U0001F1F9", "+43", 16),
    ("PL", "Pologne", "\U0001F1F5\U0001F1F1", "+48", 17),
    ("SE", "Suede", "\U0001F1F8\U0001F1EA", "+46", 18),
    ("NO", "Norvege", "\U0001F1F3\U0001F1F4", "+47", 19),
    ("DK", "Danemark", "\U0001F1E9\U0001F1F0", "+45", 20),
    ("FI", "Finlande", "\U0001F1EB\U0001F1EE", "+358", 21),
    ("IE", "Irlande", "\U0001F1EE\U0001F1EA", "+353", 22),
    ("GR", "Grece", "\U0001F1EC\U0001F1F7", "+30", 23),
    ("CZ", "Republique tcheque", "\U0001F1E8\U0001F1FF", "+420", 24),
    ("RO", "Roumanie", "\U0001F1F7\U0001F1F4", "+40", 25),
    ("HU", "Hongrie", "\U0001F1ED\U0001F1FA", "+36", 26),
    ("SK", "Slovaquie", "\U0001F1F8\U0001F1F0", "+421", 27),
    ("BG", "Bulgarie", "\U0001F1E7\U0001F1EC", "+359", 28),
    ("HR", "Croatie", "\U0001F1ED\U0001F1F7", "+385", 29),
    ("SI", "Slovenie", "\U0001F1F8\U0001F1EE", "+386", 30),
    ("LT", "Lituanie", "\U0001F1F1\U0001F1F9", "+370", 31),
    ("LV", "Lettonie", "\U0001F1F1\U0001F1FB", "+371", 32),
    ("EE", "Estonie", "\U0001F1EA\U0001F1EA", "+372", 33),
    ("CY", "Chypre", "\U0001F1E8\U0001F1FE", "+357", 34),
    ("MT", "Malte", "\U0001F1F2\U0001F1F9", "+356", 35),

    # Amerique
    ("US", "Etats-Unis", "\U0001F1FA\U0001F1F8", "+1", 50),
    ("MX", "Mexique", "\U0001F1F2\U0001F1FD", "+52", 51),
    ("BR", "Bresil", "\U0001F1E7\U0001F1F7", "+55", 52),
    ("AR", "Argentine", "\U0001F1E6\U0001F1F7", "+54", 53),
    ("CL", "Chili", "\U0001F1E8\U0001F1F1", "+56", 54),
    ("CO", "Colombie", "\U0001F1E8\U0001F1F4", "+57", 55),
    ("PE", "Perou", "\U0001F1F5\U0001F1EA", "+51", 56),

    # Asie
    ("CN", "Chine", "\U0001F1E8\U0001F1F3", "+86", 70),
    ("JP", "Japon", "\U0001F1EF\U0001F1F5", "+81", 71),
    ("KR", "Coree du Sud", "\U0001F1F0\U0001F1F7", "+82", 72),
    ("IN", "Inde", "\U0001F1EE\U0001F1F3", "+91", 73),
    ("TH", "Thailande", "\U0001F1F9\U0001F1ED", "+66", 74),
    ("VN", "Vietnam", "\U0001F1FB\U0001F1F3", "+84", 75),
    ("SG", "Singapour", "\U0001F1F8\U0001F1EC", "+65", 76),
    ("MY", "Malaisie", "\U0001F1F2\U0001F1FE", "+60", 77),
    ("ID", "Indonesie", "\U0001F1EE\U0001F1E9", "+62", 78),
    ("PH", "Philippines", "\U0001F1F5\U0001F1ED", "+63", 79),

    # Afrique
    ("MA", "Maroc", "\U0001F1F2\U0001F1E6", "+212", 90),
    ("DZ", "Algerie", "\U0001F1E9\U0001F1FF", "+213", 91),
    ("TN", "Tunisie", "\U0001F1F9\U0001F1F3", "+216", 92),
    ("SN", "Senegal", "\U0001F1F8\U0001F1F3", "+221", 93),
    ("CI", "Cote d'Ivoire", "\U0001F1E8\U0001F1EE", "+225", 94),
    ("ZA", "Afrique du Sud", "\U0001F1FF\U0001F1E6", "+27", 95),
    ("EG", "Egypte", "\U0001F1EA\U0001F1EC", "+20", 96),
    ("NG", "Nigeria", "\U0001F1F3\U0001F1EC", "+234", 97),

    # Oceanie
    ("AU", "Australie", "\U0001F1E6\U0001F1FA", "+61", 100),
    ("NZ", "Nouvelle-Zelande", "\U0001F1F3\U0001F1FF", "+64", 101),

    # Moyen-Orient
    ("AE", "Emirats arabes unis", "\U0001F1E6\U0001F1EA", "+971", 110),
    ("SA", "Arabie saoudite", "\U0001F1F8\U0001F1E6", "+966", 111),
    ("IL", "Israel", "\U0001F1EE\U0001F1F1", "+972", 112),
    ("TR", "Turquie", "\U0001F1F9\U0001F1F7", "+90", 113),

    # Autres
    ("RU", "Russie", "\U0001F1F7\U0001F1FA", "+7", 120),
]


def normalize_text(text: str) -> str:
    """Normalise le texte (sans accents, minuscules)."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    return ascii_text.lower().strip()


class GeoImporter:
    """Importeur de donnees geographiques."""

    # =========================================================================
    # IMPORT PAYS
    # =========================================================================

    @staticmethod
    async def import_countries(
        db: AsyncSession,
        reset: bool = False
    ) -> ImportResult:
        """Importe les pays depuis la liste statique."""
        start_time = time.time()
        result = ImportResult(
            success=True,
            entity_type="countries"
        )

        try:
            if reset:
                # Supprimer tous les pays existants
                existing_count = await CountryRepository.count(db)
                logger.info(f"Suppression de {existing_count} pays existants")
                # Note: CASCADE supprimera aussi les villes associees

            imported = 0
            skipped = 0

            for code, name, flag, phone_prefix, display_order in COUNTRIES_DATA:
                existing = await CountryRepository.get_by_code(db, code)

                if existing and not reset:
                    skipped += 1
                    continue

                if existing and reset:
                    await CountryRepository.delete(db, existing)

                country = Country(
                    code=code,
                    name=name,
                    flag=flag,
                    phone_prefix=phone_prefix,
                    is_active=True,
                    display_order=display_order
                )
                await CountryRepository.create(db, country)
                imported += 1

            result.imported_count = imported
            result.skipped_count = skipped
            result.duration_seconds = round(time.time() - start_time, 2)
            result.message = f"{imported} pays importes, {skipped} ignores"

            logger.info(f"Import pays termine: {result.message}")

        except Exception as e:
            result.success = False
            result.error_count = 1
            result.errors = [str(e)]
            result.message = f"Erreur: {str(e)}"
            logger.error(f"Erreur import pays: {e}")

        return result

    # =========================================================================
    # IMPORT VILLES FRANCE (api.gouv.fr)
    # =========================================================================

    @staticmethod
    async def import_french_cities(
        db: AsyncSession,
        reset: bool = False,
        progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """Importe les villes francaises depuis api.gouv.fr."""
        start_time = time.time()
        result = ImportResult(
            success=True,
            entity_type="cities",
            country_code="FR"
        )

        async def report_progress(current: int, total: int, status: str, message: str):
            """Rapporte la progression si callback fourni."""
            if progress_callback:
                await progress_callback(current, total, status, message)

        try:
            # Verifier que le pays FR existe
            france = await CountryRepository.get_by_code(db, "FR")
            if not france:
                result.success = False
                result.errors = ["Pays FR non trouve. Importez d'abord les pays."]
                result.message = result.errors[0]
                return result

            # Verifier si des villes existent deja (protection anti-doublons)
            existing_count = await CityRepository.count(db, "FR")
            if existing_count > 0 and not reset:
                result.success = False
                result.errors = [
                    f"{existing_count} villes FR existent deja. "
                    "Utilisez reset=True pour reimporter."
                ]
                result.message = result.errors[0]
                result.skipped_count = existing_count
                logger.warning(f"Import annule: {existing_count} villes FR existent deja")
                return result

            await report_progress(0, 0, "downloading", "Telechargement depuis api.gouv.fr...")

            if reset and existing_count > 0:
                deleted = await CityRepository.delete_by_country(db, "FR")
                logger.info(f"Suppression de {deleted} villes FR existantes")

            # Appel API geo.api.gouv.fr
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    "https://geo.api.gouv.fr/communes",
                    params={
                        "fields": "nom,code,codesPostaux,codeDepartement,departement,codeRegion,region,population,centre",
                        "format": "json",
                        "geometry": "centre"
                    }
                )
                response.raise_for_status()
                communes = response.json()

            logger.info(f"Recupere {len(communes)} communes depuis api.gouv.fr")
            await report_progress(0, len(communes), "importing", f"Traitement de {len(communes)} communes...")

            # Traiter chaque commune
            cities_to_create = []
            for idx, commune in enumerate(communes):
                try:
                    # Une commune peut avoir plusieurs codes postaux
                    codes_postaux = commune.get("codesPostaux", [])
                    if not codes_postaux:
                        continue

                    nom = commune.get("nom", "")
                    code_dept = commune.get("codeDepartement", "")
                    dept_info = commune.get("departement", {})
                    region_info = commune.get("region", {})
                    population = commune.get("population", 0)
                    centre = commune.get("centre", {})
                    coords = centre.get("coordinates", [None, None]) if centre else [None, None]

                    # Creer une entree par code postal
                    for cp in codes_postaux:
                        city = City(
                            name=nom,
                            postal_code=cp,
                            country_code="FR",
                            department_code=code_dept,
                            department_name=dept_info.get("nom") if isinstance(dept_info, dict) else None,
                            region_name=region_info.get("nom") if isinstance(region_info, dict) else None,
                            latitude=coords[1] if coords and len(coords) > 1 else None,
                            longitude=coords[0] if coords else None,
                            population=population,
                            search_name=normalize_text(nom)
                        )
                        cities_to_create.append(city)

                except Exception as e:
                    result.error_count += 1
                    if len(result.errors) < 10:
                        result.errors.append(f"Erreur commune {commune.get('nom', '?')}: {e}")

            total_cities = len(cities_to_create)
            await report_progress(0, total_cities, "importing", f"Import de {total_cities} villes...")

            # Import par batch pour performance
            batch_size = 500
            for i in range(0, total_cities, batch_size):
                batch = cities_to_create[i:i + batch_size]
                await CityRepository.create_batch(db, batch)
                result.imported_count += len(batch)
                logger.info(f"Batch {i//batch_size + 1}: {len(batch)} villes importees")
                await report_progress(result.imported_count, total_cities, "importing",
                                      f"Import: {result.imported_count}/{total_cities}")

            result.duration_seconds = round(time.time() - start_time, 2)
            result.message = f"{result.imported_count} villes importees en {result.duration_seconds}s"

            if result.error_count > 0:
                result.message += f" ({result.error_count} erreurs)"

            logger.info(f"Import villes FR termine: {result.message}")

        except httpx.HTTPError as e:
            result.success = False
            result.error_count = 1
            result.errors = [f"Erreur API: {str(e)}"]
            result.message = result.errors[0]
            logger.error(f"Erreur HTTP import villes: {e}")

        except Exception as e:
            result.success = False
            result.error_count = 1
            result.errors = [str(e)]
            result.message = f"Erreur: {str(e)}"
            logger.error(f"Erreur import villes: {e}")

        return result

    # =========================================================================
    # EXPORT/IMPORT FICHIERS JSON
    # =========================================================================

    @staticmethod
    async def export_countries_to_json(db: AsyncSession) -> Tuple[int, str]:
        """
        Exporte les pays vers le fichier JSON.

        Returns:
            Tuple[int, str]: (nombre de pays exportes, chemin du fichier)
        """
        filepath = get_countries_json_path()
        countries = await CountryRepository.get_all(db)

        data = [
            {
                "code": c.code,
                "name": c.name,
                "flag": c.flag,
                "phone_prefix": c.phone_prefix,
                "display_order": c.display_order
            }
            for c in countries
        ]

        # Creer le dossier si necessaire
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Export {len(data)} pays vers {filepath}")
        return len(data), str(filepath)

    @staticmethod
    async def import_countries_from_json(
        db: AsyncSession,
        reset: bool = False
    ) -> ImportResult:
        """
        Importe les pays depuis le fichier JSON local.

        Args:
            db: Session de base de donnees
            reset: Si True, supprime les pays existants avant import
        """
        start_time = time.time()
        result = ImportResult(
            success=True,
            entity_type="countries"
        )

        filepath = get_countries_json_path()

        if not filepath.exists():
            result.success = False
            result.errors = [f"Fichier non trouve: {filepath}"]
            result.message = result.errors[0]
            return result

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                countries_data = json.load(f)

            if reset:
                existing_count = await CountryRepository.count(db)
                logger.info(f"Suppression de {existing_count} pays existants")
                # Supprimer tous les pays (CASCADE sur villes)
                all_countries = await CountryRepository.get_all(db)
                for country in all_countries:
                    await CountryRepository.delete(db, country)

            imported = 0
            skipped = 0

            for country_dict in countries_data:
                code = country_dict.get("code")
                existing = await CountryRepository.get_by_code(db, code)

                if existing and not reset:
                    skipped += 1
                    continue

                country = Country(
                    code=code,
                    name=country_dict.get("name"),
                    flag=country_dict.get("flag"),
                    phone_prefix=country_dict.get("phone_prefix"),
                    is_active=True,
                    display_order=country_dict.get("display_order", 999)
                )
                await CountryRepository.create(db, country)
                imported += 1

            result.imported_count = imported
            result.skipped_count = skipped
            result.duration_seconds = round(time.time() - start_time, 2)
            result.message = f"{imported} pays importes depuis fichier, {skipped} ignores"

            logger.info(f"Import pays depuis JSON termine: {result.message}")

        except json.JSONDecodeError as e:
            result.success = False
            result.errors = [f"Erreur JSON: {str(e)}"]
            result.message = result.errors[0]
            logger.error(f"Erreur lecture JSON pays: {e}")

        except Exception as e:
            result.success = False
            result.errors = [str(e)]
            result.message = f"Erreur: {str(e)}"
            logger.error(f"Erreur import pays depuis JSON: {e}")

        return result

    @staticmethod
    async def export_cities_to_json(
        db: AsyncSession,
        country_code: str
    ) -> Tuple[int, str]:
        """
        Exporte les villes d'un pays vers un fichier JSON.

        Args:
            db: Session de base de donnees
            country_code: Code ISO du pays

        Returns:
            Tuple[int, str]: (nombre de villes exportees, chemin du fichier)
        """
        filepath = get_cities_json_path(country_code)

        # Recuperer toutes les villes du pays
        cities = await CityRepository.get_all_by_country(db, country_code)

        data = [
            {
                "name": c.name,
                "postal_code": c.postal_code,
                "country_code": c.country_code,
                "department_code": c.department_code,
                "department_name": c.department_name,
                "region_name": c.region_name,
                "latitude": float(c.latitude) if c.latitude is not None else None,
                "longitude": float(c.longitude) if c.longitude is not None else None,
                "population": c.population,
                "search_name": c.search_name
            }
            for c in cities
        ]

        # Creer le dossier si necessaire
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Export {len(data)} villes {country_code} vers {filepath}")
        return len(data), str(filepath)

    @staticmethod
    async def import_cities_from_json(
        db: AsyncSession,
        country_code: str,
        reset: bool = False,
        progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """
        Importe les villes depuis un fichier JSON local.

        Args:
            db: Session de base de donnees
            country_code: Code ISO du pays
            reset: Si True, supprime les villes existantes avant import
            progress_callback: Callback pour rapporter la progression
        """
        start_time = time.time()
        result = ImportResult(
            success=True,
            entity_type="cities",
            country_code=country_code
        )

        async def report_progress(current: int, total: int, status: str, message: str):
            """Rapporte la progression si callback fourni."""
            if progress_callback:
                await progress_callback(current, total, status, message)

        filepath = get_cities_json_path(country_code)

        if not filepath.exists():
            result.success = False
            result.errors = [f"Fichier non trouve: {filepath}"]
            result.message = result.errors[0]
            return result

        try:
            # Verifier que le pays existe
            country = await CountryRepository.get_by_code(db, country_code)
            if not country:
                result.success = False
                result.errors = [f"Pays {country_code} non trouve. Importez d'abord les pays."]
                result.message = result.errors[0]
                return result

            # Verifier si des villes existent deja (protection anti-doublons)
            existing_count = await CityRepository.count(db, country_code)
            if existing_count > 0 and not reset:
                result.success = False
                result.errors = [
                    f"{existing_count} villes {country_code} existent deja. "
                    "Utilisez reset=True pour reimporter."
                ]
                result.message = result.errors[0]
                result.skipped_count = existing_count
                logger.warning(f"Import annule: {existing_count} villes {country_code} existent deja")
                return result

            await report_progress(0, 0, "loading", "Chargement du fichier JSON...")

            with open(filepath, "r", encoding="utf-8") as f:
                cities_data = json.load(f)

            if reset and existing_count > 0:
                await report_progress(0, 0, "cleaning", "Suppression des villes existantes...")
                deleted = await CityRepository.delete_by_country(db, country_code)
                logger.info(f"Suppression de {deleted} villes {country_code} existantes")

            total_cities = len(cities_data)
            await report_progress(0, total_cities, "importing", f"Import de {total_cities} villes...")

            # Creer les villes par batch
            cities_to_create = []
            for city_dict in cities_data:
                city = City(
                    name=city_dict.get("name"),
                    postal_code=city_dict.get("postal_code"),
                    country_code=city_dict.get("country_code", country_code),
                    department_code=city_dict.get("department_code"),
                    department_name=city_dict.get("department_name"),
                    region_name=city_dict.get("region_name"),
                    latitude=city_dict.get("latitude"),
                    longitude=city_dict.get("longitude"),
                    population=city_dict.get("population"),
                    search_name=city_dict.get("search_name")
                )
                cities_to_create.append(city)

            # Import par batch
            batch_size = 500
            for i in range(0, len(cities_to_create), batch_size):
                batch = cities_to_create[i:i + batch_size]
                await CityRepository.create_batch(db, batch)
                result.imported_count += len(batch)
                await report_progress(result.imported_count, total_cities, "importing",
                                      f"Import: {result.imported_count}/{total_cities}")

            result.duration_seconds = round(time.time() - start_time, 2)
            result.message = f"{result.imported_count} villes importees depuis fichier en {result.duration_seconds}s"

            logger.info(f"Import villes {country_code} depuis JSON termine: {result.message}")

        except json.JSONDecodeError as e:
            result.success = False
            result.errors = [f"Erreur JSON: {str(e)}"]
            result.message = result.errors[0]
            logger.error(f"Erreur lecture JSON villes: {e}")

        except Exception as e:
            result.success = False
            result.errors = [str(e)]
            result.message = f"Erreur: {str(e)}"
            logger.error(f"Erreur import villes depuis JSON: {e}")

        return result

    @staticmethod
    def countries_json_exists() -> bool:
        """Verifie si le fichier countries.json existe."""
        return get_countries_json_path().exists()

    @staticmethod
    def cities_json_exists(country_code: str) -> bool:
        """Verifie si le fichier {country_code}_cities.json existe."""
        return get_cities_json_path(country_code).exists()
