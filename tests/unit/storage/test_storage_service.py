"""
Tests unitaires pour StorageService.

Execution: docker-compose exec app python -m pytest tests/storage/test_storage_service.py -v
"""

import pytest
from uuid import uuid4

from app.common.storage.service import StorageService
from app.common.storage.backends.local import LocalStorageBackend
from app.common.storage.schemas import QuotaConfig, UserStorageStats
from app.common.storage.exceptions import (
    QuotaExceededError,
    FileTooLargeError,
    InvalidFileTypeError,
    StorageFileNotFoundError,
)


pytestmark = pytest.mark.asyncio


class TestStorageServiceUpload:
    """Tests pour la methode upload()."""

    async def test_upload_success(
        self, storage_service: StorageService, test_user_id, test_document_id, sample_text_content
    ):
        """Upload un fichier avec succes."""
        file_path = await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="test.txt",
            content=sample_text_content,
            mime_type="text/plain",
        )

        assert file_path is not None
        assert str(test_user_id) in file_path

    async def test_upload_with_version(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Upload avec numero de version specifique."""
        file_path = await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.pdf",
            content=b"%PDF-1.4\n",
            mime_type="application/pdf",
            version=5,
        )

        assert "v5_" in file_path

    async def test_upload_file_too_large(
        self, storage_service: StorageService, test_user_id, test_document_id, large_content
    ):
        """Rejette un fichier trop volumineux."""
        with pytest.raises(FileTooLargeError) as exc_info:
            await storage_service.upload(
                user_id=test_user_id,
                document_id=test_document_id,
                filename="large.txt",
                content=large_content,
                mime_type="text/plain",
            )

        # Message en francais: "Fichier trop volumineux"
        assert "volumineux" in str(exc_info.value).lower() or "15" in str(exc_info.value)

    async def test_upload_invalid_mime_type(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Rejette un type MIME non autorise."""
        with pytest.raises(InvalidFileTypeError) as exc_info:
            await storage_service.upload(
                user_id=test_user_id,
                document_id=test_document_id,
                filename="script.exe",
                content=b"MZ",  # EXE header
                mime_type="application/x-msdownload",
            )

        # Message en francais: "non autorisé"
        assert "autorisé" in str(exc_info.value).lower() or "x-msdownload" in str(exc_info.value)

    async def test_upload_blocked_extension(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Rejette une extension bloquee."""
        with pytest.raises(InvalidFileTypeError) as exc_info:
            await storage_service.upload(
                user_id=test_user_id,
                document_id=test_document_id,
                filename="script.bat",
                content=b"echo hello",
                mime_type="text/plain",  # Mime type OK mais extension bloquee
            )

        # Message en francais: "bloquée"
        assert "bloquée" in str(exc_info.value).lower() or ".bat" in str(exc_info.value)

    async def test_upload_quota_exceeded(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Rejette si le quota est depasse."""
        # Creer un service avec quota tres petit
        tiny_quota_config = QuotaConfig(
            default_quota_bytes=100,  # 100 bytes seulement
            max_file_size_bytes=10 * 1024 * 1024,
            allowed_mime_types=["text/plain"],
            blocked_extensions=[],
        )
        service = StorageService(backend=local_backend, quota_config=tiny_quota_config)

        # Premier upload OK
        await service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="small.txt",
            content=b"A" * 50,
            mime_type="text/plain",
        )

        # Deuxieme upload depasse le quota
        with pytest.raises(QuotaExceededError) as exc_info:
            await service.upload(
                user_id=test_user_id,
                document_id=uuid4(),
                filename="another.txt",
                content=b"B" * 100,
                mime_type="text/plain",
            )

        assert "quota" in str(exc_info.value).lower()

    async def test_upload_skip_quota_check(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Permet de bypasser la verification de quota."""
        tiny_quota_config = QuotaConfig(
            default_quota_bytes=10,  # 10 bytes
            max_file_size_bytes=10 * 1024 * 1024,
            allowed_mime_types=["text/plain"],
            blocked_extensions=[],
        )
        service = StorageService(backend=local_backend, quota_config=tiny_quota_config)

        # Devrait reussir car check_quota=False
        file_path = await service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="big.txt",
            content=b"A" * 1000,
            mime_type="text/plain",
            check_quota=False,
        )

        assert file_path is not None

    async def test_upload_custom_user_quota(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Utilise un quota personnalise pour l'utilisateur."""
        small_default_config = QuotaConfig(
            default_quota_bytes=100,
            max_file_size_bytes=10 * 1024 * 1024,
            allowed_mime_types=["text/plain"],
            blocked_extensions=[],
        )
        service = StorageService(backend=local_backend, quota_config=small_default_config)

        # Avec le quota par defaut (100 bytes), ca devrait echouer
        # Mais avec un quota custom de 1MB, ca passe
        file_path = await service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="file.txt",
            content=b"A" * 500,
            mime_type="text/plain",
            user_quota=1024 * 1024,  # 1 MB custom quota
        )

        assert file_path is not None


class TestStorageServiceDownload:
    """Tests pour la methode download()."""

    async def test_download_success(
        self, storage_service: StorageService, test_user_id, test_document_id, sample_text_content
    ):
        """Telecharge un fichier existant."""
        file_path = await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="download_test.txt",
            content=sample_text_content,
            mime_type="text/plain",
        )

        content = await storage_service.download(file_path)

        assert content == sample_text_content

    async def test_download_not_found(self, storage_service: StorageService):
        """Leve une exception si le fichier n'existe pas."""
        with pytest.raises(StorageFileNotFoundError):
            await storage_service.download("nonexistent/path.txt")


