"""
Service Documents - Logique métier pour la gestion des documents.

Ce service orchestre les opérations entre le repository, le storage et ChromaDB.
"""

import hashlib
import logging
import mimetypes
from typing import AsyncGenerator, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ErrorCode, not_found, forbidden, bad_request
from app.common.utils.pagination import create_pagination_info
from app.common.storage.exceptions import (
    FileTooLargeError,
    InvalidFileTypeError,
    QuotaExceededError,
    StorageFileNotFoundError,
)
from app.common.storage.service import StorageService
from app.core.config import settings
from app.core.deps import get_dynamic_quota_config, get_ingestion_pipeline
from app.common.utils.rag_config import get_rag_config
from app.features.system.service import SystemConfigService
from app.models import Collection, Document, DocumentVersion, DocumentVisibility, UserQuota
from app.features.documents.repository import DocumentRepository
from app.features.documents.schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentSearchResponse,
    DocumentSearchResult,
    DocumentStatsResponse,
    DocumentUploadResponse,
    DocumentVersionResponse,
    UploadAsyncResponse,
    UploadProgressEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Suivi de progression upload en mémoire (par processus)
# ============================================================================

_upload_progress: dict[str, dict] = {}


def get_upload_progress(document_id: str) -> dict:
    """Retourne la progression d'indexation d'un document uploadé."""
    return _upload_progress.get(document_id, {"status": "idle", "progress": 0})


def set_upload_progress(
    document_id: str,
    progress: int,
    message: str,
    status: str = "indexing",
    chunk_count: int = 0,
    error_message: Optional[str] = None,
    document_name: Optional[str] = None,
) -> None:
    """Met à jour la progression d'indexation d'un document uploadé."""
    data = {
        "status": status,
        "progress": progress,
        "progress_message": message,
        "chunk_count": chunk_count,
        "error_message": error_message,
    }
    if document_name:
        data["document_name"] = document_name
    elif document_id in _upload_progress and "document_name" in _upload_progress[document_id]:
        data["document_name"] = _upload_progress[document_id]["document_name"]
    _upload_progress[document_id] = data


def clear_upload_progress(document_id: str) -> None:
    """Supprime le suivi de progression d'un document."""
    _upload_progress.pop(document_id, None)


