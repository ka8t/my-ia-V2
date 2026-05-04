"""
Schemas Conversations

Schémas Pydantic pour les conversations utilisateur.
"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# =============================================================================
# CRÉATION
# =============================================================================

class ConversationCreate(BaseModel):
    """Schema pour creer une conversation"""
    title: str = Field(..., min_length=1, max_length=500, description="Titre de la conversation")
    collection_id: uuid.UUID = Field(..., description="ID de la collection ChromaDB cible")
    mode_id: int = Field(default=1, ge=1, description="ID du mode de conversation (1=chatbot, 2=assistant)")


class MessageCreate(BaseModel):
    """Schéma pour créer un message"""
    sender_type: str = Field(..., pattern="^(user|assistant)$", description="Type d'expéditeur")
    content: str = Field(..., min_length=1, description="Contenu du message")
    sources: Optional[Dict[str, Any]] = Field(None, description="Sources RAG utilisées")
    response_time: Optional[float] = Field(None, description="Temps de réponse en secondes")


# =============================================================================
# LECTURE
# =============================================================================

class MessageRead(BaseModel):
    """Schéma de lecture d'un message"""
    id: uuid.UUID
    sender_type: str
    content: str
    sources: Optional[Dict[str, Any]] = None
    response_time: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationRead(BaseModel):
    """Schema de lecture d'une conversation (liste)"""
    id: uuid.UUID
    title: str
    collection_id: uuid.UUID
    collection_name: Optional[str] = None
    mode_id: int
    mode_name: Optional[str] = None
    messages_count: int = 0
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    """Schema de lecture detaillee d'une conversation avec messages"""
    id: uuid.UUID
    title: str
    collection_id: uuid.UUID
    collection_name: Optional[str] = None
    mode_id: int
    mode_name: Optional[str] = None
    messages: List[MessageRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# MISE À JOUR
# =============================================================================

class ConversationUpdate(BaseModel):
    """Schéma de mise à jour d'une conversation"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)


# =============================================================================
# RÉPONSES
# =============================================================================

class ConversationListResponse(BaseModel):
    """Réponse pour la liste des conversations"""
    items: List[ConversationRead]
    total: int
    limit: int
    offset: int


# =============================================================================
# CHAT
# =============================================================================

class ChatRequest(BaseModel):
    """Requête de chat dans une conversation"""
    query: str = Field(..., min_length=1, description="Question de l'utilisateur")


class Suggestion(BaseModel):
    """Suggestion d'action quand le RAG ne trouve pas de résultats"""
    suggestion_type: str = Field(..., description="Type: lower_threshold, add_documents, rephrase, check_collection")
    message: str = Field(..., description="Message affiché à l'utilisateur")
    action: Optional[str] = Field(None, description="Action frontend optionnelle (ex: open_upload)")


class ChatResponse(BaseModel):
    """Réponse de chat avec le message sauvegardé"""
    response: str = Field(..., description="Réponse de l'IA")
    sources: Optional[List[Dict[str, Any]]] = Field(None, description="Sources RAG")
    user_message: MessageRead = Field(..., description="Message utilisateur sauvegardé")
    assistant_message: MessageRead = Field(..., description="Message assistant sauvegardé")
    context_status: str = Field(default="ok", description="Statut RAG: ok, empty, filtered, no_documents")
    suggestions: Optional[List[Suggestion]] = Field(None, description="Suggestions si pas de contexte")


class MessageDeleteRequest(BaseModel):
    """Requête pour supprimer des messages"""
    message_ids: List[uuid.UUID] = Field(..., min_length=1, description="IDs des messages à supprimer")


class MessageDeleteResponse(BaseModel):
    """Réponse de suppression de messages"""
    deleted_count: int = Field(..., description="Nombre de messages supprimés")
