"""Endpoints admin pour les donnees geographiques."""
import asyncio
import json
import logging
from typing import List, AsyncGenerator

from fastapi import APIRouter, Depends, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user
from app.models import User
from app.features.admin.geo.service import GeoAdminService
from app.features.admin.geo.schemas import (
    ImportResult,
    ImportCountriesRequest,
    ImportCitiesRequest,
    ImportCountriesFromFileRequest,
    ImportCitiesFromFileRequest,
    CountryCreate,
    CountryUpdate,
    CountryAdminRead,
    GeoStats,
    ExportResult,
    GeoFilesStatus,
    ImportProgress,
    StreamImportRequest
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# STATISTICS
# =============================================================================

@router.get(
    "/stats",
    response_model=GeoStats,
    summary="Statistiques geo"
)
async def get_geo_stats(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> GeoStats:
    """Retourne les statistiques des donnees geographiques."""
    return await GeoAdminService.get_stats(db)


# =============================================================================
# IMPORT ENDPOINTS
# =============================================================================

@router.post(
    "/import/countries",
    response_model=ImportResult,
    summary="Importer les pays"
)
async def import_countries(
    request: ImportCountriesRequest = None,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ImportResult:
    """
    Importe les pays depuis la liste statique.

    - **reset**: Si true, supprime tous les pays existants avant import
    """
    reset = request.reset if request else False
    return await GeoAdminService.import_countries(db, reset)


@router.post(
    "/import/cities",
    response_model=ImportResult,
    summary="Importer les villes"
)
async def import_cities(
    request: ImportCitiesRequest = None,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ImportResult:
    """
    Importe les villes depuis une API externe.

    - **country_code**: Code ISO du pays (defaut: FR, seul supporte)
    - **reset**: Si true, supprime les villes existantes du pays avant import

    Pour la France, utilise api.gouv.fr (~35000 villes).
    """
    country_code = request.country_code if request else "FR"
    reset = request.reset if request else False
    return await GeoAdminService.import_cities(db, country_code, reset)


# =============================================================================
# IMPORT/EXPORT FICHIERS JSON
# =============================================================================

@router.get(
    "/files/status",
    response_model=GeoFilesStatus,
    summary="Statut des fichiers de donnees"
)
async def get_files_status(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> GeoFilesStatus:
    """Retourne le statut des fichiers JSON de donnees geographiques."""
    return await GeoAdminService.get_files_status(db)


@router.post(
    "/export/countries",
    response_model=ExportResult,
    summary="Exporter les pays vers fichier"
)
async def export_countries(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ExportResult:
    """Exporte les pays de la base vers le fichier countries.json."""
    return await GeoAdminService.export_countries(db)


@router.post(
    "/export/cities/{country_code}",
    response_model=ExportResult,
    summary="Exporter les villes vers fichier"
)
async def export_cities(
    country_code: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ExportResult:
    """Exporte les villes d'un pays vers le fichier {CODE}_cities.json."""
    return await GeoAdminService.export_cities(db, country_code)


@router.post(
    "/import/countries/file",
    response_model=ImportResult,
    summary="Importer les pays depuis fichier"
)
async def import_countries_from_file(
    request: ImportCountriesFromFileRequest = None,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ImportResult:
    """
    Importe les pays depuis le fichier countries.json local.

    - **reset**: Si true, supprime les pays existants avant import
    """
    reset = request.reset if request else False
    return await GeoAdminService.import_countries_from_file(db, reset)


@router.post(
    "/import/cities/file",
    response_model=ImportResult,
    summary="Importer les villes depuis fichier"
)
async def import_cities_from_file(
    request: ImportCitiesFromFileRequest = None,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ImportResult:
    """
    Importe les villes depuis le fichier {CODE}_cities.json local.

    - **country_code**: Code ISO du pays (defaut: FR)
    - **reset**: Si true, supprime les villes existantes avant import
    """
    country_code = request.country_code if request else "FR"
    reset = request.reset if request else False
    return await GeoAdminService.import_cities_from_file(db, country_code, reset)


@router.post(
    "/download/cities/{country_code}",
    response_model=ImportResult,
    summary="Telecharger et importer les villes"
)
async def download_and_import_cities(
    country_code: str,
    reset: bool = Query(False, description="Supprimer les villes existantes avant import"),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> ImportResult:
    """
    Telecharge les villes depuis l'API externe, les importe en base,
    puis les sauvegarde dans le fichier JSON local.

    - **country_code**: Code ISO du pays (seul FR supporte)
    - **reset**: Si true, supprime les villes existantes avant import
    """
    return await GeoAdminService.download_and_import_cities(db, country_code, reset)


# =============================================================================
# IMPORT AVEC STREAMING SSE
# =============================================================================

@router.post(
    "/import/cities/stream",
    summary="Importer les villes avec progression SSE"
)
async def import_cities_stream(
    request: StreamImportRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> StreamingResponse:
    """
    Importe les villes avec streaming de la progression via SSE.

    - **country_code**: Code ISO du pays (defaut: FR)
    - **source**: 'file' (JSON local) ou 'api' (API externe)
    - **reset**: Supprimer les villes existantes avant import

    Retourne un flux SSE avec les evenements:
    - progress: {"event":"progress","progress":45,"current":15000,"total":35000,"status":"importing"}
    - complete: {"event":"complete","success":true,"imported_count":35000,"duration_seconds":12.5}
    - error: {"event":"error","error":"message"}
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        progress_queue: asyncio.Queue = asyncio.Queue()

        async def progress_callback(current: int, total: int, status: str, message: str):
            """Callback appele par l'importer pour rapporter la progression."""
            progress_pct = int((current / total) * 100) if total > 0 else 0
            progress_data = ImportProgress(
                event="progress",
                progress=progress_pct,
                current=current,
                total=total,
                status=status,
                message=message
            )
            await progress_queue.put(progress_data)

        async def run_import():
            """Execute l'import et met le resultat dans la queue."""
            try:
                if request.source == "api":
                    result = await GeoAdminService.download_and_import_cities_with_progress(
                        db, request.country_code, request.reset, progress_callback
                    )
                else:
                    result = await GeoAdminService.import_cities_from_file_with_progress(
                        db, request.country_code, request.reset, progress_callback
                    )

                # Envoyer le resultat final
                complete_data = ImportProgress(
                    event="complete",
                    progress=100,
                    current=result.imported_count,
                    total=result.imported_count,
                    status="complete",
                    message=result.message,
                    success=result.success,
                    imported_count=result.imported_count,
                    duration_seconds=result.duration_seconds,
                    error=result.errors[0] if result.errors else None
                )
                await progress_queue.put(complete_data)
                await progress_queue.put(None)  # Signal de fin

            except Exception as e:
                logger.error(f"Erreur import stream: {e}")
                error_data = ImportProgress(
                    event="error",
                    progress=0,
                    status="error",
                    message=str(e),
                    success=False,
                    error=str(e)
                )
                await progress_queue.put(error_data)
                await progress_queue.put(None)

        # Lancer l'import en tache de fond
        import_task = asyncio.create_task(run_import())

        try:
            while True:
                # Attendre le prochain message
                progress = await progress_queue.get()

                if progress is None:
                    break

                # Formater en SSE
                data = progress.model_dump_json()
                yield f"data: {data}\n\n"

                # Si complete ou error, terminer
                if progress.event in ("complete", "error"):
                    break

        except asyncio.CancelledError:
            import_task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =============================================================================
# COUNTRIES CRUD
# =============================================================================

@router.get(
    "/countries",
    response_model=List[CountryAdminRead],
    summary="Liste tous les pays (admin)"
)
async def list_all_countries(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> List[CountryAdminRead]:
    """Liste tous les pays, y compris les inactifs."""
    countries = await GeoAdminService.get_all_countries(db)
    return [CountryAdminRead.model_validate(c) for c in countries]


@router.get(
    "/countries/{code}",
    response_model=CountryAdminRead,
    summary="Detail d'un pays (admin)"
)
async def get_country(
    code: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> CountryAdminRead:
    """Recupere les details d'un pays."""
    country = await GeoAdminService.get_country(db, code)
    return CountryAdminRead.model_validate(country)


@router.post(
    "/countries",
    response_model=CountryAdminRead,
    status_code=201,
    summary="Creer un pays"
)
async def create_country(
    data: CountryCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> CountryAdminRead:
    """Cree un nouveau pays."""
    country = await GeoAdminService.create_country(db, data)
    return CountryAdminRead.model_validate(country)


@router.patch(
    "/countries/{code}",
    response_model=CountryAdminRead,
    summary="Modifier un pays"
)
async def update_country(
    code: str,
    data: CountryUpdate,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> CountryAdminRead:
    """Met a jour un pays existant."""
    country = await GeoAdminService.update_country(db, code, data)
    return CountryAdminRead.model_validate(country)


@router.post(
    "/countries/{code}/toggle-active",
    response_model=CountryAdminRead,
    summary="Activer/desactiver un pays"
)
async def toggle_country_active(
    code: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> CountryAdminRead:
    """Active ou desactive un pays."""
    country = await GeoAdminService.toggle_country_active(db, code)
    return CountryAdminRead.model_validate(country)


@router.delete(
    "/countries/{code}",
    status_code=204,
    summary="Supprimer un pays"
)
async def delete_country(
    code: str,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
) -> None:
    """
    Supprime un pays.

    **Attention**: Supprime egalement toutes les villes associees (cascade).
    """
    await GeoAdminService.delete_country(db, code)
