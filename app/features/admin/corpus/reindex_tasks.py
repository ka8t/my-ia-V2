"""Tâches de fond — réindexation corpus-aware (documents et sources).

Ces fonctions sont conçues pour être passées à ``BackgroundTasks.add_task``.
Elles maintiennent la progression dans ``ReindexManager`` et supportent
l'annulation en cascade via ``corpus_id`` (optionnel).

Importées par :
- ``app/features/admin/corpus/router.py`` (routes API ``/api/admin/corpus``)
- ``app/web/admin_corpus.py`` (routes web ``/web/admin/corpus``)

Note : la version *non corpus-aware* utilisée par le router admin documents
vit dans ``app/features/admin/documents/router.py`` et reste séparée car sa
signature est différente (``provider`` au lieu de ``corpus_id``).
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


async def run_doc_reindex_in_background(
    document_id: UUID,
    corpus_id: Optional[UUID] = None,
) -> None:
    """Réindexe un document en BG, avec progression et annulation cascade-aware."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import selectinload

    from app.common.utils.reindex import (
        ReindexManager,
        clear_doc_cancel_flag,
        is_doc_cancel_requested,
        set_doc_reindex_progress,
    )
    from app.core.config import settings
    from app.core.deps import get_chroma_client, get_storage_service
    from app.features.admin.documents.service import AdminDocumentService
    from app.models import Document

    doc_id_str = str(document_id)
    corpus_id_str = str(corpus_id) if corpus_id else None

    if corpus_id_str:
        ReindexManager.register_corpus_item(corpus_id_str, ReindexManager.doc_id(doc_id_str))

    def _check_cancelled() -> bool:
        if is_doc_cancel_requested(doc_id_str):
            set_doc_reindex_progress(
                doc_id_str, 0, "cancelled",
                status="cancelled",
                error_message="Annulé par l'utilisateur",
                corpus_id=corpus_id_str,
            )
            clear_doc_cancel_flag(doc_id_str)
            return True
        return False

    set_doc_reindex_progress(doc_id_str, 0, "starting", corpus_id=corpus_id_str)

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        if _check_cancelled():
            return

        async with bg_session_maker() as db:
            set_doc_reindex_progress(doc_id_str, 5, "loading_document", corpus_id=corpus_id_str)
            if _check_cancelled():
                return

            result = await db.execute(
                select(Document)
                .options(selectinload(Document.collection))
                .where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            if not document:
                set_doc_reindex_progress(
                    doc_id_str, 0, "not_found",
                    status="failed",
                    error_message="Document introuvable",
                    corpus_id=corpus_id_str,
                )
                return

            set_doc_reindex_progress(
                doc_id_str, 10, "preparing",
                document_name=document.filename,
                corpus_id=corpus_id_str,
            )
            if _check_cancelled():
                return

            service = AdminDocumentService(
                session=db,
                storage_service=get_storage_service(),
                chroma_client=get_chroma_client(),
            )
            reindex_result = await service._reindex_document_internal(
                document,
                track_progress=True,
                cancel_check=lambda: is_doc_cancel_requested(doc_id_str),
            )

            if is_doc_cancel_requested(doc_id_str):
                _check_cancelled()
                return

            await db.commit()

            if reindex_result["success"]:
                set_doc_reindex_progress(
                    doc_id_str, 100, "complete",
                    status="success",
                    documents_count=reindex_result["new_chunk_count"],
                    corpus_id=corpus_id_str,
                )
            elif reindex_result.get("cancelled"):
                set_doc_reindex_progress(
                    doc_id_str, 0, "cancelled",
                    status="cancelled",
                    error_message="Annulé par l'utilisateur",
                    corpus_id=corpus_id_str,
                )
            else:
                set_doc_reindex_progress(
                    doc_id_str, 0, "failed",
                    status="failed",
                    error_message=reindex_result["message"],
                    corpus_id=corpus_id_str,
                )

    except Exception as e:
        logger.error(f"Background reindex failed for document {document_id}: {e}")
        set_doc_reindex_progress(
            doc_id_str, 0, "error",
            status="failed",
            error_message=str(e),
            corpus_id=corpus_id_str,
        )
    finally:
        clear_doc_cancel_flag(doc_id_str)
        if corpus_id_str:
            ReindexManager.unregister_corpus_item(
                corpus_id_str, ReindexManager.doc_id(doc_id_str)
            )
        await engine.dispose()


async def run_source_reindex_in_background(
    source_id: UUID,
    triggered_by: Optional[str] = None,
    log_id: Optional[str] = None,
    corpus_id: Optional[UUID] = None,
) -> None:
    """Réindexe une source en BG via le scheduler V1, avec cascade-cancel optionnelle."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.common.utils.reindex import ReindexManager
    from app.core.config import settings
    from app.features.sources.scheduler import reindex_source
    from app.models import ContextSource

    source_id_str = str(source_id)
    corpus_id_str = str(corpus_id) if corpus_id else None

    if corpus_id_str:
        ReindexManager.register_corpus_item(
            corpus_id_str, ReindexManager.source_id(source_id_str)
        )

    logger.info(
        "Démarrage réindexation source %s (trigger: corpus_reindex, log_id: %s)",
        source_id, log_id,
    )

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with bg_session_maker() as db:
            result = await db.execute(
                select(ContextSource).where(ContextSource.id == source_id)
            )
            source = result.scalar_one_or_none()
            if not source:
                logger.warning("Source %s non trouvée", source_id)
                return

            await reindex_source(
                db=db,
                source=source,
                trigger_type="corpus_reindex",
                triggered_by=triggered_by,
                log_id=log_id,
            )
            logger.info("Source %s réindexée avec succès", source_id)

    except Exception as e:
        logger.error("Erreur réindexation source %s: %s", source_id, e)
    finally:
        if corpus_id_str:
            ReindexManager.unregister_corpus_item(
                corpus_id_str, ReindexManager.source_id(source_id_str)
            )
        await engine.dispose()
