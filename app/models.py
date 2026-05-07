import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyBaseOAuthAccountTableUUID
from sqlalchemy import String, Boolean, Integer, Float, ForeignKey, DateTime, Text, JSON, Enum as SQLEnum, UniqueConstraint, CheckConstraint, Numeric
import enum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base
from app.common.crypto.types import EncryptedString


# --- Enums ---

class DocumentVisibility(str, enum.Enum):
    """Visibilite d'un document pour le RAG"""
    PUBLIC = "public"      # Accessible a tous les utilisateurs
    PRIVATE = "private"    # Accessible uniquement au proprietaire
    SHARED = "shared"      # Partage avec users specifiques (prepare pour le futur)


class CollectionType(str, enum.Enum):
    """Type de collection ChromaDB"""
    PRIVATE = "private"    # Collection privee d'un utilisateur
    PUBLIC = "public"      # Collection publique accessible a tous


class ApprovalStatus(str, enum.Enum):
    """Statut d'approbation d'un utilisateur"""
    PENDING = "pending"      # En attente de validation
    APPROVED = "approved"    # Approuve par un admin/validateur
    REJECTED = "rejected"    # Refuse par un admin/validateur


class SourceType(str, enum.Enum):
    """Type de source de contexte externe"""
    WEB = "web"          # Recherche web (Google, Wikipedia, etc.)
    DATABASE = "database"  # Base de donnees externe
    API = "api"          # API REST tierce


class HealthStatus(str, enum.Enum):
    """Statut de sante d'une source"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class IndexationTrigger(str, enum.Enum):
    """Type de déclencheur d'indexation"""
    MANUAL = "manual"        # Déclenché manuellement par un admin
    SCHEDULED = "scheduled"  # Déclenché par le scheduler automatique
    ON_CREATE = "on_create"  # Déclenché à la création de la source


class IndexationStatus(str, enum.Enum):
    """Statut d'une indexation"""
    PENDING = "pending"    # En attente
    RUNNING = "running"    # En cours
    SUCCESS = "success"    # Terminé avec succès
    FAILED = "failed"      # Échoué


# --- Tables de Référence ---

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # 'user', 'contributor', 'admin'
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ConversationMode(Base):
    __tablename__ = "conversation_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # 'chatbot', 'assistant'
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ResourceType(Base):
    __tablename__ = "resource_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuditAction(Base):
    __tablename__ = "audit_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default='info')  # 'info', 'warning', 'critical'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Tables Principales ---

