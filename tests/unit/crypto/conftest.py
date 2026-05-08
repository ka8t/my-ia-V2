"""
Fixtures pour les tests crypto.
"""
import os
import pytest


@pytest.fixture(scope="module")
def test_encryption_key() -> bytes:
    """Clé de chiffrement de test (32 bytes)."""
    return bytes.fromhex("0" * 64)


@pytest.fixture(scope="module")
def test_hmac_key() -> bytes:
    """Clé HMAC de test (32 bytes)."""
    return bytes.fromhex("1" * 64)


@pytest.fixture(autouse=True)
def set_encryption_key_env(monkeypatch):
    """
    Configure la variable d'environnement ENCRYPTION_KEY pour les tests.

    Cette fixture est appliquée automatiquement à tous les tests.
    """
    test_key = "0" * 64  # 32 bytes en hex
    monkeypatch.setenv("ENCRYPTION_KEY", test_key)
