"""
Schémas Pydantic pour l'Ingestion

DTOs pour l'upload et l'ingestion de documents.
"""
from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    """Réponse après upload d'un document (synchrone)"""
    success: bool
    filename: str
    chunks_indexed: int
    message: str
    document_id: str | None = None


class UploadAsyncResponse(BaseModel):
    """Réponse après upload asynchrone (indexation en background)"""
    success: bool
    document_id: str
    filename: str
    message: str
