"""
Service de chiffrement AES-256-GCM.

Fournit le chiffrement/déchiffrement des données personnelles (PII).
"""
import base64
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.common.crypto.key_manager import get_key_manager

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Erreur lors du chiffrement/déchiffrement."""
    pass


class EncryptionService:
    """
    Service de chiffrement AES-256-GCM.

    AES-256-GCM (Galois/Counter Mode) fournit:
    - Confidentialité: les données sont chiffrées
    - Authentification: toute modification est détectée
    - Performance: chiffrement rapide avec support matériel

    Format du ciphertext: base64(IV || ciphertext || auth_tag)
    - IV: 12 bytes (96 bits) - Initialization Vector unique
    - auth_tag: 16 bytes (128 bits) - inclus automatiquement par GCM
    """

    IV_SIZE = 12  # 96 bits recommandé pour GCM
    KEY_SIZE = 32  # 256 bits

    def __init__(self, key: Optional[bytes] = None):
        """
        Initialise le service de chiffrement.

        Args:
            key: Clé AES-256 de 32 bytes. Si None, utilise KeyManager.
        """
        if key is None:
            key = get_key_manager().aes_key

        if len(key) != self.KEY_SIZE:
            raise ValueError(f"La clé doit faire {self.KEY_SIZE} bytes")

        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        """
        Chiffre une chaîne de caractères.

        Args:
            plaintext: Texte à chiffrer

        Returns:
            Ciphertext encodé en base64

        Raises:
            EncryptionError: Si le chiffrement échoue
        """
        if not plaintext:
            return ""

        try:
            # Génère un IV aléatoire unique pour chaque chiffrement
            iv = os.urandom(self.IV_SIZE)

            # Chiffre les données (GCM inclut automatiquement le tag d'auth)
            ciphertext = self._aesgcm.encrypt(
                nonce=iv,
                data=plaintext.encode('utf-8'),
                associated_data=None
            )

            # Combine IV + ciphertext et encode en base64
            combined = iv + ciphertext
            return base64.b64encode(combined).decode('ascii')

        except Exception as e:
            logger.error(f"Erreur de chiffrement: {e}")
            raise EncryptionError(f"Échec du chiffrement: {e}") from e

    def decrypt(self, ciphertext: str) -> str:
        """
        Déchiffre une chaîne encodée en base64.

        Args:
            ciphertext: Texte chiffré encodé en base64

        Returns:
            Texte déchiffré

        Raises:
            EncryptionError: Si le déchiffrement échoue ou si les données
                           ont été modifiées (échec d'authentification GCM)
        """
        if not ciphertext:
            return ""

        try:
            # Décode le base64
            combined = base64.b64decode(ciphertext)

            if len(combined) < self.IV_SIZE + 16:  # IV + minimum auth tag
                raise EncryptionError("Données chiffrées invalides (trop courtes)")

            # Extrait l'IV et le ciphertext
            iv = combined[:self.IV_SIZE]
            encrypted_data = combined[self.IV_SIZE:]

            # Déchiffre et vérifie l'authenticité
            plaintext = self._aesgcm.decrypt(
                nonce=iv,
                data=encrypted_data,
                associated_data=None
            )

            return plaintext.decode('utf-8')

        except EncryptionError:
            raise
        except Exception as e:
            logger.error(f"Erreur de déchiffrement: {e}")
            raise EncryptionError(f"Échec du déchiffrement: {e}") from e

    def encrypt_optional(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Chiffre une valeur optionnelle.

        Args:
            plaintext: Texte à chiffrer ou None

        Returns:
            Ciphertext ou None si l'entrée est None
        """
        if plaintext is None:
            return None
        return self.encrypt(plaintext)

    def decrypt_optional(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Déchiffre une valeur optionnelle.

        Args:
            ciphertext: Texte chiffré ou None

        Returns:
            Texte déchiffré ou None si l'entrée est None
        """
        if ciphertext is None:
            return None
        return self.decrypt(ciphertext)


# Instance singleton pour usage courant
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """
    Retourne l'instance singleton du service de chiffrement.

    Returns:
        Instance de EncryptionService
    """
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service
