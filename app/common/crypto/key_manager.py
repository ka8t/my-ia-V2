"""
Gestion des clés de chiffrement.

Fournit la dérivation sécurisée des clés pour AES et HMAC.
"""
import hashlib
import hmac
import logging
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


class KeyManager:
    """
    Gestionnaire de clés de chiffrement.

    Dérive des clés séparées pour AES (chiffrement) et HMAC (blind index)
    à partir d'une clé maître unique.
    """

    # Contextes pour la dérivation HKDF (doivent être uniques par usage)
    AES_CONTEXT = b"my-ia-aes-encryption-v1"
    HMAC_CONTEXT = b"my-ia-hmac-blind-index-v1"

    def __init__(self, master_key: bytes):
        """
        Initialise le gestionnaire avec une clé maître.

        Args:
            master_key: Clé maître de 32 bytes (256 bits)

        Raises:
            ValueError: Si la clé n'a pas la bonne taille
        """
        if len(master_key) != 32:
            raise ValueError(f"La clé maître doit faire 32 bytes, reçu {len(master_key)}")

        self._master_key = master_key
        self._aes_key: bytes | None = None
        self._hmac_key: bytes | None = None

    def _derive_key(self, context: bytes, length: int = 32) -> bytes:
        """
        Dérive une clé à partir de la clé maître via HKDF.

        Args:
            context: Contexte unique pour cette dérivation
            length: Longueur de la clé dérivée en bytes

        Returns:
            Clé dérivée
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=None,  # Pas de sel, la clé maître est déjà aléatoire
            info=context,
        )
        return hkdf.derive(self._master_key)

    @property
    def aes_key(self) -> bytes:
        """
        Retourne la clé AES-256 pour le chiffrement.

        La clé est dérivée une seule fois et mise en cache.
        """
        if self._aes_key is None:
            self._aes_key = self._derive_key(self.AES_CONTEXT)
        return self._aes_key

    @property
    def hmac_key(self) -> bytes:
        """
        Retourne la clé HMAC pour les blind index.

        La clé est dérivée une seule fois et mise en cache.
        """
        if self._hmac_key is None:
            self._hmac_key = self._derive_key(self.HMAC_CONTEXT)
        return self._hmac_key

    def clear_cache(self) -> None:
        """Efface les clés dérivées du cache (pour rotation de clé)."""
        self._aes_key = None
        self._hmac_key = None


@lru_cache(maxsize=1)
def get_key_manager() -> KeyManager:
    """
    Retourne l'instance singleton du gestionnaire de clés.

    La clé est lue depuis la variable d'environnement ENCRYPTION_KEY.

    Returns:
        Instance de KeyManager

    Raises:
        ValueError: Si ENCRYPTION_KEY n'est pas définie ou invalide
    """
    from app.core.config import settings

    encryption_key = getattr(settings, 'encryption_key', None)

    if not encryption_key:
        raise ValueError(
            "ENCRYPTION_KEY non définie. "
            "Générez une clé avec: openssl rand -hex 32"
        )

    try:
        key_bytes = bytes.fromhex(encryption_key)
    except ValueError as e:
        raise ValueError(
            f"ENCRYPTION_KEY doit être une chaîne hexadécimale de 64 caractères: {e}"
        )

    if len(key_bytes) != 32:
        raise ValueError(
            f"ENCRYPTION_KEY doit faire 32 bytes (64 caractères hex), "
            f"reçu {len(key_bytes)} bytes"
        )

    logger.info("KeyManager initialisé avec succès")
    return KeyManager(key_bytes)


def generate_encryption_key() -> str:
    """
    Génère une nouvelle clé de chiffrement aléatoire.

    Returns:
        Clé hexadécimale de 64 caractères (256 bits)
    """
    return os.urandom(32).hex()