class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), default=2)  # 2 = User
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # --- Champs de profil chiffres (PII) ---
    # Prenom (chiffre, recherche par trigrammes)
    first_name: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    first_name_search: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String(16)), nullable=True)  # Trigrammes hashes

    # Nom (chiffre, recherche par trigrammes)
    last_name: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    last_name_search: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String(16)), nullable=True)  # Trigrammes hashes

    # Telephone (chiffre, recherche exacte par blind index)
    phone: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    phone_blind_index: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Adresse (chiffre, pas de recherche)
    address_line1: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(EncryptedString(), nullable=True)

    # Localisation (references vers tables geo, pas chiffre)
    city_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cities.id"), nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(2), ForeignKey("countries.code"), nullable=True, default="FR")

    # --- Approbation inscription ---
    approval_status: Mapped[str] = mapped_column(
        SQLEnum(
            ApprovalStatus,
            name="approval_status",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e]
        ),
        default=ApprovalStatus.PENDING,
        nullable=False
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relations
    role: Mapped["Role"] = relationship()
    city: Mapped[Optional["City"]] = relationship()
    country: Mapped[Optional["Country"]] = relationship()
    approver: Mapped[Optional["User"]] = relationship("User", remote_side="User.id", foreign_keys=[approved_by])
    preferences: Mapped["UserPreference"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[List["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    password_history: Mapped[List["PasswordHistory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    collection: Mapped[Optional["Collection"]] = relationship("Collection", back_populates="owner", uselist=False)
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship("OAuthAccount", back_populates="user", lazy="joined")


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """Comptes OAuth lies a un utilisateur (Google, GitHub, etc.)."""
    __tablename__ = "oauth_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Relations
    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts")

class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    top_k: Mapped[int] = mapped_column(Integer, default=4)
    show_sources: Mapped[bool] = mapped_column(Boolean, default=True)
    theme: Mapped[str] = mapped_column(String(20), default="light")
    language: Mapped[str] = mapped_column(String(5), default="fr")
    default_mode_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversation_modes.id"), default=1)
    voice_to_text_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Transcription vocale Whisper
    voice_auto_send: Mapped[bool] = mapped_column(Boolean, default=False)  # Auto-envoi après silence détecté
    voice_tts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Lecture vocale des réponses
    voice_tts_auto_play: Mapped[bool] = mapped_column(Boolean, default=True)  # Lecture automatique sans clic
    voice_tts_voice: Mapped[str] = mapped_column(String(100), default="")  # Voix TTS sélectionnée
    voice_tts_rate: Mapped[float] = mapped_column(Float, default=1.0)  # Vitesse de lecture TTS (0.5-2.0)
    rag_mode: Mapped[str] = mapped_column(String(10), default="auto")  # Mode RAG: auto, fast, full

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    user: Mapped["User"] = relationship(back_populates="preferences")
    default_mode: Mapped["ConversationMode"] = relationship()

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    mode_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversation_modes.id"), default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # Archivage
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Résumé automatique des conversations longues

    # Relations
    user: Mapped["User"] = relationship(back_populates="conversations")
    collection: Mapped["Collection"] = relationship("Collection", back_populates="conversations")
    mode: Mapped["ConversationMode"] = relationship()
    messages: Mapped[List["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False) # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[Optional[dict]] = mapped_column(JSON)
    response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Temps de reponse en secondes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # Soft delete

    # Relations
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

class Document(Base):
    """
    Document uploadé.

    Un document peut appartenir à plusieurs corpus (relation N à N via corpus_documents)
    et/ou à une collection privée (docs privés d'un utilisateur).
    """
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint('user_id', 'file_hash', name='uq_document_user_file_hash'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    # Document dans une collection privée (docs privés utilisateur)
    collection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str] = mapped_column(String(150), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)  # Chemin relatif dans le storage
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_count: Mapped[int] = mapped_column(Integer, default=0)  # Nombre d'embeddings dans ChromaDB
    indexed_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # Provider utilisé pour l'indexation (ollama/llamacpp)
    current_version: Mapped[int] = mapped_column(Integer, default=1)  # Version courante
    visibility: Mapped[DocumentVisibility] = mapped_column(
        SQLEnum(
            DocumentVisibility,
            name="document_visibility",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e]  # Utilise 'public'/'private'/'shared'
        ),
        default=DocumentVisibility.PUBLIC,
        nullable=False
    )
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # Admin peut desindexer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    user: Mapped["User"] = relationship(back_populates="documents")
    collection: Mapped[Optional["Collection"]] = relationship("Collection", back_populates="documents")
    versions: Mapped[List["DocumentVersion"]] = relationship(back_populates="document", cascade="all, delete-orphan", order_by="DocumentVersion.version_number")
    shares: Mapped[List["DocumentShare"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    # Relation N à N avec Corpus via table pivot
    corpus_memberships: Mapped[List["CorpusDocument"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan"
    )

    @property
    def corpus_list(self) -> List["Corpus"]:
        """Accès direct aux corpus du document."""
        return [cm.corpus for cm in self.corpus_memberships]

    @property
    def corpus_count(self) -> int:
        """Nombre de corpus associés."""
        return len(self.corpus_memberships)

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    refresh_token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))

    # Relations
    user: Mapped["User"] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action_id: Mapped[int] = mapped_column(ForeignKey("audit_actions.id"), nullable=False)
    resource_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("resource_types.id"))
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    user: Mapped["User"] = relationship()
    action: Mapped["AuditAction"] = relationship()
    resource_type: Mapped["ResourceType"] = relationship()


# --- Tables Versioning & Partage Documents ---

class DocumentVersion(Base):
    """Historique des versions d'un document."""
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)  # Chemin relatif dans le storage
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # Nombre de chunks de cette version
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Note optionnelle
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relations
    document: Mapped["Document"] = relationship(back_populates="versions")
    creator: Mapped["User"] = relationship()


class DocumentShare(Base):
    """Partage d'un document avec un utilisateur specifique (prepare pour le futur)."""
    __tablename__ = "document_shares"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    shared_with_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(20), default="read")  # "read" | "write" (futur)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relations
    document: Mapped["Document"] = relationship(back_populates="shares")
    shared_with: Mapped["User"] = relationship(foreign_keys=[shared_with_user_id])
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])

    # Contrainte unique: un document ne peut etre partage qu'une fois avec le meme utilisateur
    __table_args__ = (
        UniqueConstraint('document_id', 'shared_with_user_id', name='uq_document_share_user'),
    )