class DocumentService:
    """Service de gestion des documents utilisateur."""

    def __init__(
        self,
        session: AsyncSession,
        storage_service: StorageService,
        chroma_client=None,
    ):
        self.session = session
        self.storage = storage_service
        self.chroma = chroma_client
        self.repo = DocumentRepository(session)

    async def _refresh_storage_config(self) -> None:
        """
        Rafraichit la configuration du storage depuis la base de donnees.

        Permet d'utiliser les types MIME dynamiques configures par l'admin.
        """
        try:
            quota_config = await get_dynamic_quota_config(self.session)
            self.storage.update_config(quota_config)
        except Exception as e:
            logger.warning(f"Failed to refresh storage config: {e}")

    # === List & Get ===

    def _doc_to_response(self, doc: Document, current_user_id: UUID = None) -> DocumentResponse:
        """Convertit un Document en DocumentResponse avec infos collection."""
        response_dict = {
            "id": doc.id,
            "filename": doc.filename,
            "file_hash": doc.file_hash,
            "file_size": doc.file_size,
            "file_type": doc.file_type,
            "file_path": doc.file_path,
            "chunk_count": doc.chunk_count,
            "current_version": doc.current_version,
            "visibility": doc.visibility,
            "is_indexed": doc.is_indexed,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "user_id": doc.user_id,
            "is_owner": doc.user_id == current_user_id if current_user_id else True,
            "collection_id": doc.collection_id,
            "collection_name": doc.collection.display_name if doc.collection else None,
            "collection_type": doc.collection.type if doc.collection else None,
        }
        return DocumentResponse(**response_dict)

    async def list_documents(
        self,
        user_id: UUID,
        visibility: Optional[str] = None,
        file_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> DocumentListResponse:
        """Liste les documents d'un utilisateur avec pagination."""
        documents, total = await self.repo.list_user_documents(
            user_id=user_id,
            visibility=visibility,
            file_type=file_type,
            page=page,
            page_size=page_size,
        )

        info = create_pagination_info(total, page_size, (page - 1) * page_size)

        return DocumentListResponse(
            documents=[self._doc_to_response(doc, user_id) for doc in documents],
            total=info.total,
            page=info.page,
            page_size=info.page_size,
            total_pages=info.total_pages,
        )

    async def get_document(
        self, user_id: UUID, document_id: UUID
    ) -> DocumentDetailResponse:
        """
        Récupère un document avec ses versions.

        Permet de voir les documents de sa collection privée (lecture seule).
        """
        document = await self.repo.get_accessible_document_with_versions(user_id, document_id)

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Construire la réponse avec is_owner
        response_dict = self._doc_to_response(document, user_id).model_dump()

        return DocumentDetailResponse(
            **response_dict,
            versions=[
                DocumentVersionResponse.model_validate(v) for v in document.versions
            ],
        )

    async def get_document_for_access(
        self, user_id: UUID, document_id: UUID
    ) -> Document:
        """
        Récupère un document en vérifiant les droits d'accès.
        
        Un utilisateur peut accéder à:
        - Ses propres documents
        - Les documents publics
        """
        document = await self.repo.get_by_id(document_id)

        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Vérifier accès
        if document.user_id != user_id:
            if document.visibility != DocumentVisibility.PUBLIC:
                raise forbidden(ErrorCode.DOC_ACCESS_DENIED)

        return document

    # === Search ===

    async def search_documents(
        self,
        user_id: UUID,
        query: str,
        visibility: Optional[str] = None,
        limit: int = 50,
    ) -> DocumentSearchResponse:
        """Recherche dans les documents de l'utilisateur."""
        if not query or len(query) < 2:
            raise bad_request(ErrorCode.DOC_QUERY_TOO_SHORT, {"min": 2})

        documents = await self.repo.search_user_documents(
            user_id=user_id,
            query=query,
            visibility=visibility,
            limit=limit,
        )

        results = [
            DocumentSearchResult(
                id=doc.id,
                filename=doc.filename,
                file_type=doc.file_type,
                file_size=doc.file_size,
                visibility=doc.visibility.value,
                created_at=doc.created_at,
            )
            for doc in documents
        ]

        return DocumentSearchResponse(results=results, total=len(results), query=query)

    # === Upload & Replace ===

    async def upload_document(
        self,
        user_id: UUID,
        file: UploadFile,
        visibility: str = "public",
        collection_id: Optional[UUID] = None,
    ) -> DocumentUploadResponse:
        """Upload un nouveau document."""
        # Rafraichir la config depuis la DB (types MIME dynamiques)
        await self._refresh_storage_config()

        # Lire le contenu
        content = await file.read()

        # Calculer le hash
        file_hash = hashlib.sha256(content).hexdigest()

        # Vérifier si le document existe déjà pour cet utilisateur (même hash)
        existing = await self.repo.get_user_document_by_hash(user_id, file_hash)
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": ErrorCode.DOC_ALREADY_EXISTS.value,
                    "params": {
                        "document_id": str(existing.id),
                        "filename": existing.filename,
                    }
                },
            )

        # Déterminer le type MIME
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

        # Récupérer le quota personnalisé si existant
        user_quota = await self._get_user_quota(user_id)

        # Si pas de collection_id, utiliser la collection privee de l'utilisateur
        if not collection_id:
            collection_id = await self._get_user_collection_id(user_id)

        # Créer le document en DB d'abord pour avoir l'ID
        document = Document(
            user_id=user_id,
            collection_id=collection_id,
            filename=file.filename,
            file_hash=file_hash,
            file_size=len(content),
            file_type=mime_type,
            chunk_count=0,
            current_version=1,
            visibility=DocumentVisibility(visibility),
            is_indexed=True,
        )

        try:
            document = await self.repo.create(document)

            # Sauvegarder dans le storage
            file_path = await self.storage.upload(
                user_id=user_id,
                document_id=document.id,
                filename=file.filename,
                content=content,
                mime_type=mime_type,
                version=1,
                user_quota=user_quota,
            )

            # Mettre à jour le path
            document.file_path = file_path

            # Créer la version
            version = DocumentVersion(
                document_id=document.id,
                version_number=1,
                file_path=file_path,
                file_size=len(content),
                file_hash=file_hash,
                chunk_count=0,
                created_by=user_id,
            )
            await self.repo.create_version(version)

            # Ingerer dans ChromaDB
            chunk_count = await self._ingest_to_chromadb(
                file_path=file_path,
                user_id=user_id,
                collection_id=collection_id,
                visibility=visibility,
                original_filename=file.filename,
            )

            # Mettre a jour les compteurs (chunk_count = embedding_count car 1 embedding par chunk)
            document.chunk_count = chunk_count
            document.embedding_count = chunk_count
            version.chunk_count = chunk_count

            await self.session.commit()

            logger.info(f"Document uploadé: {document.id} par user {user_id} ({chunk_count} chunks)")

            return DocumentUploadResponse(
                id=document.id,
                filename=document.filename,
                file_size=document.file_size,
                file_type=document.file_type,
                version=1,
                message=f"Document uploadé avec succès ({chunk_count} chunks indexés)",
            )

        except (FileTooLargeError, InvalidFileTypeError, QuotaExceededError) as e:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur upload document: {e}")
            raise HTTPException(status_code=500, detail="Erreur lors de l'upload")

    async def upload_document_with_progress(
        self,
        user_id: UUID,
        file_content: bytes,
        file_name: str,
        file_content_type: Optional[str] = None,
        visibility: str = "public",
        collection_id: Optional[UUID] = None,
        replace_if_exists: bool = False,
    ) -> AsyncGenerator[UploadProgressEvent, None]:
        """
        Upload un document avec progression en temps réel.

        Yield des événements UploadProgressEvent à chaque étape:
        - upload (10%): Réception et validation du fichier
        - parsing (30%): Analyse du contenu
        - embedding (70%): Génération des embeddings
        - indexing (90%): Indexation dans ChromaDB
        - done (100%): Terminé avec succès
        - error: En cas d'erreur

        Args:
            user_id: ID de l'utilisateur
            file_content: Contenu du fichier (bytes)
            file_name: Nom du fichier
            file_content_type: Type MIME du fichier
            visibility: Visibilité du document
            collection_id: ID de la collection cible

        Yields:
            UploadProgressEvent pour chaque étape
        """
        document = None

        # Utiliser les paramètres passés (fichier déjà lu par le router)
        content = file_content
        filename = file_name
        content_type = file_content_type

        try:
            # === ÉTAPE 1: Upload (10%) ===
            yield UploadProgressEvent(
                stage="upload",
                progress=5,
                message="Réception du fichier..."
            )

            # Rafraichir la config depuis la DB
            await self._refresh_storage_config()

            # Calculer le hash du contenu déjà lu
            file_hash = hashlib.sha256(content).hexdigest()

            yield UploadProgressEvent(
                stage="upload",
                progress=10,
                message="Fichier reçu, validation..."
            )

            # Vérifier si le document existe déjà
            existing = await self.repo.get_user_document_by_hash(user_id, file_hash)
            if existing:
                if replace_if_exists:
                    # Supprimer l'ancien document pour le remplacer
                    logger.info(f"Remplacement du document existant: {existing.id}")
                    await self._delete_document_internal(existing)
                else:
                    yield UploadProgressEvent(
                        stage="error",
                        progress=0,
                        message=f"Ce document existe déjà: {existing.filename}"
                    )
                    return

            # Déterminer le type MIME
            mime_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

            # Récupérer le quota
            user_quota = await self._get_user_quota(user_id)

            # Si pas de collection_id, utiliser la collection privée
            if not collection_id:
                collection_id = await self._get_user_collection_id(user_id)

            # === ÉTAPE 2: Parsing (30%) ===
            yield UploadProgressEvent(
                stage="parsing",
                progress=20,
                message="Création de l'enregistrement..."
            )

            # Créer le document en DB
            document = Document(
                user_id=user_id,
                collection_id=collection_id,
                filename=filename,
                file_hash=file_hash,
                file_size=len(content),
                file_type=mime_type,
                chunk_count=0,
                current_version=1,
                visibility=DocumentVisibility(visibility),
                is_indexed=True,
            )
            document = await self.repo.create(document)

            yield UploadProgressEvent(
                stage="parsing",
                progress=25,
                message="Sauvegarde du fichier..."
            )

            # Sauvegarder dans le storage
            file_path = await self.storage.upload(
                user_id=user_id,
                document_id=document.id,
                filename=filename,
                content=content,
                mime_type=mime_type,
                version=1,
                user_quota=user_quota,
            )

            # Mettre à jour le path
            document.file_path = file_path

            yield UploadProgressEvent(
                stage="parsing",
                progress=30,
                message="Fichier sauvegardé, analyse du contenu..."
            )

            # Créer la version
            version = DocumentVersion(
                document_id=document.id,
                version_number=1,
                file_path=file_path,
                file_size=len(content),
                file_hash=file_hash,
                chunk_count=0,
                created_by=user_id,
            )
            await self.repo.create_version(version)

            # === ÉTAPE 3 & 4: Embedding + Indexing (30% -> 90%) ===
            yield UploadProgressEvent(
                stage="embedding",
                progress=40,
                message="Génération des embeddings..."
            )

            # Ingérer dans ChromaDB avec progression
            chunk_count = await self._ingest_with_progress(
                file_path=file_path,
                user_id=user_id,
                collection_id=collection_id,
                visibility=visibility,
                progress_callback=self._create_progress_yielder(),
                original_filename=filename,
            )

            yield UploadProgressEvent(
                stage="indexing",
                progress=90,
                message=f"Indexation terminée ({chunk_count} chunks)"
            )

            # Mettre à jour les compteurs
            document.chunk_count = chunk_count
            document.embedding_count = chunk_count
            version.chunk_count = chunk_count

            await self.session.commit()

            # === ÉTAPE 5: Done (100%) ===
            result = DocumentUploadResponse(
                id=document.id,
                filename=document.filename,
                file_size=document.file_size,
                file_type=document.file_type,
                version=1,
                message=f"Document uploadé avec succès ({chunk_count} chunks indexés)",
            )

            yield UploadProgressEvent(
                stage="done",
                progress=100,
                message="Upload terminé avec succès",
                result=result
            )

            logger.info(f"Document uploadé (stream): {document.id} par user {user_id} ({chunk_count} chunks)")

        except (FileTooLargeError, InvalidFileTypeError, QuotaExceededError) as e:
            await self.session.rollback()
            yield UploadProgressEvent(
                stage="error",
                progress=0,
                message=str(e)
            )
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur upload document (stream): {e}")
            # Détecter les erreurs de doublon
            error_msg = str(e)
            if "duplicate key" in error_msg or "UniqueViolation" in error_msg:
                yield UploadProgressEvent(
                    stage="error",
                    progress=0,
                    message="Ce fichier existe déjà. Utilisez 'Remplacer' pour le mettre à jour."
                )
            else:
                yield UploadProgressEvent(
                    stage="error",
                    progress=0,
                    message=f"Erreur lors de l'upload: {str(e)}"
                )

    def _create_progress_yielder(self):
        """Crée un callback pour la progression (non utilisé pour l'instant)."""
        return None

    async def upload_document_deferred(
        self,
        user_id: UUID,
        file_content: bytes,
        file_name: str,
        file_content_type: Optional[str] = None,
        visibility: str = "public",
        collection_id: Optional[UUID] = None,
        replace_if_exists: bool = False,
    ) -> UploadAsyncResponse:
        """
        Upload un document sans indexation immédiate.

        Le document est sauvegardé avec is_indexed=False.
        L'indexation sera lancée en tâche de fond.

        Returns:
            UploadAsyncResponse avec l'ID du document créé
        """
        # Rafraichir la config depuis la DB
        await self._refresh_storage_config()

        # Calculer le hash du contenu
        file_hash = hashlib.sha256(file_content).hexdigest()

        # Vérifier si le document existe déjà
        existing = await self.repo.get_user_document_by_hash(user_id, file_hash)
        if existing:
            if replace_if_exists:
                logger.info(f"Remplacement du document existant: {existing.id}")
                await self._delete_document_internal(existing)
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Ce document existe déjà: {existing.filename}"
                )

        # Déterminer le type MIME
        mime_type = file_content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        # Récupérer le quota
        user_quota = await self._get_user_quota(user_id)

        # Si pas de collection_id, utiliser la collection privée
        if not collection_id:
            collection_id = await self._get_user_collection_id(user_id)

        try:
            # Créer le document en DB avec is_indexed=False
            document = Document(
                user_id=user_id,
                collection_id=collection_id,
                filename=file_name,
                file_hash=file_hash,
                file_size=len(file_content),
                file_type=mime_type,
                chunk_count=0,
                current_version=1,
                visibility=DocumentVisibility(visibility),
                is_indexed=False,  # Sera True après indexation
            )
            document = await self.repo.create(document)

            # Sauvegarder dans le storage
            file_path = await self.storage.upload(
                user_id=user_id,
                document_id=document.id,
                filename=file_name,
                content=file_content,
                mime_type=mime_type,
                version=1,
                user_quota=user_quota,
            )

            # Mettre à jour le path
            document.file_path = file_path

            # Créer la version
            version = DocumentVersion(
                document_id=document.id,
                version_number=1,
                file_path=file_path,
                file_size=len(file_content),
                file_hash=file_hash,
                chunk_count=0,
                created_by=user_id,
            )
            await self.repo.create_version(version)

            await self.session.commit()

            # Initialiser le suivi de progression
            set_upload_progress(
                str(document.id),
                progress=0,
                message="pending",
                status="pending",
                document_name=file_name,
            )

            logger.info(f"Document uploadé (deferred): {document.id} par user {user_id}")

            return UploadAsyncResponse(
                id=document.id,
                filename=document.filename,
                file_size=document.file_size,
                file_type=document.file_type,
                status="pending",
                message="Document uploadé, indexation en attente",
            )

        except (FileTooLargeError, InvalidFileTypeError, QuotaExceededError) as e:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur upload document (deferred): {e}")
            raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload: {str(e)}")

    async def _ingest_with_progress(
        self,
        file_path: str,
        user_id: UUID,
        collection_id: UUID,
        visibility: str,
        progress_callback=None,
        original_filename: Optional[str] = None,
    ) -> int:
        """
        Ingère un document dans ChromaDB.

        Version simplifiée pour le streaming (la progression détaillée
        nécessiterait de modifier le pipeline d'ingestion).

        Args:
            original_filename: Nom original du fichier pour affichage dans les sources

        Returns:
            Nombre de chunks indexés
        """
        pipeline = get_ingestion_pipeline()
        if not pipeline:
            logger.warning("Pipeline d'ingestion non initialisé, indexation ignorée")
            return 0

        try:
            # Charger la configuration RAG
            rag_config = await get_rag_config(self.session)

            # Construire le chemin complet
            full_path = f"{settings.storage_local_path}/{file_path}"

            # Récupérer le nom de la collection
            collection_name = await self._get_collection_name(collection_id)

            logger.info(f"Ingestion (stream) du document {file_path} dans collection {collection_name}")

            # Appeler le pipeline
            result = await pipeline.ingest_file(
                file_path=full_path,
                parsing_strategy="auto",
                skip_duplicates=False,
                user_id=str(user_id),
                visibility=visibility,
                collection_name=collection_name,
                chunk_size=rag_config.chunk_size,
                chunk_overlap=rag_config.chunk_overlap,
                chunking_strategy=rag_config.chunking_strategy,
                original_filename=original_filename,
            )

            if result["status"] == "success":
                chunks_count = result.get("chunks_indexed", 0)
                logger.info(f"Document indexé avec succès: {chunks_count} chunks")

                # Mettre à jour les compteurs de la collection
                await self._update_collection_counters(collection_id, 1, chunks_count)

                return chunks_count
            else:
                logger.warning(f"Ingestion échouée: {result.get('reason', 'unknown')}")
                return 0

        except Exception as e:
            logger.error(f"Erreur lors de l'ingestion ChromaDB: {e}")
            return 0

    async def replace_document(
        self,
        user_id: UUID,
        document_id: UUID,
        file: UploadFile,
        comment: Optional[str] = None,
    ) -> DocumentUploadResponse:
        """Remplace un document par une nouvelle version."""
        # Rafraichir la config depuis la DB (types MIME dynamiques)
        await self._refresh_storage_config()

        # Récupérer le document existant
        document = await self.repo.get_user_document(user_id, document_id)
        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Lire le contenu
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()

        # Vérifier que ce n'est pas le même contenu
        if file_hash == document.file_hash:
            raise bad_request(ErrorCode.DOC_FILE_IDENTICAL)

        # Déterminer le type MIME
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or document.file_type

        # Nouvelle version
        new_version = document.current_version + 1

        # Récupérer quota
        user_quota = await self._get_user_quota(user_id)

        try:
            # Sauvegarder dans le storage
            file_path = await self.storage.upload(
                user_id=user_id,
                document_id=document.id,
                filename=file.filename,
                content=content,
                mime_type=mime_type,
                version=new_version,
                user_quota=user_quota,
            )

            # Créer la version
            version = DocumentVersion(
                document_id=document.id,
                version_number=new_version,
                file_path=file_path,
                file_size=len(content),
                file_hash=file_hash,
                chunk_count=0,
                comment=comment,
                created_by=user_id,
            )
            await self.repo.create_version(version)

            # Mettre à jour le document principal
            document.file_hash = file_hash
            document.file_size = len(content)
            document.file_type = mime_type
            document.file_path = file_path
            document.current_version = new_version
            document.filename = file.filename
            await self.repo.update(document)

            # Réindexer dans ChromaDB (supprimer anciens chunks, créer nouveaux)
            reindex_result = await self._reindex_document(document)
            if not reindex_result["success"]:
                logger.warning(
                    f"Réindexation échouée pour document {document.id}: "
                    f"{reindex_result['message']}"
                )

            await self.session.commit()

            logger.info(
                f"Document remplacé: {document.id} v{new_version} par user {user_id}"
            )

            return DocumentUploadResponse(
                id=document.id,
                filename=document.filename,
                file_size=document.file_size,
                file_type=document.file_type,
                version=new_version,
                message=f"Document mis à jour (version {new_version})",
            )

        except (FileTooLargeError, InvalidFileTypeError, QuotaExceededError) as e:
            await self.session.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur remplacement document: {e}")
            raise HTTPException(status_code=500, detail="Erreur lors du remplacement")

    # === Update ===

    async def update_document(
        self,
        user_id: UUID,
        document_id: UUID,
        visibility: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> DocumentResponse:
        """Met à jour les métadonnées d'un document."""
        document = await self.repo.get_user_document(user_id, document_id)
        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        if visibility:
            document.visibility = DocumentVisibility(visibility)

        if filename:
            document.filename = filename

        document = await self.repo.update(document)
        await self.session.commit()

        return DocumentResponse.model_validate(document)

    # === Delete ===

    async def _delete_document_internal(self, document: Document) -> None:
        """
        Supprime un document (ChromaDB → storage → DB) sans commit.
        Utilisé pour le remplacement de document.

        ChromaDB est supprimé en premier. Si ça échoue, rien d'autre n'est touché.
        """
        try:
            # 1. Supprimer de ChromaDB EN PREMIER
            await self._delete_from_chroma(document)

            # 2. Supprimer du storage
            await self.storage.delete_document(document.user_id, document.id)

            # 3. Supprimer de la DB (cascade sur versions)
            await self.repo.delete(document)

            logger.info(f"Document supprimé (interne): {document.id}")

        except Exception as e:
            logger.error(f"Erreur suppression interne document: {e}")
            raise

    async def delete_document(self, user_id: UUID, document_id: UUID) -> bool:
        """
        Supprime un document, ses embeddings ChromaDB, fichiers et enregistrement DB.

        Ordre : ChromaDB → Storage → Compteurs → DB → Commit.
        Si ChromaDB échoue, rien d'autre n'est supprimé.
        """
        document = await self.repo.get_user_document(user_id, document_id)
        if not document:
            raise not_found(ErrorCode.DOC_NOT_FOUND)

        # Sauvegarder les valeurs pour mise à jour des compteurs
        chunk_count = document.chunk_count or 0
        collection_id = document.collection_id

        try:
            # 1. Supprimer de ChromaDB EN PREMIER
            await self._delete_from_chroma(document)

            # 2. Supprimer du storage
            await self.storage.delete_document(user_id, document_id)

            # 3. Mettre à jour les compteurs de la collection
            if collection_id:
                coll_result = await self.session.execute(
                    select(Collection).where(Collection.id == collection_id)
                )
                collection = coll_result.scalar_one_or_none()
                if collection:
                    collection.document_count = max(0, (collection.document_count or 0) - 1)
                    collection.chunk_count = max(0, (collection.chunk_count or 0) - chunk_count)

            # 4. Supprimer de la DB (cascade sur versions)
            await self.repo.delete(document)
            await self.session.commit()

            logger.info(f"Document supprimé: {document_id} par user {user_id} (ChromaDB + storage + DB, -{chunk_count} chunks)")
            return True

        except RuntimeError as e:
            # Échec ChromaDB → rien n'est supprimé
            await self.session.rollback()
            logger.error(f"ChromaDB delete failed, document non supprimé: {e}")
            raise HTTPException(status_code=500, detail="Erreur suppression ChromaDB, document non supprimé")
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Erreur suppression document: {e}")
            raise HTTPException(status_code=500, detail="Erreur lors de la suppression")

    async def _delete_from_chroma(self, document: Document) -> None:
        """
        Supprime les embeddings d'un document de ChromaDB.

        Raises:
            RuntimeError: Si la suppression ChromaDB échoue
        """
        if not self.chroma or not document.file_hash:
            return

        # Récupérer le nom de la collection ChromaDB
        # Note: On utilise toujours une requête explicite pour éviter le lazy-loading
        # qui échoue en contexte async (greenlet_spawn error)
        collection_name = None
        if document.collection_id:
            coll_result = await self.session.execute(
                select(Collection).where(Collection.id == document.collection_id)
            )
            collection = coll_result.scalar_one_or_none()
            if collection:
                collection_name = collection.name

        if not collection_name:
            logger.warning(f"Collection introuvable pour document {document.id}")
            return

        # Déterminer le provider actif pour le nom de collection ChromaDB
        config_service = SystemConfigService(self.session)
        provider = await config_service.get("llm.provider", settings.llm_provider)
        chroma_name = f"{collection_name}_{provider}"

        try:
            # Essayer la collection provider-specific d'abord
            try:
                chroma_collection = self.chroma.get_collection(name=chroma_name)
            except Exception:
                # Fallback sur le nom de base (rétrocompatibilité)
                chroma_collection = self.chroma.get_collection(name=collection_name)
                chroma_name = collection_name

            # Supprimer les chunks par document_hash
            chroma_collection.delete(where={"document_hash": document.file_hash})
            logger.info(f"ChromaDB: embeddings supprimés pour {document.filename} dans {chroma_name}")
        except Exception as e:
            logger.error(f"Erreur suppression ChromaDB pour {document.id}: {e}")
            raise RuntimeError(f"ChromaDB delete failed for document {document.id}: {e}") from e

    async def _reindex_document(self, document: Document) -> dict:
        """
        Réindexe un document dans ChromaDB.

        Supprime les anciens chunks puis réingère le nouveau contenu.

        Args:
            document: Document à réindexer (avec file_path et file_hash à jour)

        Returns:
            dict avec {"success": bool, "message": str, "chunks_indexed": int}
        """
        if not document.file_path:
            return {
                "success": False,
                "message": "Pas de fichier associé au document",
                "chunks_indexed": 0,
            }

        try:
            # 1. Supprimer les anciens chunks de ChromaDB
            await self._delete_from_chroma(document)
            logger.info(f"Anciens chunks supprimés pour document {document.id}")

            # 2. Réingérer le nouveau contenu
            chunk_count = await self._ingest_to_chromadb(
                file_path=document.file_path,
                user_id=document.user_id,
                collection_id=document.collection_id,
                visibility=document.visibility.value,
                original_filename=document.filename,
            )

            # 3. Mettre à jour les compteurs du document
            document.chunk_count = chunk_count
            document.embedding_count = chunk_count
            document.is_indexed = chunk_count > 0

            # 4. Mettre à jour la version courante également
            version = await self.repo.get_version(document.id, document.current_version)
            if version:
                version.chunk_count = chunk_count

            logger.info(
                f"Document {document.id} réindexé: {chunk_count} chunks"
            )

            return {
                "success": True,
                "message": f"Document réindexé avec {chunk_count} chunks",
                "chunks_indexed": chunk_count,
            }

        except Exception as e:
            logger.error(f"Erreur réindexation document {document.id}: {e}")
            return {
                "success": False,
                "message": str(e),
                "chunks_indexed": 0,
            }

    async def bulk_delete_documents(
        self, user_id: UUID, document_ids: List[UUID]
    ) -> Tuple[int, List[UUID]]:
        """
        Supprime plusieurs documents en une seule opération.

        Ordre par document : ChromaDB → Storage → Compteurs → DB.
        Si ChromaDB échoue pour un document, celui-ci est marqué failed.

        Args:
            user_id: ID de l'utilisateur
            document_ids: Liste des IDs de documents à supprimer

        Returns:
            Tuple[deleted_count, failed_ids]
        """
        deleted_count = 0
        failed_ids = []
        # Compteurs par collection pour mise à jour groupée
        collection_deltas: dict[UUID, dict] = {}

        for doc_id in document_ids:
            try:
                document = await self.repo.get_user_document(user_id, doc_id)
                if not document:
                    failed_ids.append(doc_id)
                    continue

                # Sauvegarder pour mise à jour des compteurs
                if document.collection_id:
                    if document.collection_id not in collection_deltas:
                        collection_deltas[document.collection_id] = {"docs": 0, "chunks": 0}
                    collection_deltas[document.collection_id]["docs"] += 1
                    collection_deltas[document.collection_id]["chunks"] += document.chunk_count or 0

                # 1. Supprimer de ChromaDB EN PREMIER
                await self._delete_from_chroma(document)

                # 2. Supprimer du storage
                await self.storage.delete_document(user_id, doc_id)

                # 3. Supprimer de la DB
                await self.repo.delete(document)
                deleted_count += 1

            except Exception as e:
                logger.error(f"Erreur suppression document {doc_id}: {e}")
                failed_ids.append(doc_id)

        # Mettre à jour les compteurs des collections
        for coll_id, deltas in collection_deltas.items():
            coll_result = await self.session.execute(
                select(Collection).where(Collection.id == coll_id)
            )
            collection = coll_result.scalar_one_or_none()
            if collection:
                collection.document_count = max(0, (collection.document_count or 0) - deltas["docs"])
                collection.chunk_count = max(0, (collection.chunk_count or 0) - deltas["chunks"])

        # Commit une seule fois à la fin
        await self.session.commit()
        logger.info(f"Bulk delete: {deleted_count} supprimés, {len(failed_ids)} échecs pour user {user_id}")
        return deleted_count, failed_ids

    # === Download ===

    async def get_download_content(
        self, user_id: UUID, document_id: UUID, version: Optional[int] = None
    ) -> Tuple[bytes, str, str]:
        """
        Récupère le contenu d'un document pour téléchargement.

        Returns:
            Tuple[content, filename, mime_type]
        """
        document = await self.get_document_for_access(user_id, document_id)

        # Déterminer le chemin
        if version:
            doc_version = await self.repo.get_version(document_id, version)
            if not doc_version:
                raise not_found(ErrorCode.DOC_VERSION_NOT_FOUND, {"version": version})
            file_path = doc_version.file_path
        else:
            file_path = document.file_path

        if not file_path:
            raise not_found(ErrorCode.DOC_FILE_NOT_FOUND)

        try:
            content = await self.storage.download(file_path)
            return content, document.filename, document.file_type
        except StorageFileNotFoundError:
            raise not_found(ErrorCode.STORAGE_FILE_NOT_FOUND)

    # === Stats ===

    async def get_user_stats(self, user_id: UUID) -> DocumentStatsResponse:
        """Récupère les statistiques de stockage d'un utilisateur."""
        user_quota = await self._get_user_quota(user_id)
        stats = await self.storage.get_user_stats(user_id, user_quota)

        remaining = None
        if stats.quota_bytes:
            remaining = max(0, stats.quota_bytes - stats.used_bytes)

        return DocumentStatsResponse(
            used_bytes=stats.used_bytes,
            file_count=stats.file_count,
            quota_bytes=stats.quota_bytes,
            quota_used_percent=stats.quota_used_percent,
            remaining_bytes=remaining,
        )

    # === Helpers ===

    async def _get_user_quota(self, user_id: UUID) -> Optional[int]:
        """Récupère le quota personnalisé d'un utilisateur."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(UserQuota.quota_bytes).where(UserQuota.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row if row else None

    async def _get_user_collection_id(self, user_id: UUID) -> UUID:
        """Recupere l'ID de la collection privee de l'utilisateur."""
        result = await self.session.execute(
            select(Collection.id).where(
                Collection.owner_id == user_id,
                Collection.type == "private"
            )
        )
        collection_id = result.scalar_one_or_none()

        if not collection_id:
            raise not_found(ErrorCode.COLLECTION_NOT_FOUND)

        return collection_id

    async def _get_collection_name(self, collection_id: UUID) -> str:
        """Recupere le nom technique de la collection pour ChromaDB."""
        result = await self.session.execute(
            select(Collection.name).where(Collection.id == collection_id)
        )
        name = result.scalar_one_or_none()

        if not name:
            raise not_found(ErrorCode.COLLECTION_NOT_FOUND)

        return name

    async def _ingest_to_chromadb(
        self,
        file_path: str,
        user_id: UUID,
        collection_id: UUID,
        visibility: str,
        original_filename: Optional[str] = None,
    ) -> int:
        """
        Ingere un document dans ChromaDB via le pipeline.

        Args:
            file_path: Chemin relatif du fichier dans le storage
            user_id: ID de l'utilisateur
            collection_id: ID de la collection cible
            visibility: Visibilite du document
            original_filename: Nom original du fichier pour affichage

        Returns:
            Nombre de chunks indexes
        """
        pipeline = get_ingestion_pipeline()
        if not pipeline:
            logger.warning("Pipeline d'ingestion non initialise, indexation ignoree")
            return 0

        try:
            # Charger la configuration RAG depuis la BDD
            rag_config = await get_rag_config(self.session)

            # Construire le chemin complet
            full_path = f"{settings.storage_local_path}/{file_path}"

            # Recuperer le nom de la collection
            collection_name = await self._get_collection_name(collection_id)

            logger.info(f"Ingestion du document {file_path} dans collection {collection_name} "
                       f"(chunk_size={rag_config.chunk_size}, overlap={rag_config.chunk_overlap}, "
                       f"strategy={rag_config.chunking_strategy})")

            # Appeler le pipeline avec les parametres de chunking depuis la config
            result = await pipeline.ingest_file(
                file_path=full_path,
                parsing_strategy="auto",
                skip_duplicates=False,  # On a deja verifie les doublons par hash
                user_id=str(user_id),
                visibility=visibility,
                collection_name=collection_name,
                chunk_size=rag_config.chunk_size,
                chunk_overlap=rag_config.chunk_overlap,
                chunking_strategy=rag_config.chunking_strategy,
                original_filename=original_filename,
            )

            if result["status"] == "success":
                chunks_count = result.get("chunks_indexed", 0)
                logger.info(f"Document indexe avec succes: {chunks_count} chunks")

                # Mettre a jour les compteurs de la collection
                await self._update_collection_counters(collection_id, 1, chunks_count)

                return chunks_count
            else:
                logger.warning(f"Ingestion echouee: {result.get('reason', 'unknown')}")
                return 0

        except Exception as e:
            logger.error(f"Erreur lors de l'ingestion ChromaDB: {e}")
            # Ne pas faire echouer l'upload si l'ingestion echoue
            return 0

    async def _update_collection_counters(
        self,
        collection_id: UUID,
        doc_delta: int,
        chunk_delta: int,
    ) -> None:
        """Met a jour les compteurs de documents et chunks de la collection."""
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        collection = result.scalar_one_or_none()
        if collection:
            collection.document_count += doc_delta
            collection.chunk_count += chunk_delta
