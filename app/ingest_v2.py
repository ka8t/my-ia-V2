"""
Advanced Document Ingestion Pipeline v2.0
------------------------------------------
Modern RAG ingestion system with:
- Multi-format parsing (Unstructured.io)
- Semantic chunking (LangChain)
- Deduplication & versioning
- Rich metadata extraction
- Optimized async pipeline
- OCR support for images
- Table extraction
"""

import os
import json
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import uuid

import httpx
import chromadb
from chromadb.config import Settings

# PyMuPDF for lightweight PDF parsing (fallback)
import fitz  # pymupdf

# Unstructured for multi-format parsing
from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title
from unstructured.staging.base import elements_to_json

# OCR with Tesseract (replacement for unstructured-inference)
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

# LangChain for semantic chunking
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
from langchain_core.documents import Document as LangchainDocument

# Configuration centralisée
from app.core.config import settings

# Logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DocumentParser:
    """Advanced multi-format document parser using Unstructured.io with PyMuPDF fallback"""

    # Extensions de fichiers texte simples
    TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".jsonl", ".html", ".htm"}

    # Magic numbers pour détecter le vrai type de fichier
    MAGIC_NUMBERS = {
        b'%PDF': 'pdf',
        b'PK\x03\x04': 'zip',  # DOCX, XLSX, PPTX sont des ZIP
        b'<!DOCTYPE': 'html',
        b'<html': 'html',
        b'<HTML': 'html',
        b'<?xml': 'xml',
    }

    @staticmethod
    def detect_real_file_type(file_path: str) -> str:
        """
        Detect the real file type by reading magic numbers.

        Args:
            file_path: Path to the file

        Returns:
            Detected type: 'pdf', 'html', 'zip', 'xml', or 'unknown'
        """
        try:
            with open(file_path, 'rb') as f:
                header = f.read(20)

            for magic, file_type in DocumentParser.MAGIC_NUMBERS.items():
                if header.lstrip(b'\n\r\t ').startswith(magic):
                    return file_type

            # Check if it's plain text
            try:
                header.decode('utf-8')
                return 'text'
            except UnicodeDecodeError:
                return 'binary'

        except Exception as e:
            logger.warning(f"Could not detect file type for {file_path}: {e}")
            return 'unknown'

    @staticmethod
    def parse_text_file(file_path: str) -> List[Dict[str, Any]]:
        """
        Parse plain text files directly without external dependencies.

        Args:
            file_path: Path to text file

        Returns:
            List of document elements with metadata
        """
        logger.info(f"Parsing text file directly: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Fallback to latin-1 if UTF-8 fails
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()

        if not content.strip():
            logger.warning(f"Empty file: {file_path}")
            return []

        # Split by paragraphs for better chunking
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        parsed_elements = []
        for i, paragraph in enumerate(paragraphs):
            parsed_elements.append({
                "type": "NarrativeText",
                "text": paragraph,
                "metadata": {
                    "filename": os.path.basename(file_path),
                    "paragraph_index": i,
                }
            })

        # If no paragraphs found, treat entire content as one element
        if not parsed_elements and content.strip():
            parsed_elements.append({
                "type": "NarrativeText",
                "text": content.strip(),
                "metadata": {
                    "filename": os.path.basename(file_path),
                }
            })

        logger.info(f"Parsed {len(parsed_elements)} text elements from {file_path}")
        return parsed_elements

    @staticmethod
    def parse_pdf_with_pymupdf(file_path: str) -> List[Dict[str, Any]]:
        """
        Parse PDF using PyMuPDF (lightweight fallback).

        Args:
            file_path: Path to PDF document

        Returns:
            List of document elements with metadata
        """
        logger.info(f"Parsing PDF with PyMuPDF: {file_path}")
        parsed_elements = []

        try:
            doc = fitz.open(file_path)
            for page_num, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    parsed_elements.append({
                        "type": "NarrativeText",
                        "text": text.strip(),
                        "metadata": {
                            "page_number": page_num + 1,
                            "filename": os.path.basename(file_path),
                        }
                    })
            doc.close()
            logger.info(f"PyMuPDF parsed {len(parsed_elements)} pages from {file_path}")
            return parsed_elements
        except Exception as e:
            logger.error(f"PyMuPDF error for {file_path}: {e}")
            raise

    @staticmethod
    def parse_document(file_path: str, strategy: str = "auto") -> List[Dict[str, Any]]:
        """
        Parse document using lightweight parsers first, with Unstructured.io as fallback.

        Priority:
        1. Detect real file type (handles misnamed files like HTML saved as .pdf)
        2. Text files (.txt, .md, html, etc.) -> parse_text_file (no dependencies)
        3. Real PDFs -> PyMuPDF (lightweight)
        4. Office docs (DOCX, XLSX, PPTX) -> Unstructured.io
        5. Other formats -> Unstructured.io (heavy)

        Args:
            file_path: Path to document
            strategy: Parsing strategy ('auto', 'fast', 'hi_res', 'ocr_only')

        Returns:
            List of document elements with metadata
        """
        file_ext = os.path.splitext(file_path)[1].lower()

        # Step 1: Detect REAL file type (handles misnamed files)
        real_type = DocumentParser.detect_real_file_type(file_path)
        logger.info(f"File {file_path}: extension={file_ext}, detected_type={real_type}")

        # Handle misnamed files (e.g., HTML saved as .pdf)
        if file_ext == ".pdf" and real_type != "pdf":
            logger.warning(f"File {file_path} has .pdf extension but is actually {real_type}")
            if real_type in ("html", "xml", "text"):
                return DocumentParser.parse_text_file(file_path)

        # Priority 1: Text files - use simple parser (no external deps)
        if file_ext in DocumentParser.TEXT_EXTENSIONS or real_type in ("html", "xml", "text"):
            try:
                return DocumentParser.parse_text_file(file_path)
            except Exception as e:
                logger.warning(f"Text parser failed, trying unstructured: {e}")

        # Priority 2: Real PDFs - use PyMuPDF (lightweight)
        if file_ext == ".pdf" and real_type == "pdf":
            try:
                return DocumentParser.parse_pdf_with_pymupdf(file_path)
            except Exception as e:
                logger.warning(f"PyMuPDF failed, trying unstructured: {e}")

        # Priority 3: Office documents (DOCX, XLSX, PPTX) - they are ZIP files
        if real_type == "zip" and file_ext in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"):
            logger.info(f"Parsing Office document {file_path} with unstructured")
            # Fall through to unstructured below

        # Priority 4: Other formats or fallback - use Unstructured
        try:
            logger.info(f"Parsing {file_path} with unstructured (strategy='{strategy}')")

            # Parse with Unstructured (optimized - no ML inference)
            elements = partition(
                filename=file_path,
                strategy=strategy,
                include_metadata=True,
            )

            # Convert to JSON-serializable format
            parsed_elements = []
            for element in elements:
                parsed_elements.append({
                    "type": element.category,
                    "text": str(element),
                    "metadata": element.metadata.to_dict() if hasattr(element.metadata, 'to_dict') else {}
                })

            logger.info(f"Parsed {len(parsed_elements)} elements from {file_path}")
            return parsed_elements

        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            raise

    @staticmethod
    def extract_tables(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract and structure tables separately"""
        tables = []
        for elem in elements:
            if elem["type"] == "Table":
                tables.append({
                    "content": elem["text"],
                    "metadata": elem["metadata"]
                })
        return tables

    @staticmethod
    async def parse_document_async(file_path: str, strategy: str = "auto") -> List[Dict[str, Any]]:
        """
        Parsing non-bloquant via thread pool.

        Utilise asyncio.to_thread pour ne pas bloquer l'event loop
        pendant le parsing CPU-intensive (Unstructured.io, OCR, etc.)

        Args:
            file_path: Chemin du fichier
            strategy: Stratégie de parsing

        Returns:
            Liste d'éléments parsés
        """
        return await asyncio.to_thread(
            DocumentParser.parse_document,
            file_path,
            strategy
        )


class OCRProcessor:
    """
    OCR using Tesseract (lightweight replacement for unstructured-inference)

    Provides OCR capabilities for images and scanned PDFs without heavy ML dependencies.
    """

    @staticmethod
    def ocr_image(image_path: str, lang: str = "fra+eng") -> str:
        """
        Extract text from image using Tesseract OCR

        Args:
            image_path: Path to image file (PNG, JPG, etc.)
            lang: Tesseract language code (fra+eng for French+English)

        Returns:
            Extracted text
        """
        try:
            logger.info(f"Running OCR on image: {image_path}")
            image = Image.open(image_path)
            text = pytesseract.image_to_string(image, lang=lang)
            logger.info(f"OCR extracted {len(text)} characters from {image_path}")
            return text.strip()
        except Exception as e:
            logger.error(f"OCR error for {image_path}: {e}")
            return ""

    @staticmethod
    def ocr_pdf(pdf_path: str, lang: str = "fra+eng") -> List[str]:
        """
        Extract text from scanned PDF using Tesseract OCR

        Converts each PDF page to image and runs OCR.
        Use this for scanned PDFs where normal text extraction fails.

        Args:
            pdf_path: Path to PDF file
            lang: Tesseract language code

        Returns:
            List of text per page
        """
        try:
            logger.info(f"Running OCR on PDF: {pdf_path}")

            # Convert PDF pages to images
            images = convert_from_path(pdf_path)
            logger.info(f"PDF has {len(images)} pages")

            texts = []
            for i, image in enumerate(images):
                logger.info(f"OCR page {i+1}/{len(images)} of {pdf_path}")
                text = pytesseract.image_to_string(image, lang=lang)
                texts.append(text.strip())

            total_chars = sum(len(t) for t in texts)
            logger.info(f"OCR extracted {total_chars} characters from {len(images)} pages")
            return texts

        except Exception as e:
            logger.error(f"OCR error for PDF {pdf_path}: {e}")
            return []

    @staticmethod
    def is_scanned_pdf(pdf_path: str, threshold: int = 100) -> bool:
        """
        Detect if a PDF is scanned (image-based) or text-based

        Args:
            pdf_path: Path to PDF file
            threshold: Minimum characters to consider PDF as text-based

        Returns:
            True if PDF appears to be scanned (low text content)
        """
        try:
            import pymupdf
            doc = pymupdf.open(pdf_path)

            # Check first few pages
            total_text = ""
            for page_num in range(min(3, len(doc))):
                page = doc[page_num]
                total_text += page.get_text()

            doc.close()

            # If very little text found, likely scanned
            return len(total_text.strip()) < threshold

        except Exception as e:
            logger.warning(f"Could not detect PDF type for {pdf_path}: {e}")
            return False


class SemanticChunker:
    """Semantic chunking using LangChain"""

    def __init__(self, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

        # Initialize text splitters
        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],  # Semantic separators
        )

        # Markdown header splitter for structured documents
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ]
        )

    def chunk_recursive(self, text: str, metadata: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Chunk using recursive character splitting (respects paragraphs/sentences)"""
        docs = self.recursive_splitter.create_documents([text], metadatas=[metadata] if metadata else None)

        return [
            {
                "text": doc.page_content,
                "metadata": doc.metadata or {}
            }
            for doc in docs
        ]

    def chunk_by_title(self, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Chunk by document structure (titles, sections)"""
        from unstructured.documents.elements import Title, NarrativeText, ListItem, Table

        # This would use Unstructured's chunk_by_title
        # For now, we'll group by title elements
        chunks = []
        current_chunk = []
        current_metadata = {}

        for elem in elements:
            if elem["type"] == "Title":
                # Save previous chunk
                if current_chunk:
                    chunks.append({
                        "text": "\n".join(current_chunk),
                        "metadata": current_metadata.copy()
                    })
                # Start new chunk
                current_chunk = [elem["text"]]
                current_metadata = elem["metadata"].copy()
            else:
                current_chunk.append(elem["text"])

        # Add last chunk
        if current_chunk:
            chunks.append({
                "text": "\n".join(current_chunk),
                "metadata": current_metadata
            })

        return chunks

    def chunk_markdown(self, text: str) -> List[Dict[str, Any]]:
        """Chunk markdown preserving header structure"""
        docs = self.markdown_splitter.split_text(text)

        chunks = []
        for doc in docs:
            # Further split if still too large
            if len(doc.page_content) > self.chunk_size:
                sub_docs = self.recursive_splitter.split_documents([doc])
                chunks.extend([
                    {"text": d.page_content, "metadata": d.metadata}
                    for d in sub_docs
                ])
            else:
                chunks.append({
                    "text": doc.page_content,
                    "metadata": doc.metadata
                })

        return chunks


class DocumentDeduplicator:
    """Handle document deduplication and versioning"""

    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute SHA256 hash of content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute SHA256 hash of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def check_duplicate(collection, document_hash: str) -> bool:
        """Check if document already exists in collection"""
        try:
            results = collection.get(
                where={"document_hash": document_hash}
            )
            return len(results["ids"]) > 0
        except:
            return False


class MetadataExtractor:
    """Extract rich metadata from documents"""

    @staticmethod
    def extract_file_metadata(file_path: str) -> Dict[str, Any]:
        """Extract file system metadata"""
        path = Path(file_path)
        stat = path.stat()

        return {
            "filename": path.name,
            "file_extension": path.suffix,
            "file_size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "file_path": str(path.absolute()),
        }

    @staticmethod
    def _sanitize_metadata_value(value: Any) -> Any:
        """
        Sanitize metadata value for ChromaDB compatibility.
        ChromaDB only accepts str, int, float, bool values.

        Args:
            value: Any metadata value

        Returns:
            Sanitized value (scalar type)
        """
        if isinstance(value, list):
            # Convert list to comma-separated string
            return ','.join(str(v) for v in value) if value else ''
        elif isinstance(value, dict):
            # Convert dict to JSON string
            return json.dumps(value)
        elif isinstance(value, (str, int, float, bool)):
            return value
        elif value is None:
            return ''
        else:
            return str(value)

    @staticmethod
    def enrich_metadata(
        base_metadata: Dict[str, Any],
        file_metadata: Dict[str, Any],
        document_hash: str,
        chunk_index: int,
        total_chunks: int,
        chunk_type: Optional[str] = None,
        user_id: Optional[str] = None,
        visibility: str = "public"
    ) -> Dict[str, Any]:
        """Combine and enrich metadata with user ownership and visibility"""
        # Sanitize base_metadata values for ChromaDB compatibility
        sanitized_base = {
            k: MetadataExtractor._sanitize_metadata_value(v)
            for k, v in base_metadata.items()
        }

        metadata = {
            **file_metadata,
            **sanitized_base,
            "document_hash": document_hash,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "chunk_type": chunk_type or "text",
            "indexed_at": datetime.now().isoformat(),
            "ingestion_version": "2.0",
            "visibility": visibility,  # public, private, (future: shared)
        }
        # user_id peut etre None pour documents legacy ou admin uploads
        if user_id:
            metadata["user_id"] = user_id
        return metadata


class EmbeddingGenerator:
    """Generate embeddings using Ollama"""

    def __init__(self, ollama_url: Optional[str] = None, model: Optional[str] = None):
        self.ollama_url = ollama_url or settings.ollama_url
        self.model = model or settings.embed_model

    async def generate_embeddings(
        self,
        texts: List[str],
        batch_size: int = 100,
        progress_callback: Optional[callable] = None,
        model: Optional[str] = None,
        max_concurrent: int = 3
    ) -> List[List[float]]:
        """Generate embeddings with parallel batching and progress tracking.

        Optimisation: utilise asyncio.Semaphore pour traiter plusieurs batches
        en parallèle (défaut: 3 batches simultanés).

        Args:
            texts: Liste de textes a vectoriser
            batch_size: Taille des batches (défaut: 100)
            progress_callback: Callback de progression
            model: Modele d'embedding (override le modele par defaut)
            max_concurrent: Nombre max de batches en parallèle (défaut: 3)
        """
        total = len(texts)
        if total == 0:
            return []

        effective_model = model or self.model
        semaphore = asyncio.Semaphore(max_concurrent)
        completed_count = 0

        async def process_batch(batch_idx: int, batch: List[str], client: httpx.AsyncClient):
            nonlocal completed_count
            async with semaphore:
                try:
                    response = await client.post(
                        f"{self.ollama_url}/api/embed",
                        json={"model": effective_model, "input": batch}
                    )
                    response.raise_for_status()
                    batch_embeddings = response.json()["embeddings"]

                    completed_count += len(batch)
                    if progress_callback:
                        await progress_callback(completed_count, total)

                    logger.debug(f"Batch {batch_idx + 1} completed ({len(batch)} embeddings)")
                    return batch_idx, batch_embeddings

                except Exception as e:
                    logger.error(f"Error generating embeddings for batch {batch_idx + 1}: {e}")
                    raise

        # Créer les batches
        batches = [(i, texts[i:i + batch_size]) for i in range(0, total, batch_size)]
        num_batches = len(batches)

        logger.info(f"Generating embeddings: {total} texts in {num_batches} batches (max {max_concurrent} concurrent)")

        async with httpx.AsyncClient(timeout=600.0) as client:
            # Lancer tous les batches en parallèle (limité par semaphore)
            tasks = [process_batch(idx, batch, client) for idx, (_, batch) in enumerate(batches)]
            results = await asyncio.gather(*tasks)

        # Trier par index de batch et aplatir
        results.sort(key=lambda x: x[0])
        all_embeddings = [emb for _, embeddings in results for emb in embeddings]

        logger.info(f"Generated {len(all_embeddings)} embeddings")
        return all_embeddings


class AdvancedIngestionPipeline:
    """Main ingestion pipeline orchestrator"""

    def __init__(
        self,
        chroma_client: chromadb.Client,
        collection_name: Optional[str] = None,
        chunking_strategy: Optional[str] = None
    ):
        self.chroma_client = chroma_client
        self.default_collection_name = collection_name or settings.collection_name
        self.chunking_strategy = chunking_strategy or settings.chunking_strategy

        # Initialize components
        self.parser = DocumentParser()
        self.chunker = SemanticChunker()
        self.deduplicator = DocumentDeduplicator()
        self.metadata_extractor = MetadataExtractor()
        self.embedder = EmbeddingGenerator()

        # Collection par defaut (peut etre overridee par ingest_file)
        self._collections_cache: Dict[str, Any] = {}

    def _get_collection(self, collection_name: Optional[str] = None, provider: Optional[str] = None):
        """
        Recupere ou cree une collection ChromaDB (avec cache).

        La collection est suffixée avec le provider LLM actif pour éviter
        les conflits de dimension entre embeddings de providers différents.

        Args:
            collection_name: Nom de base de la collection (optionnel)
            provider: Provider LLM (optionnel, défaut depuis settings)

        Returns:
            Collection ChromaDB
        """
        base_name = collection_name or self.default_collection_name
        effective_provider = provider or settings.llm_provider
        full_name = f"{base_name}_{effective_provider}"

        if full_name not in self._collections_cache:
            self._collections_cache[full_name] = self.chroma_client.get_or_create_collection(
                name=full_name,
                metadata={
                    "hnsw:space": "cosine",           # Distance cosine pour similarité
                    "hnsw:M": 16,                     # Connexions par noeud
                    "hnsw:construction_ef": 100,      # Qualité construction index
                    "hnsw:search_ef": 50              # Qualité recherche (équilibre)
                }
            )
            logger.debug(f"Collection '{full_name}' created/retrieved for provider '{effective_provider}'")

        return self._collections_cache[full_name]

    async def ingest_file(
        self,
        file_path: str,
        parsing_strategy: str = "auto",
        skip_duplicates: bool = True,
        user_id: Optional[str] = None,
        visibility: str = "public",
        collection_name: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunking_strategy: Optional[str] = None,
        embedding_model: Optional[str] = None,
        provider: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        original_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Ingest a single file with full pipeline

        Args:
            file_path: Path to file
            parsing_strategy: Unstructured parsing strategy
            skip_duplicates: Skip if document already indexed
            user_id: UUID de l'utilisateur proprietaire (None = legacy/admin)
            visibility: Visibilite du document (public, private)
            collection_name: Nom de la collection ChromaDB cible (optionnel)
            chunk_size: Taille des chunks (optionnel, defaut depuis settings)
            chunk_overlap: Chevauchement des chunks (optionnel, defaut depuis settings)
            chunking_strategy: Strategie de chunking (optionnel, defaut depuis settings)
            embedding_model: Modele d'embedding (optionnel, defaut depuis settings)
            provider: Provider LLM cible (optionnel, defaut depuis settings)
            progress_callback: Callback de progression async (current, total) -> None
            original_filename: Nom original du fichier (pour affichage dans les sources)

        Returns:
            Ingestion result with statistics
        """
        # Utiliser les parametres fournis ou les valeurs par defaut
        effective_chunk_size = chunk_size or settings.chunk_size
        effective_chunk_overlap = chunk_overlap or settings.chunk_overlap
        effective_chunking_strategy = chunking_strategy or self.chunking_strategy
        logger.info(f"Starting ingestion of {file_path} into collection {collection_name or self.default_collection_name}")

        # Get the target collection (avec provider spécifique si fourni)
        collection = self._get_collection(collection_name, provider=provider)

        # Extract file metadata
        file_metadata = self.metadata_extractor.extract_file_metadata(file_path)
        document_hash = self.deduplicator.compute_file_hash(file_path)

        # Override filename with original if provided (pour affichage correct dans les sources)
        if original_filename:
            file_metadata["filename"] = original_filename

        # Check for duplicates in target collection
        if skip_duplicates and self.deduplicator.check_duplicate(collection, document_hash):
            logger.info(f"Document {file_path} already indexed (hash: {document_hash[:8]}...), skipping")
            return {
                "status": "skipped",
                "reason": "duplicate",
                "document_hash": document_hash,
                "chunks_indexed": 0
            }

        # Parse document
        elements = self.parser.parse_document(file_path, strategy=parsing_strategy)

        # Extract tables separately
        tables = self.parser.extract_tables(elements)

        # Chunk based on strategy (avec parametres dynamiques)
        chunks = await self._chunk_elements(
            elements,
            file_path,
            chunk_size=effective_chunk_size,
            chunk_overlap=effective_chunk_overlap,
            chunking_strategy=effective_chunking_strategy
        )

        if not chunks:
            logger.warning(f"No chunks generated from {file_path}")
            return {
                "status": "failed",
                "reason": "no_content",
                "chunks_indexed": 0
            }

        # Generate embeddings (avec modèle depuis config RAG si fourni)
        chunk_texts = [chunk["text"] for chunk in chunks]
        embeddings = await self.embedder.generate_embeddings(
            chunk_texts,
            model=embedding_model,
            progress_callback=progress_callback
        )

        # Prepare for ChromaDB
        ids = []
        metadatas = []
        documents = []

        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = f"{document_hash}-{idx}"
            ids.append(chunk_id)

            # Enrich metadata with user ownership and visibility
            metadata = self.metadata_extractor.enrich_metadata(
                base_metadata=chunk.get("metadata", {}),
                file_metadata=file_metadata,
                document_hash=document_hash,
                chunk_index=idx,
                total_chunks=len(chunks),
                chunk_type=chunk.get("type", "text"),
                user_id=user_id,
                visibility=visibility
            )
            metadatas.append(metadata)
            documents.append(chunk["text"])

        # Add to ChromaDB in parallel batches (non-bloquant)
        BATCH_SIZE = 256  # Augmenté de 100 à 256 (recommandé pour PDF)

        async def add_batch(batch_idx: int, start: int, end: int):
            """Insertion non-bloquante d'un batch via thread pool."""
            await asyncio.to_thread(
                collection.add,
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end]
            )
            logger.debug(f"Indexed batch {batch_idx + 1}")

        # Créer et exécuter les tâches en parallèle
        tasks = []
        num_batches = (len(ids) + BATCH_SIZE - 1) // BATCH_SIZE
        for batch_idx, i in enumerate(range(0, len(ids), BATCH_SIZE)):
            tasks.append(add_batch(batch_idx, i, min(i + BATCH_SIZE, len(ids))))

        await asyncio.gather(*tasks)
        logger.info(f"Indexed {len(ids)} chunks in {num_batches} parallel batches")

        logger.info(f"Successfully indexed {len(chunks)} chunks from {file_path}")

        return {
            "status": "success",
            "filename": file_metadata["filename"],
            "document_hash": document_hash,
            "chunks_indexed": len(chunks),
            "tables_found": len(tables),
            "file_size": file_metadata["file_size"],
        }

    async def _chunk_elements(
        self,
        elements: List[Dict[str, Any]],
        file_path: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunking_strategy: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Chunk elements based on strategy with dynamic parameters"""

        # Combine all text from elements
        full_text = "\n\n".join([elem["text"] for elem in elements if elem["text"].strip()])

        if not full_text.strip():
            return []

        # Utiliser les parametres fournis ou les valeurs par defaut
        effective_strategy = chunking_strategy or self.chunking_strategy

        # Creer un chunker avec les parametres dynamiques si fournis
        if chunk_size or chunk_overlap:
            chunker = SemanticChunker(
                chunk_size=chunk_size or settings.chunk_size,
                chunk_overlap=chunk_overlap or settings.chunk_overlap
            )
        else:
            chunker = self.chunker

        # Choose chunking strategy
        if effective_strategy == "by_title":
            chunks = chunker.chunk_by_title(elements)

        elif effective_strategy == "markdown" and file_path.endswith(('.md', '.markdown')):
            chunks = chunker.chunk_markdown(full_text)

        else:  # Default to recursive (semantic)
            # Aggregate metadata from elements
            metadata = {}
            if elements and elements[0].get("metadata"):
                metadata = elements[0]["metadata"]

            chunks = chunker.chunk_recursive(full_text, metadata)

        logger.info(f"Chunked {file_path} with strategy={effective_strategy}, "
                   f"size={chunk_size or settings.chunk_size}, overlap={chunk_overlap or settings.chunk_overlap}")

        return chunks

    async def ingest_directory(
        self,
        directory: str,
        recursive: bool = True,
        file_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Ingest all files in a directory

        Args:
            directory: Path to directory
            recursive: Scan subdirectories
            file_patterns: List of glob patterns (e.g., ['*.pdf', '*.docx'])

        Returns:
            Ingestion statistics
        """
        logger.info(f"Starting directory ingestion: {directory}")

        path = Path(directory)

        # Default patterns
        if file_patterns is None:
            file_patterns = [
                "*.pdf", "*.txt", "*.md", "*.html", "*.htm",
                "*.docx", "*.doc", "*.xlsx", "*.xls", "*.pptx", "*.ppt",
                "*.jsonl", "*.json", "*.csv",
                "*.png", "*.jpg", "*.jpeg"  # OCR images
            ]

        # Find all files
        files = []
        for pattern in file_patterns:
            if recursive:
                files.extend(path.rglob(pattern))
            else:
                files.extend(path.glob(pattern))

        logger.info(f"Found {len(files)} files to process")

        # Ingest each file
        results = {
            "total_files": len(files),
            "successful": 0,
            "skipped": 0,
            "failed": 0,
            "total_chunks": 0,
            "files": []
        }

        for file in files:
            try:
                result = await self.ingest_file(str(file))
                results["files"].append(result)

                if result["status"] == "success":
                    results["successful"] += 1
                    results["total_chunks"] += result["chunks_indexed"]
                elif result["status"] == "skipped":
                    results["skipped"] += 1
                else:
                    results["failed"] += 1

            except Exception as e:
                logger.error(f"Error ingesting {file}: {e}")
                results["failed"] += 1
                results["files"].append({
                    "status": "failed",
                    "filename": file.name,
                    "error": str(e)
                })

        logger.info(f"Directory ingestion complete: {results['successful']} successful, "
                   f"{results['skipped']} skipped, {results['failed']} failed")

        return results


async def main():
    """Main ingestion script"""
    logger.info("🚀 Starting Advanced Ingestion Pipeline v2.0")

    # Initialize ChromaDB (HTTP client to connect to dedicated service)
    chroma_client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=Settings(anonymized_telemetry=False)
    )

    # Create pipeline
    pipeline = AdvancedIngestionPipeline(chroma_client=chroma_client)

    # Ingest from datasets directory
    results = await pipeline.ingest_directory(
        directory=settings.datasets_dir,
        recursive=True
    )

    # Display results
    logger.info("=" * 60)
    logger.info("📊 INGESTION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total files found: {results['total_files']}")
    logger.info(f"✅ Successful: {results['successful']}")
    logger.info(f"⏭️  Skipped (duplicates): {results['skipped']}")
    logger.info(f"❌ Failed: {results['failed']}")
    logger.info(f"📦 Total chunks indexed: {results['total_chunks']}")
    logger.info("=" * 60)

    # Get collection count
    collection = chroma_client.get_collection(name=settings.collection_name)
    total_count = collection.count()
    logger.info(f"📚 Total documents in database: {total_count}")


if __name__ == "__main__":
    asyncio.run(main())
