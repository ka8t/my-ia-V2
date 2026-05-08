"""
Tests pour le service de chiffrement AES-256-GCM.

Execution: docker-compose exec app python -m pytest tests/crypto/test_encryption.py -v
"""
import pytest

from app.common.crypto.encryption import EncryptionService, EncryptionError
from app.common.crypto.key_manager import KeyManager


class TestEncryptionService:
    """Tests pour EncryptionService."""

    @pytest.fixture
    def service(self, test_encryption_key: bytes) -> EncryptionService:
        """Instance du service avec clé de test."""
        return EncryptionService(key=test_encryption_key)

    def test_encrypt_decrypt_simple(self, service: EncryptionService):
        """Chiffrement/déchiffrement d'une chaîne simple."""
        plaintext = "Hello, World!"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_encrypt_decrypt_unicode(self, service: EncryptionService):
        """Chiffrement de caractères Unicode (accents, emojis)."""
        plaintext = "Bonjour le monde! 🌍 Éàü"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext

    def test_encrypt_decrypt_long_text(self, service: EncryptionService):
        """Chiffrement d'un texte long."""
        plaintext = "A" * 10000
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext

    def test_encrypt_empty_string(self, service: EncryptionService):
        """Chiffrement d'une chaîne vide retourne chaîne vide."""
        encrypted = service.encrypt("")
        assert encrypted == ""

        decrypted = service.decrypt("")
        assert decrypted == ""

    def test_encrypt_different_iv_each_time(self, service: EncryptionService):
        """Chaque chiffrement produit un résultat différent (IV unique)."""
        plaintext = "Same text"
        encrypted1 = service.encrypt(plaintext)
        encrypted2 = service.encrypt(plaintext)

        # Les deux chiffrements doivent être différents (IV différent)
        assert encrypted1 != encrypted2

        # Mais les deux doivent déchiffrer vers le même texte
        assert service.decrypt(encrypted1) == plaintext
        assert service.decrypt(encrypted2) == plaintext

    def test_decrypt_tampered_data_fails(self, service: EncryptionService):
        """Le déchiffrement de données modifiées échoue (GCM auth)."""
        plaintext = "Sensitive data"
        encrypted = service.encrypt(plaintext)

        # Modifie le ciphertext (simule une attaque)
        import base64
        data = bytearray(base64.b64decode(encrypted))
        data[-1] ^= 0xFF  # Modifie le dernier byte
        tampered = base64.b64encode(bytes(data)).decode('ascii')

        with pytest.raises(EncryptionError):
            service.decrypt(tampered)

    def test_decrypt_invalid_base64_fails(self, service: EncryptionService):
        """Le déchiffrement de base64 invalide échoue."""
        with pytest.raises(EncryptionError):
            service.decrypt("not-valid-base64!!!")

    def test_decrypt_too_short_fails(self, service: EncryptionService):
        """Le déchiffrement de données trop courtes échoue."""
        import base64
        short_data = base64.b64encode(b"short").decode('ascii')

        with pytest.raises(EncryptionError):
            service.decrypt(short_data)

    def test_encrypt_optional_none(self, service: EncryptionService):
        """encrypt_optional avec None retourne None."""
        result = service.encrypt_optional(None)
        assert result is None

    def test_decrypt_optional_none(self, service: EncryptionService):
        """decrypt_optional avec None retourne None."""
        result = service.decrypt_optional(None)
        assert result is None

    def test_encrypt_decrypt_optional(self, service: EncryptionService):
        """encrypt/decrypt_optional fonctionne avec une valeur."""
        plaintext = "Test value"
        encrypted = service.encrypt_optional(plaintext)
        decrypted = service.decrypt_optional(encrypted)

        assert decrypted == plaintext

    def test_wrong_key_fails_decrypt(self, test_encryption_key: bytes):
        """Déchiffrement avec mauvaise clé échoue."""
        service1 = EncryptionService(key=test_encryption_key)

        # Clé différente
        other_key = bytes.fromhex("F" * 64)
        service2 = EncryptionService(key=other_key)

        plaintext = "Secret message"
        encrypted = service1.encrypt(plaintext)

        with pytest.raises(EncryptionError):
            service2.decrypt(encrypted)


class TestKeyManager:
    """Tests pour KeyManager."""

    def test_init_with_valid_key(self, test_encryption_key: bytes):
        """Initialisation avec clé valide."""
        manager = KeyManager(test_encryption_key)
        assert manager.aes_key is not None
        assert manager.hmac_key is not None

    def test_init_with_invalid_key_size(self):
        """Initialisation avec clé de mauvaise taille échoue."""
        with pytest.raises(ValueError) as exc_info:
            KeyManager(b"too-short")

        assert "32 bytes" in str(exc_info.value)

    def test_derived_keys_are_different(self, test_encryption_key: bytes):
        """Les clés AES et HMAC sont différentes."""
        manager = KeyManager(test_encryption_key)

        assert manager.aes_key != manager.hmac_key
        assert len(manager.aes_key) == 32
        assert len(manager.hmac_key) == 32

    def test_derived_keys_are_deterministic(self, test_encryption_key: bytes):
        """Les clés dérivées sont toujours identiques pour la même clé maître."""
        manager1 = KeyManager(test_encryption_key)
        manager2 = KeyManager(test_encryption_key)

        assert manager1.aes_key == manager2.aes_key
        assert manager1.hmac_key == manager2.hmac_key

    def test_clear_cache(self, test_encryption_key: bytes):
        """clear_cache efface les clés en mémoire."""
        manager = KeyManager(test_encryption_key)

        # Accède aux clés pour les mettre en cache
        aes1 = manager.aes_key
        hmac1 = manager.hmac_key

        manager.clear_cache()

        # Les clés sont recalculées
        aes2 = manager.aes_key
        hmac2 = manager.hmac_key

        # Mais identiques (déterministe)
        assert aes1 == aes2
        assert hmac1 == hmac2
