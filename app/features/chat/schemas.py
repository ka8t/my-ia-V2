"""
Schémas Pydantic pour le Chat

DTOs pour les endpoints de chat.
"""
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Requête de chat"""
    query: str = Field(..., description="Question de l'utilisateur")
    session_id: Optional[str] = Field(None, description="ID de session pour le contexte")
    collection_name: Optional[str] = Field(None, description="Nom de la collection ChromaDB cible")
    source_ids: Optional[List[UUID]] = Field(None, description="IDs des sources externes a interroger")
    language: Optional[str] = Field("fr", description="Langue de réponse (fr/en), défaut: fr")
    rag_mode: Optional[str] = Field("auto", description="Mode RAG: auto, fast ou full")


class Suggestion(BaseModel):
    """Suggestion d'action quand le RAG ne trouve pas de résultats"""
    suggestion_type: str = Field(..., description="Type: lower_threshold, add_documents, rephrase, check_collection")
    message: str = Field(..., description="Message affiché à l'utilisateur")
    action: Optional[str] = Field(None, description="Action frontend optionnelle (ex: open_upload)")


class ChatResponse(BaseModel):
    """Réponse de chat"""
    response: str = Field(..., description="Réponse de l'IA")
    sources: Optional[List[Dict[str, Any]]] = Field(None, description="Sources utilisées")
    session_id: Optional[str] = Field(None, description="ID de session")
    context_status: str = Field(default="ok", description="Statut RAG: ok, empty, filtered, no_documents")
    suggestions: Optional[List[Suggestion]] = Field(None, description="Suggestions si pas de contexte")
    topic_changed: bool = Field(default=False, description="True si un changement de sujet a été détecté")
    rag_mode_used: Optional[str] = Field(None, description="Mode RAG utilisé: fast, full ou default")
