"""
Service Ingestion

Logique metier pour l'ingestion de documents avec le pipeline v2.
"""
import hashlib
import os
import logging
import tempfile
import uuid as uuid_lib
from typing import Dict, Any, Optional, Set
from uuid import UUID

from fastapi import UploadFile, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.errors import ErrorCode, not_found, bad_request, api_error
from app.core.deps import get_ingestion_pipeline
from app.models import Document, DocumentVisibility, Collection, Corpus, CorpusDocument, User
from app.common.filetypes import (
    FILE_TYPES_REGISTRY,
    get_enabled_extensions,
)
from app.common.utils.rag_config import get_rag_config

logger = logging.getLogger(__name__)

# Extensions par defaut (fallback si DB non disponible)
DEFAULT_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".html", ".htm",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".jsonl", ".json", ".csv",
    ".png", ".jpg", ".jpeg"
}


class IngestionService:
    """Service pour l'ingestion de documents"""

    @staticmethod
    async def get_allowed_extensions(db: Optional[AsyncSession] = None) -> Set[str]:
        """
        Recupere les extensions autorisees depuis la DB ou utilise le fallback.

        Args:
            db: Session database (optionnelle)

        Returns:
            Set des extensions autorisees
        """
        if db is None:
            return DEFAULT_EXTENSIONS

        try:
            from app.features.system.service import SystemConfigService
            config_service = SystemConfigService(db)
            enabled_types = await config_service.get("storage.enabled_file_types", None)

            if enabled_types is None:
                # Utiliser les types actives par defaut du registre
                return get_enabled_extensions(None)

            return get_enabled_extensions(enabled_types)
        except Exception as e:
            logger.warning(f"Failed to get enabled extensions from DB, using defaults: {e}")
            return DEFAULT_EXTENSIONS

    @staticmethod
    async def create_document_with_upload(
        db: AsyncSession,
        user: User,
        file: UploadFile,
        corpus_id: UUID,
        storage,
        chroma,
        replace_if_exists: bool = True,
        visibility: str = "public",
    ) -> tuple[Document, bytes, str, str]:
        """
        Cree un document en DB, gere les doublons, upload vers le storage.

        Encapsule toutes les operations DB liees a la creation d'un document
        pour le endpoint v2/async.

        Args:
            db: Session database async
            user: Utilisateur connecte
            file: Fichier uploade
            corpus_id: UUID du corpus cible
            storage: Service de stockage
            chroma: Client ChromaDB
            replace_if_exists: Remplacer si le fichier existe deja
            visibility: Visibilite du document ('public' ou 'private')

        Returns:
            Tuple (document, content, file_ext, collection_name)

        Raises:
            HTTPException: 400 si corpus_id manquant, 404 si corpus introuvable,
                          409 si doublon sans remplacement, 500 si storage echoue
        """
        # Verifier le corpus et recuperer la collection ChromaDB
        result = await db.execute(
            select(Corpus)
            .options(selectinload(Corpus.assigned_collections))
            .where(Corpus.id == corpus_id)
        )
        corpus = result.unique().scalar_one_or_none()
        if not corpus:
            raise HTTPException(status_code=404, detail="Corpus non trouvé")

        # Determiner le nom de collection ChromaDB
        if corpus.assigned_collections:
            collection_name = corpus.assigned_collections[0].name
        else:
            collection_name = corpus.name

        # Lire le contenu du fichier et calculer le hash
        content = await file.read()
        file_ext = os.path.splitext(file.filename)[1].lower()
        file_hash = hashlib.sha256(content).hexdigest()

        # Verifier si un document avec le meme hash existe pour cet utilisateur
        existing_result = await db.execute(
            select(Document).where(
                Document.user_id == user.id,
                Document.file_hash == file_hash
            )
        )
        existing_doc = existing_result.scalar_one_or_none()

        if existing_doc:
            if not replace_if_exists:
                raise HTTPException(
                    status_code=409,
                    detail="Ce fichier existe déjà. Cochez l'option \"Remplacer\" pour le mettre à jour."
                )
            # Supprimer l'ancien document via le service admin (storage + ChromaDB + DB)
            from app.features.admin.documents.service import AdminDocumentService
            logger.info(f"Remplacement du document existant {existing_doc.id} par nouvelle version")
            admin_service = AdminDocumentService(db, storage, chroma)
            await admin_service.delete_document(existing_doc.id)

        # Creer le document en DB (pas encore indexe)
        doc_visibility = DocumentVisibility(visibility)
        new_doc = Document(
            filename=file.filename,
            file_hash=file_hash,
            file_size=len(content),
            file_type=file.content_type or "application/octet-stream",
            chunk_count=0,
            embedding_count=0,
            user_id=user.id,
            visibility=doc_visibility,
            is_indexed=False
        )
        db.add(new_doc)
        await db.flush()

        # Creer la relation document-corpus via table pivot (N-N)
        corpus_doc = CorpusDocument(
            corpus_id=corpus_id,
            document_id=new_doc.id
        )
        db.add(corpus_doc)
        await db.commit()
        await db.refresh(new_doc)

        # Sauvegarder le fichier dans le storage
        try:
            file_path = await storage.upload(
                user_id=user.id,
                document_id=new_doc.id,
                filename=file.filename,
                content=content,
                mime_type=file.content_type or "application/octet-stream",
                check_quota=False
            )
            new_doc.file_path = file_path
            await db.commit()
        except Exception as e:
            # Supprimer le document cree si le storage echoue
            logger.error(f"Erreur sauvegarde storage, suppression du document: {e}")
            await db.delete(new_doc)
            await db.commit()
            raise HTTPException(
                status_code=500,
                detail=f"Erreur lors de la sauvegarde du fichier: {str(e)}"
            )

        return new_doc, content, file_ext, collection_name

    @staticmethod
    async def ingest_document(
        file: UploadFile,
        parsing_strategy: str = "auto",
        skip_duplicates: bool = True,
        user_id: Optional[str] = None,
        visibility: str = "public",
        collection_id: Optional[UUID] = None,
        corpus_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None,
        storage=None
    ) -> Dict[str, Any]:
        """
        Ingere un document avec le pipeline avance v2

        Args:
            file: Fichier uploade
            parsing_strategy: Strategie de parsing ('auto', 'fast', 'hi_res', 'ocr_only')
            skip_duplicates: Ignorer les doublons
            user_id: UUID de l'utilisateur proprietaire
            visibility: Visibilite du document ('public' ou 'private')
            collection_id: UUID de la collection cible (docs privés utilisateur)
            corpus_id: UUID du corpus cible (docs publics admin)
            db: Session database pour sauvegarder le Document

        Returns:
            Dictionnaire avec le resultat de l'ingestion

        Raises:
            HTTPException: Si le pipeline n'est pas initialise ou erreur d'ingestion

        Note:
            Un document appartient soit a un corpus (docs publics),
            soit a une collection (docs prives), jamais les deux.
        """
        ingestion_pipeline = get_ingestion_pipeline()
        if not ingestion_pipeline:
            raise HTTPException(
                status_code=500,
                detail="Ingestion pipeline not initialized"
            )

        # Verifier qu'on a soit collection_id soit corpus_id (pas les deux, pas aucun)
        if collection_id and corpus_id:
            raise bad_request(ErrorCode.VALIDATION_ERROR, {"field": "collection_id/corpus_id", "message": "Spécifier l'un ou l'autre, pas les deux"})
        if not collection_id and not corpus_id:
            raise bad_request(ErrorCode.VALIDATION_ERROR, {"field": "collection_id/corpus_id", "message": "Un des deux est requis"})

        # Variables pour le tracking
        collection_name = None
        collection = None
        corpus = None

        if db:
            if corpus_id:
                # Mode Corpus: récupérer le corpus et sa première collection assignée
                from sqlalchemy.orm import selectinload
                result = await db.execute(
                    select(Corpus)
                    .options(selectinload(Corpus.assigned_collections))
                    .where(Corpus.id == corpus_id)
                )
                corpus = result.unique().scalar_one_or_none()
                if not corpus:
                    raise not_found(ErrorCode.CORPUS_NOT_FOUND)

                # Utiliser la première collection assignée pour l'indexation ChromaDB
                if corpus.assigned_collections:
                    collection = corpus.assigned_collections[0]
                    collection_name = collection.name
                else:
                    # Pas de collection assignée, utiliser le nom du corpus comme collection ChromaDB
                    collection_name = corpus.name
                    logger.warning(f"Corpus {corpus.name} has no assigned collection, using corpus name for ChromaDB")

            else:
                # Mode Collection: récupérer la collection
                result = await db.execute(
                    select(Collection).where(Collection.id == collection_id)
                )
                collection = result.scalar_one_or_none()
                if not collection:
                    raise not_found(ErrorCode.COLLECTION_NOT_FOUND)
                collection_name = collection.name

        # Recuperer les extensions autorisees depuis la DB
        allowed_extensions = await IngestionService.get_allowed_extensions(db)

        # Vérifier l'extension
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise bad_request(
                ErrorCode.INGESTION_FILE_TYPE_NOT_SUPPORTED,
                {"extensions": ', '.join(sorted(allowed_extensions))}
            )

        tmp_file_path = None
        try:
            # Créer un fichier temporaire
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                content = await file.read()
                tmp_file.write(content)
                tmp_file_path = tmp_file.name

            logger.info(f"File uploaded: {file.filename} ({len(content)} bytes)")

            # Charger la config RAG pour le modèle d'embedding
            rag_config = await get_rag_config(db)

            # Ingestion avec le pipeline avance (avec user_id, visibility et collection)
            result = await ingestion_pipeline.ingest_file(
                file_path=tmp_file_path,
                parsing_strategy=parsing_strategy,
                skip_duplicates=skip_duplicates,
                user_id=user_id,
                visibility=visibility,
                collection_name=collection_name,
                embedding_model=rag_config.embedding_model,
                original_filename=file.filename,
            )

            # Nettoyer le fichier temporaire
            os.unlink(tmp_file_path)

            # Gérer les différents statuts de résultat
            if result["status"] == "skipped":
                # Document déjà dans ChromaDB, mais vérifier s'il existe en PostgreSQL
                saved_doc_id = None
                if db and user_id and (collection_id or corpus_id):
                    try:
                        # Chercher par hash
                        existing = await db.execute(
                            select(Document).where(Document.file_hash == result["document_hash"])
                        )
                        doc = existing.scalar_one_or_none()
                        if doc:
                            saved_doc_id = str(doc.id)
                        else:
                            # Créer l'entrée en base même si déjà dans ChromaDB
                            doc_visibility = DocumentVisibility(visibility)
                            new_doc = Document(
                                filename=file.filename,
                                file_hash=result["document_hash"],
                                file_size=len(content),
                                file_type=file.content_type or "application/octet-stream",
                                chunk_count=0,  # Déjà indexé, on ne connaît pas le count
                                embedding_count=0,
                                user_id=uuid_lib.UUID(user_id),
                                collection_id=collection_id if collection_id else None,
                                visibility=doc_visibility,
                                is_indexed=True
                            )
                            db.add(new_doc)
                            await db.flush()

                            # Créer la relation document-corpus via table pivot (N-N)
                            if corpus_id:
                                corpus_doc = CorpusDocument(
                                    corpus_id=corpus_id,
                                    document_id=new_doc.id
                                )
                                db.add(corpus_doc)

                            await db.commit()
                            await db.refresh(new_doc)
                            saved_doc_id = str(new_doc.id)

                            # Sauvegarder le fichier vers le storage permanent
                            if storage:
                                try:
                                    file_path = await storage.upload(
                                        user_id=uuid_lib.UUID(user_id),
                                        document_id=new_doc.id,
                                        filename=file.filename,
                                        content=content,
                                        mime_type=file.content_type or "application/octet-stream",
                                        check_quota=False  # Pas de vérification quota pour admin
                                    )
                                    new_doc.file_path = file_path
                                    await db.commit()
                                    logger.info(f"File saved to storage: {file_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to save file to storage: {e}")

                            logger.info(f"Document (skipped) saved to DB: {new_doc.id}")
                    except Exception as e:
                        logger.error(f"Error handling skipped document in DB: {e}")
                        await db.rollback()

                return {
                    "success": True,
                    "filename": file.filename,
                    "chunks_indexed": 0,
                    "message": f"Document déjà indexé (hash: {result['document_hash'][:8]}...)",
                    "document_id": saved_doc_id
                }
            elif result["status"] == "failed":
                raise bad_request(
                    ErrorCode.INGESTION_FAILED,
                    {"reason": result.get('reason', 'unknown error')}
                )
            else:  # success
                # Sauvegarder le Document en PostgreSQL si db fournie
                saved_doc_id = None
                if db and user_id and (collection_id or corpus_id):
                    try:
                        doc_visibility = DocumentVisibility(visibility)
                        new_doc = Document(
                            filename=file.filename,
                            file_hash=result.get("document_hash", ""),
                            file_size=len(content),
                            file_type=file.content_type or "application/octet-stream",
                            chunk_count=result["chunks_indexed"],
                            embedding_count=result["chunks_indexed"],  # 1 embedding par chunk
                            user_id=uuid_lib.UUID(user_id),
                            # Document dans collection privée (corpus via table pivot)
                            collection_id=collection_id if collection_id else None,
                            visibility=doc_visibility,
                            is_indexed=True
                        )
                        db.add(new_doc)
                        await db.flush()

                        # Créer la relation document-corpus via table pivot (N-N)
                        if corpus_id:
                            corpus_doc = CorpusDocument(
                                corpus_id=corpus_id,
                                document_id=new_doc.id
                            )
                            db.add(corpus_doc)

                        # Mettre a jour les compteurs de la collection (si disponible)
                        if collection:
                            collection.document_count += 1
                            collection.chunk_count += result["chunks_indexed"]
                            collection.embedding_model = rag_config.embedding_model

                        await db.commit()
                        await db.refresh(new_doc)
                        saved_doc_id = str(new_doc.id)

                        # Sauvegarder le fichier vers le storage permanent
                        if storage:
                            try:
                                file_path = await storage.upload(
                                    user_id=uuid_lib.UUID(user_id),
                                    document_id=new_doc.id,
                                    filename=file.filename,
                                    content=content,
                                    mime_type=file.content_type or "application/octet-stream",
                                    check_quota=False  # Pas de vérification quota pour admin
                                )
                                new_doc.file_path = file_path
                                await db.commit()
                                logger.info(f"File saved to storage: {file_path}")
                            except Exception as e:
                                logger.warning(f"Failed to save file to storage: {e}")

                        target_info = f"corpus={corpus.name}" if corpus else f"collection={collection_name}"
                        logger.info(f"Document saved to DB: {new_doc.id} (user={user_id}, {target_info}, visibility={visibility})")
                    except Exception as e:
                        logger.error(f"Error saving document to DB: {e}")
                        await db.rollback()
                        # On ne fait pas echouer l'ingestion si la sauvegarde DB echoue
                        # Le document est deja dans ChromaDB

                message = f"Fichier '{file.filename}' indexé avec succès ({result['chunks_indexed']} chunks"
                if result.get('tables_found', 0) > 0:
                    message += f", {result['tables_found']} tables détectées"
                message += ")"

                return {
                    "success": True,
                    "filename": file.filename,
                    "chunks_indexed": result["chunks_indexed"],
                    "message": message,
                    "document_id": saved_doc_id
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in ingestion: {e}", exc_info=True)

            # Nettoyer le fichier temporaire si il existe
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                except:
                    pass

            raise api_error(500, ErrorCode.INGESTION_FAILED, {"reason": str(e)})