class UserQuota(Base):
    """Quota de stockage personnalise par utilisateur (optionnel)."""
    __tablename__ = "user_quotas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    quota_bytes: Mapped[int] = mapped_column(Integer, nullable=False)  # Quota en bytes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relations
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


# --- Tables Geographiques ---

class Country(Base):
    """Table des pays avec drapeaux."""
    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)  # ISO 3166-1 alpha-2 (FR, US, DE...)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flag: Mapped[str] = mapped_column(String(10), nullable=False)  # Emoji drapeau
    phone_prefix: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # +33, +1, etc.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # Visible dans la liste
    display_order: Mapped[int] = mapped_column(Integer, default=999)  # Ordre d'affichage (FR en premier)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class City(Base):
    """Table des villes avec codes postaux."""
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), ForeignKey("countries.code"), nullable=False)
    department_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # Code departement (France)
    department_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(10, 8), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(11, 8), nullable=True)
    population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Pour tri par pertinence
    search_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # Nom normalise sans accents

    # Index composite pour recherche rapide
    __table_args__ = (
        # Index pour recherche par nom + pays
        # Index pour recherche par code postal + pays
    )

    # Relations
    country: Mapped["Country"] = relationship()


# --- Tables Politique Mot de Passe ---

class PasswordPolicy(Base):
    """Politique de mot de passe configurable."""
    __tablename__ = "password_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # 'default', 'admin', 'strict'
    min_length: Mapped[int] = mapped_column(Integer, default=8)
    max_length: Mapped[int] = mapped_column(Integer, default=128)
    require_uppercase: Mapped[bool] = mapped_column(Boolean, default=True)
    require_lowercase: Mapped[bool] = mapped_column(Boolean, default=True)
    require_digit: Mapped[bool] = mapped_column(Boolean, default=True)
    require_special: Mapped[bool] = mapped_column(Boolean, default=True)
    special_characters: Mapped[str] = mapped_column(String(50), default="!@#$%^&*()_+-=[]{}|;:,.<>?")
    expire_days: Mapped[int] = mapped_column(Integer, default=0)  # 0 = jamais
    history_count: Mapped[int] = mapped_column(Integer, default=0)  # Nombre d'anciens mdp interdits
    max_failed_attempts: Mapped[int] = mapped_column(Integer, default=5)
    lockout_duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PasswordHistory(Base):
    """Historique des mots de passe pour eviter la reutilisation."""
    __tablename__ = "password_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    user: Mapped["User"] = relationship(back_populates="password_history")

    __table_args__ = (
        # Index pour recherche rapide par user
    )


# --- Configuration Systeme ---

class SystemConfig(Base):
    """Configuration systeme dynamique (cle/valeur avec type)."""
    __tablename__ = "system_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # Valeur stockee en string
    value_type: Mapped[str] = mapped_column(String(20), default="string")  # string, int, float, bool, json, list
    category: Mapped[str] = mapped_column(String(50), default="general")  # storage, security, rag, general
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)  # Masquer dans les logs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relations
    updater: Mapped[Optional["User"]] = relationship(foreign_keys=[updated_by])


# --- Bibliothèque (table: collections) ---
# Terminologie : "Bibliothèque" côté UI, "Collection" côté technique ChromaDB.

