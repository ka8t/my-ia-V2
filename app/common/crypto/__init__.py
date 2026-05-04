"""
Module de chiffrement pour les données personnelles (PII).

Fournit:
- AES-256-GCM pour le chiffrement/déchiffrement
- HMAC-SHA256 pour les blind index (recherche exacte)
- Trigrammes hashés pour la recherche partielle
- Types SQLAlchemy pour chiffrement automatique

Usage:
    from app.common.crypto import (
        EncryptionService,
        SearchIndexService,
        EncryptedString,
        get_encryption_service,
        get_search_index_service
    )

    # Chiffrement manuel
    service = get_encryption_service()
    encrypted = service.encrypt("données sensibles")
    decrypted = service.decrypt(encrypted)

    # Index de recherche
    search_service = get_search_index_service()
    blind_index = search_service.create_blind_index("test@email.com")
    trigram_index = search_service.create_trigram_index("Jean Dupont")

    # Dans un modèle SQLAlchemy (chiffrement automatique)
    class User(Base):
        first_name = Column(EncryptedString(), nullable=True)
"""

from app.common.crypto.encryption import (
    EncryptionError,
    EncryptionService,
    get_encryption_service,
)
from app.common.crypto.key_manager import (
    KeyManager,
    generate_encryption_key,
    get_key_manager,
)
from app.common.crypto.search import (
    SearchIndexService,
    get_search_index_service,
)
from app.common.crypto.types import (
    EncryptedString,
    EncryptedStringSearchable,
)

__all__ = [
    # Encryption
    "EncryptionService",
    "EncryptionError",
    "get_encryption_service",
    # Key management
    "KeyManager",
    "get_key_manager",
    "generate_encryption_key",
    # Search indexing
    "SearchIndexService",
    "get_search_index_service",
    # SQLAlchemy types
    "EncryptedString",
    "EncryptedStringSearchable",
]