class TestStorageServiceDelete:
    """Tests pour la methode delete_document()."""

    async def test_delete_document_success(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Supprime un document et toutes ses versions."""
        # Creer plusieurs versions
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v1",
            mime_type="text/plain",
            version=1,
        )
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v2",
            mime_type="text/plain",
            version=2,
        )

        result = await storage_service.delete_document(test_user_id, test_document_id)

        assert result is True

    async def test_delete_nonexistent_document(self, storage_service: StorageService):
        """Retourne False si le document n'existe pas."""
        result = await storage_service.delete_document(uuid4(), uuid4())
        assert result is False


class TestStorageServiceStats:
    """Tests pour les statistiques."""

    async def test_get_user_stats(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Recupere les statistiques d'un utilisateur."""
        content = b"Test content for stats"
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="stats.txt",
            content=content,
            mime_type="text/plain",
        )

        stats = await storage_service.get_user_stats(test_user_id)

        assert isinstance(stats, UserStorageStats)
        assert stats.user_id == test_user_id
        assert stats.used_bytes == len(content)
        assert stats.file_count == 1
        assert stats.quota_bytes > 0
        assert stats.quota_used_percent > 0

    async def test_get_user_stats_custom_quota(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Calcule le pourcentage avec un quota personnalise."""
        content = b"A" * 1000  # 1000 bytes
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="quota_test.txt",
            content=content,
            mime_type="text/plain",
        )

        # Quota de 10000 bytes = 10% utilise
        stats = await storage_service.get_user_stats(test_user_id, user_quota=10000)

        assert stats.quota_bytes == 10000
        assert stats.quota_used_percent == 10.0

    async def test_get_user_stats_empty(self, storage_service: StorageService):
        """Statistiques pour un utilisateur sans fichiers."""
        stats = await storage_service.get_user_stats(uuid4())

        assert stats.used_bytes == 0
        assert stats.file_count == 0


class TestStorageServiceQuotaCheck:
    """Tests pour la verification de quota."""

    async def test_check_can_upload_true(
        self, storage_service: StorageService, test_user_id
    ):
        """Retourne True si l'upload est possible."""
        can_upload = await storage_service.check_can_upload(
            user_id=test_user_id,
            file_size=1000,
        )
        assert can_upload is True

    async def test_check_can_upload_false(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Retourne False si le quota serait depasse."""
        tiny_quota_config = QuotaConfig(
            default_quota_bytes=500,
            max_file_size_bytes=10 * 1024 * 1024,
            allowed_mime_types=["text/plain"],
            blocked_extensions=[],
        )
        service = StorageService(backend=local_backend, quota_config=tiny_quota_config)

        # Uploader 400 bytes
        await service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="existing.txt",
            content=b"A" * 400,
            mime_type="text/plain",
        )

        # Verifier si on peut uploader 200 bytes de plus (total 600 > 500)
        can_upload = await service.check_can_upload(
            user_id=test_user_id,
            file_size=200,
        )
        assert can_upload is False

    async def test_check_can_upload_with_custom_quota(
        self, storage_service: StorageService, test_user_id
    ):
        """Utilise un quota personnalise pour la verification."""
        # Avec quota par defaut (100 MB), 50 MB OK
        # Avec quota custom de 10 bytes, 50 MB NOK
        can_upload = await storage_service.check_can_upload(
            user_id=test_user_id,
            file_size=50 * 1024 * 1024,
            user_quota=10,
        )
        assert can_upload is False


class TestStorageServiceFileOperations:
    """Tests pour les operations sur fichiers."""

    async def test_get_file_info(
        self, storage_service: StorageService, test_user_id, test_document_id, sample_text_content
    ):
        """Recupere les infos d'un fichier."""
        file_path = await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="info_test.txt",
            content=sample_text_content,
            mime_type="text/plain",
        )

        info = await storage_service.get_file_info(file_path)

        assert info.size == len(sample_text_content)
        assert info.mime_type == "text/plain"
        assert "info_test.txt" in info.filename

    async def test_file_exists(
        self, storage_service: StorageService, test_user_id, test_document_id, sample_text_content
    ):
        """Verifie l'existence d'un fichier."""
        file_path = await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="exists_test.txt",
            content=sample_text_content,
            mime_type="text/plain",
        )

        assert await storage_service.file_exists(file_path) is True
        assert await storage_service.file_exists("nonexistent.txt") is False

    async def test_list_document_versions(
        self, storage_service: StorageService, test_user_id, test_document_id
    ):
        """Liste les versions d'un document."""
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v1",
            mime_type="text/plain",
            version=1,
        )
        await storage_service.upload(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v2",
            mime_type="text/plain",
            version=2,
        )

        versions = await storage_service.list_document_versions(test_user_id, test_document_id)

        assert len(versions) == 2
        assert "v1_" in versions[0]
        assert "v2_" in versions[1]
