"""
Router Ingestion

Endpoints pour l'ingestion de documents.
"""
import logging
import os
import tempfile
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, UploadFile, File, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import verify_api_key, get_db, get_storage_service, get_chroma_client
from app.features.ingestion.schemas import UploadResponse, UploadAsyncResponse
from app.features.ingestion.service import IngestionService
from app.features.auth.router import current_active_user
from app.common.utils.reindex import set_doc_reindex_progress
from app.common.metrics import REQUEST_COUNT
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["ingestion"])


@router.post("", response_model=UploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    parsing_strategy: str = "auto",
    skip_duplicates: bool = True,
    _: bool = Depends(verify_api_key)
):
    """
    Upload et ingestion de documents avec parsing avancé

    Features:
    - Multi-format support (PDF, DOCX, XLSX, PPTX, images avec OCR, etc.)
    - Semantic chunking avec LangChain
    - Déduplication automatique
    - Extraction de métadonnées riches
    - Extraction de tables

    Args:
        file: Fichier à uploader
        parsing_strategy: 'auto', 'fast', 'hi_res', ou 'ocr_only'
        skip_duplicates: Ignorer si le hash du document existe déjà
        _: Vérification API key

    Returns:
        Résultat de l'ingestion
    """
    try:
        result = await IngestionService.ingest_document(
            file=file,
            parsing_strategy=parsing_strategy,
            skip_duplicates=skip_duplicates
        )

        REQUEST_COUNT.labels(endpoint="/upload", method="POST", status="200").inc()

        return UploadResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/upload", method="POST", status="500").inc()
        logger.error(f"Error in upload endpoint: {e}")
        raise


