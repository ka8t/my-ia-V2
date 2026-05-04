"""
Crypto Utils

Utilitaires de chiffrement/déchiffrement pour les secrets stockés en BDD.
Utilise Fernet (AES-128-CBC) via cryptography.
"""
import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Clé de chiffrement chargée depuis les variables d'environnement
# Format attendu: clé Fernet base64 de 32 bytes
_ENCRYPTION_KEY: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    """
    Récupère la clé de chiffrement depuis les variables d'environnement.

    La clé doit être au format Fernet (base64, 32 bytes).
    Si non définie, génère une clé temporaire (WARNING: données perdues au redémarrage).

    Returns:
        bytes: Clé Fernet valide
    """
    global _ENCRYPTION_KEY

    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY

    env_key = os.environ.get("ENCRYPTION_KEY", "")

    if env_key:
        try:
            # Valider que c'est une clé Fernet valide
            key_bytes = env_key.encode() if isinstance(env_key, str) else env_key
            Fernet(key_bytes)  # Validation
            _ENCRYPTION_KEY = key_bytes
            logger.debug("Encryption key loaded from environment")
        except Exception as e:
            logger.warning(f"Invalid ENCRYPTION_KEY in environment: {e}")
            _ENCRYPTION_KEY = None

    if _ENCRYPTION_KEY is None:
        # Générer une clé temporaire (données perdues au redémarrage)
        _ENCRYPTION_KEY = Fernet.generate_key()
        logger.warning(
            "ENCRYPTION_KEY not set or invalid. Using temporary key. "
            "Set ENCRYPTION_KEY in .env for persistent encryption."
        )

    return _ENCRYPTION_KEY


def generate_encryption_key() -> str:
    """
    Génère une nouvelle clé de chiffrement Fernet.

    À utiliser pour générer une clé à mettre dans .env.

    Returns:
        str: Clé Fernet en base64
    """
    return Fernet.generate_key().decode()


def encrypt_secret(plaintext: str) -> str:
    """
    Chiffre une valeur sensible avec Fernet.

    Args:
        plaintext: Valeur en clair à chiffrer

    Returns:
        str: Valeur chiffrée encodée en base64
    """
    if not plaintext:
        return ""

    try:
        key = _get_encryption_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        raise ValueError("Failed to encrypt secret") from e


def decrypt_secret(ciphertext: str) -> str:
    """
    Déchiffre une valeur chiffrée avec Fernet.

    Args:
        ciphertext: Valeur chiffrée en base64

    Returns:
        str: Valeur déchiffrée en clair
    """
    if not ciphertext:
        return ""

    try:
        key = _get_encryption_key()
        fernet = Fernet(key)
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.error("Decryption failed: invalid token (wrong key or corrupted data)")
        raise ValueError("Failed to decrypt secret: invalid key or corrupted data")
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        raise ValueError("Failed to decrypt secret") from e


def is_encrypted(value: str) -> bool:
    """
    Vérifie si une valeur semble être chiffrée (format Fernet).

    Args:
        value: Valeur à vérifier

    Returns:
        bool: True si la valeur ressemble à un token Fernet
    """
    if not value or len(value) < 50:
        return False

    try:
        # Les tokens Fernet commencent par "gAAAAA"
        return value.startswith("gAAAAA")
    except Exception:
        return False


def mask_secret(value: str, show_chars: int = 4) -> str:
    """
    Masque une valeur sensible pour l'affichage.

    Args:
        value: Valeur à masquer
        show_chars: Nombre de caractères à afficher au début

    Returns:
        str: Valeur masquée (ex: "smtp****")
    """
    if not value:
        return ""

    if len(value) <= show_chars:
        return "*" * len(value)

    return value[:show_chars] + "*" * (len(value) - show_chars)