class Collection(Base):
    """Bibliothèque de documents (UI: 'Bibliothèque' / 'Library').
    Table PostgreSQL: collections. Chaque bibliothèque génère 1+ collections ChromaDB (1 par provider LLM)."""
    __tablename__ = "collections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # Nom technique ChromaDB
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)  # Nom affiche
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'private' | 'public'
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    # Corpus assigné à cette collection (ensemble de sources pour le RAG)
    corpus_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("corpus.id", ondelete="SET NULL"), nullable=True, index=True
    )

    space: Mapped[str] = mapped_column(String(20), default="cosine")  # cosine | l2 | ip
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    # Modele d'embedding utilise pour l'indexation
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Cache des questions suggerees (generees par Ollama)
    suggested_questions: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    suggestions_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    owner: Mapped[Optional["User"]] = relationship("User", back_populates="collection")
    corpus: Mapped[Optional["Corpus"]] = relationship("Corpus", back_populates="assigned_collections")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="collection")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="collection")
    context_sources: Mapped[List["CollectionSource"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="CollectionSource.priority"
    )
    corpus_memberships: Mapped[List["CorpusCollection"]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan"
    )


class ContextSource(Base):
    """Source de contexte externe pour enrichir le RAG."""
    __tablename__ = "context_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # Slug technique
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'web' | 'database' | 'api'
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_results: Mapped[int] = mapped_column(Integer, default=5)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # Plus petit = plus prioritaire

    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Configuration d'indexation par source ---
    index_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # Indexation activée pour cette source
    index_ttl_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # TTL en heures (NULL = config globale)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, default=False)  # Ré-indexation automatique
    refresh_interval_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Intervalle de rafraîchissement
    replace_on_refresh: Mapped[bool] = mapped_column(Boolean, default=True)  # Remplacer l'index existant
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # Dernière indexation réussie
    last_content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Hash du dernier contenu
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)  # Nombre de chunks indexés
    indexed_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # Provider utilisé pour l'indexation (ollama/llamacpp)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    indexation_logs: Mapped[List["SourceIndexationLog"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="desc(SourceIndexationLog.indexed_at)"
    )
    collections: Mapped[List["CollectionSource"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan"
    )
    corpus_sources: Mapped[List["CorpusSource"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan"
    )


class SourceIndexationLog(Base):
    """Historique des indexations d'une source de contexte."""
    __tablename__ = "source_indexation_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("context_sources.id", ondelete="CASCADE"), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Statistiques
    documents_count: Mapped[int] = mapped_column(Integer, default=0)  # Nombre de documents indexés
    replaced_count: Mapped[int] = mapped_column(Integer, default=0)   # Nombre de documents remplacés

    # Déclencheur
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'manual', 'scheduled', 'on_create'
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Détection de changements
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Hash SHA256 du contenu
    content_changed: Mapped[bool] = mapped_column(Boolean, default=False)  # Le contenu a-t-il changé ?

    # Résultat
    status: Mapped[str] = mapped_column(String(20), default="pending")  # 'pending', 'running', 'success', 'failed'
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Durée en millisecondes

    # Progression
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100%
    progress_message: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Étape en cours

    # Relations
    source: Mapped["ContextSource"] = relationship(back_populates="indexation_logs")
    triggered_by_user: Mapped[Optional["User"]] = relationship(foreign_keys=[triggered_by])


class Corpus(Base):
    """
    Corpus thématique contenant documents et sources pour le RAG.

    Un corpus regroupe :
    - Des documents (uploadés par l'admin)
    - Des sources externes (web, API, MCP, etc.)

    Une collection publique peut être assignée à un corpus pour utiliser
    son contenu lors des chats. Les collections privées peuvent aussi
    utiliser un corpus en plus de leurs propres documents.
    """
    __tablename__ = "corpus"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # Slug technique
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    # Relation N à N avec Documents via table pivot
    corpus_documents: Mapped[List["CorpusDocument"]] = relationship(
        back_populates="corpus",
        cascade="all, delete-orphan",
        order_by="CorpusDocument.priority"
    )
    sources: Mapped[List["CorpusSource"]] = relationship(
        back_populates="corpus",
        cascade="all, delete-orphan",
        order_by="CorpusSource.priority"
    )
    # Collections qui ont ce corpus assigné (relation inverse de Collection.corpus)
    assigned_collections: Mapped[List["Collection"]] = relationship(
        back_populates="corpus",
        foreign_keys="Collection.corpus_id"
    )
    # Legacy: relation N-N (à supprimer après migration)
    collections: Mapped[List["CorpusCollection"]] = relationship(
        back_populates="corpus",
        cascade="all, delete-orphan",
        order_by="CorpusCollection.priority"
    )

    @property
    def documents(self) -> List["Document"]:
        """Accès direct aux documents du corpus."""
        return [cd.document for cd in self.corpus_documents]

    @property
    def document_count(self) -> int:
        """Nombre de documents dans ce corpus."""
        return len(self.corpus_documents)


class CorpusCollection(Base):
    """
    Table de liaison entre Corpus et Collections.

    Seules les collections PUBLIQUES peuvent être ajoutées à un corpus.
    Les collections privées des utilisateurs ne sont pas éligibles.
    """
    __tablename__ = "corpus_collections"
    __table_args__ = (
        UniqueConstraint('corpus_id', 'collection_id', name='uq_corpus_collection'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)  # Plus petit = plus prioritaire

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    corpus: Mapped["Corpus"] = relationship(back_populates="collections")
    collection: Mapped["Collection"] = relationship(back_populates="corpus_memberships")


class CorpusSource(Base):
    """
    Table de liaison entre Corpus et Sources de contexte.

    Permet d'associer des sources externes à un corpus thématique.
    """
    __tablename__ = "corpus_sources"
    __table_args__ = (
        UniqueConstraint('corpus_id', 'source_id', name='uq_corpus_source'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("context_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)  # Plus petit = plus prioritaire
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    corpus: Mapped["Corpus"] = relationship(back_populates="sources")
    source: Mapped["ContextSource"] = relationship(back_populates="corpus_sources")


class CorpusDocument(Base):
    """
    Table de liaison entre Corpus et Documents (relation N à N).

    Permet à un document d'appartenir à plusieurs corpus thématiques.
    """
    __tablename__ = "corpus_documents"
    __table_args__ = (
        UniqueConstraint('corpus_id', 'document_id', name='uq_corpus_document'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpus.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    corpus: Mapped["Corpus"] = relationship(back_populates="corpus_documents")
    document: Mapped["Document"] = relationship(back_populates="corpus_memberships")


class CollectionSource(Base):
    """
    Table de liaison entre Collections et Sources de contexte.

    Permet d'assigner des sources externes à des collections spécifiques,
    avec priorité et activation par collection.
    """
    __tablename__ = "collection_sources"
    __table_args__ = (
        UniqueConstraint('collection_id', 'source_id', name='uq_collection_source'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("context_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Configuration par collection
    priority: Mapped[int] = mapped_column(Integer, default=100)  # Plus petit = plus prioritaire
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Activé pour cette collection

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    collection: Mapped["Collection"] = relationship(back_populates="context_sources")
    source: Mapped["ContextSource"] = relationship(back_populates="collections")


# --- Logging structuré ---

class AppLog(Base):
    """
    Logs applicatifs structurés persistés en base de données.

    Stocke les logs de toutes les catégories (technical, access, audit, security, infra)
    avec enrichissement automatique (request_id, user_id, contexte métier).

    Voir: docs/plans/PLAN-LOGGING.html — Phase 5.
    """
    __tablename__ = "app_logs"
    __table_args__ = (
        # Index composites pour les requêtes fréquentes
        {"comment": "Logs applicatifs structurés — 5 catégories, format JSON"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Classification
    level: Mapped[str] = mapped_column(String(10), index=True)
    log_category: Mapped[str] = mapped_column(String(20), index=True)

    # Service et environnement
    service: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    environment: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Corrélation
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Contenu
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Métadonnées réseau
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Source du log
    logger_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Alerting (Phase 9)
    is_alert: Mapped[bool] = mapped_column(Boolean, default=False)