@router.post("/v2", response_model=UploadResponse)
async def upload_file_v2(
    request: Request,
    file: UploadFile = File(...),
    parsing_strategy: str = "auto",
    skip_duplicates: bool = True,
    visibility: str = Query(default="public", pattern="^(public|private)$"),
    collection_id: Optional[str] = Query(default=None, description="UUID de la collection cible (docs privés)"),
    corpus_id: Optional[str] = Query(default=None, description="UUID du corpus cible (docs publics admin)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    storage = Depends(get_storage_service)
):
    """
    Upload et ingestion de documents avec authentification JWT

    Nouvelle version avec:
    - Liaison au user connecte
    - Choix de visibilite (public/private)
    - Sauvegarde en BDD avec ownership
    - Choix du corpus (admin) ou collection (user) cible

    Args:
        file: Fichier à uploader
        parsing_strategy: 'auto', 'fast', 'hi_res', ou 'ocr_only'
        skip_duplicates: Ignorer si le hash du document existe déjà
        visibility: 'public' (defaut) ou 'private'
        collection_id: UUID de la collection cible pour docs privés (optionnel)
        corpus_id: UUID du corpus cible pour docs publics (optionnel)
        db: Session database
        user: Utilisateur connecte

    Returns:
        Résultat de l'ingestion

    Note:
        Un document appartient soit à un corpus (docs publics admin),
        soit à une collection (docs privés utilisateur), jamais les deux.
    """
    from uuid import UUID as UUIDType
    try:
        # Vérifier qu'on n'a pas les deux
        if collection_id and corpus_id:
            raise ValueError("Spécifier soit collection_id soit corpus_id, pas les deux")

        # Convertir en UUID si fourni
        coll_uuid = UUIDType(collection_id) if collection_id else None
        corp_uuid = UUIDType(corpus_id) if corpus_id else None

        result = await IngestionService.ingest_document(
            file=file,
            parsing_strategy=parsing_strategy,
            skip_duplicates=skip_duplicates,
            user_id=str(user.id),
            visibility=visibility,
            collection_id=coll_uuid,
            corpus_id=corp_uuid,
            db=db,
            storage=storage
        )

        REQUEST_COUNT.labels(endpoint="/upload/v2", method="POST", status="200").inc()

        return UploadResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(endpoint="/upload/v2", method="POST", status="500").inc()
        logger.error(f"Error in upload/v2 endpoint: {e}")
        raise


@router.post("/v2/async", response_model=UploadAsyncResponse)
async def upload_file_v2_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    visibility: str = Query(default="public", pattern="^(public|private)$"),
    corpus_id: Optional[str] = Query(default=None, description="UUID du corpus cible"),
    replace_if_exists: bool = Query(default=True, description="Remplacer si le fichier existe déjà"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    storage = Depends(get_storage_service),
    chroma = Depends(get_chroma_client)
):
    """
    Upload de document avec indexation asynchrone.

    1. Sauvegarde le fichier (DB + storage) via le service
    2. Lance l'indexation en arrière-plan
    3. Retourne immédiatement avec l'ID du document

    Utiliser GET /api/admin/documents/{id}/reindex/status pour suivre la progression.
    """
    try:
        if not corpus_id:
            raise HTTPException(status_code=400, detail="corpus_id requis")

        corp_uuid = UUID(corpus_id)

        # Déléguer toutes les opérations DB/storage au service
        new_doc, content, file_ext, collection_name = (
            await IngestionService.create_document_with_upload(
                db=db,
                user=user,
                file=file,
                corpus_id=corp_uuid,
                storage=storage,
                chroma=chroma,
                replace_if_exists=replace_if_exists,
                visibility=visibility,
            )
        )

        # Initialiser la progression
        doc_id_str = str(new_doc.id)
        set_doc_reindex_progress(doc_id_str, 0, "queued", document_name=file.filename)

        # Lancer l'indexation en arrière-plan
        background_tasks.add_task(
            _run_indexation_in_background,
            document_id=new_doc.id,
            content=content,
            file_ext=file_ext,
            collection_name=collection_name,
        )

        REQUEST_COUNT.labels(endpoint="/upload/v2/async", method="POST", status="200").inc()

        return UploadAsyncResponse(
            success=True,
            document_id=str(new_doc.id),
            filename=file.filename,
            message="Document sauvegardé, indexation en cours..."
        )

    except HTTPException:
        raise
    except Exception as e:
        # Vérifier si c'est une erreur de duplicata (même fichier déjà uploadé)
        error_str = str(e)
        if "uq_document_user_file_hash" in error_str or "duplicate key" in error_str.lower():
            REQUEST_COUNT.labels(endpoint="/upload/v2/async", method="POST", status="409").inc()
            raise HTTPException(
                status_code=409,
                detail=f"Ce document existe déjà : {file.filename}"
            )
        REQUEST_COUNT.labels(endpoint="/upload/v2/async", method="POST", status="500").inc()
        logger.error(f"Error in upload/v2/async: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_indexation_in_background(
    document_id: UUID,
    content: bytes,
    file_ext: str,
    collection_name: str,
) -> None:
    """
    Tâche de fond pour l'indexation d'un document uploadé.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings
    from app.core.deps import get_ingestion_pipeline
    from app.models import Document
    from app.common.utils.rag_config import get_rag_config

    doc_id_str = str(document_id)
    set_doc_reindex_progress(doc_id_str, 5, "starting")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tmp_file_path = None
    try:
        async with bg_session_maker() as db:
            # Récupérer le document
            set_doc_reindex_progress(doc_id_str, 10, "loading_document")
            result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

            if not document:
                set_doc_reindex_progress(
                    doc_id_str, 0, "not_found",
                    status="failed", error_message="Document introuvable"
                )
                return

            set_doc_reindex_progress(
                doc_id_str, 15, "preparing",
                document_name=document.filename
            )

            # Créer fichier temporaire (hash déjà calculé lors de l'upload)
            set_doc_reindex_progress(doc_id_str, 20, "ingesting")
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                tmp_file.write(content)
                tmp_file_path = tmp_file.name

            # Récupérer la config RAG
            rag_config = await get_rag_config(db)

            # Lancer l'ingestion
            set_doc_reindex_progress(doc_id_str, 30, "embedding")
            ingestion_pipeline = get_ingestion_pipeline()
            if not ingestion_pipeline:
                set_doc_reindex_progress(
                    doc_id_str, 0, "error",
                    status="failed", error_message="Pipeline non initialisé"
                )
                return

            # Callback de progression pour les embeddings (30% -> 85%)
            async def embedding_progress_callback(current: int, total: int) -> None:
                # Progression de 30% à 85% pendant l'embedding
                progress = 30 + int((current / total) * 55) if total > 0 else 30
                set_doc_reindex_progress(doc_id_str, progress, "embedding")

            result = await ingestion_pipeline.ingest_file(
                file_path=tmp_file_path,
                parsing_strategy="auto",
                skip_duplicates=False,
                user_id=str(document.user_id),
                visibility=document.visibility.value,
                collection_name=collection_name,
                embedding_model=rag_config.embedding_model,
                progress_callback=embedding_progress_callback,
                original_filename=document.filename,
            )

            # Nettoyer fichier temporaire
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                tmp_file_path = None

            set_doc_reindex_progress(doc_id_str, 90, "updating_counters")

            if result["status"] == "success":
                # Récupérer le provider actif
                from app.features.system.service import SystemConfigService
                config_service = SystemConfigService(db)
                current_provider = await config_service.get("llm.provider", "ollama")

                document.chunk_count = result["chunks_indexed"]
                document.embedding_count = result["chunks_indexed"]
                document.is_indexed = True
                document.indexed_provider = current_provider
                await db.commit()

                set_doc_reindex_progress(
                    doc_id_str, 100, "complete",
                    status="success",
                    documents_count=result["chunks_indexed"],
                )
                logger.info(f"Document {document_id} indexé: {result['chunks_indexed']} chunks")
            else:
                set_doc_reindex_progress(
                    doc_id_str, 0, "failed",
                    status="failed",
                    error_message=result.get("reason", "Erreur inconnue"),
                )

    except Exception as e:
        logger.error(f"Background indexation failed for {document_id}: {e}")
        set_doc_reindex_progress(
            doc_id_str, 0, "error",
            status="failed",
            error_message=str(e),
        )
        # Nettoyer fichier temporaire en cas d'erreur
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
            except:
                pass
    finally:
        await engine.dispose()
