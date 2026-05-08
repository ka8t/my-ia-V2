"""
Fixtures pour les tests du module Storage.

Execution: docker-compose exec app python -m pytest tests/storage/ -v
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from app.common.storage.backends.local import LocalStorageBackend
from app.common.storage.schemas import QuotaConfig
from app.common.storage.service import StorageService


@pytest.fixture(scope="session")
def event_loop():
    """Event loop unique pour eviter conflits."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def temp_storage_path():
    """Cree un repertoire temporaire pour les tests de storage."""
    temp_dir = tempfile.mkdtemp(prefix="test_storage_")
    yield temp_dir
    # Cleanup apres le test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def local_backend(temp_storage_path):
    """Backend local avec repertoire temporaire."""
    return LocalStorageBackend(base_path=temp_storage_path)


@pytest.fixture(scope="function")
def quota_config():
    """Configuration des quotas pour les tests."""
    return QuotaConfig(
        default_quota_bytes=100 * 1024 * 1024,  # 100 MB
        max_file_size_bytes=10 * 1024 * 1024,   # 10 MB
        allowed_mime_types=[
            "application/pdf",
            "text/plain",
            "text/csv",
            "application/json",
        ],
        blocked_extensions=[".exe", ".bat", ".sh"],
    )


@pytest.fixture(scope="function")
def storage_service(local_backend, quota_config):
    """Service de stockage avec backend local et quotas."""
    return StorageService(backend=local_backend, quota_config=quota_config)


@pytest.fixture(scope="function")
def test_user_id():
    """ID utilisateur de test."""
    return uuid4()


@pytest.fixture(scope="function")
def test_document_id():
    """ID document de test."""
    return uuid4()


@pytest.fixture(scope="function")
def sample_pdf_content():
    """Contenu PDF fictif pour les tests."""
    # Header PDF minimal
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


@pytest.fixture(scope="function")
def sample_text_content():
    """Contenu texte pour les tests."""
    return b"Hello, this is a test document content.\nWith multiple lines."


@pytest.fixture(scope="function")
def large_content():
    """Contenu volumineux (15 MB) pour tester les limites."""
    return b"X" * (15 * 1024 * 1024)  # 15 MB
