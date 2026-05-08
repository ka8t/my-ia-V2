"""
Tests unitaires pour LocalStorageBackend.

Execution: docker-compose exec app python -m pytest tests/storage/test_local_backend.py -v
"""

import pytest
from uuid import uuid4

from app.common.storage.backends.local import LocalStorageBackend
from app.common.storage.exceptions import StorageFileNotFoundError
from app.common.storage.schemas import FileInfo, StorageStats, UserStorageStats


pytestmark = pytest.mark.asyncio


class TestLocalStorageBackendSave:
    """Tests pour la methode save()."""

    async def test_save_file_success(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Sauvegarde un fichier avec succes."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="test.txt",
            content=sample_text_content,
            version=1,
        )

        assert file_path is not None
        assert str(test_user_id) in file_path
        assert str(test_document_id) in file_path
        assert "v1_" in file_path
        assert "test.txt" in file_path

    async def test_save_multiple_versions(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Sauvegarde plusieurs versions d'un document."""
        content_v1 = b"Version 1 content"
        content_v2 = b"Version 2 content updated"

        path_v1 = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=content_v1,
            version=1,
        )

        path_v2 = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=content_v2,
            version=2,
        )

        assert "v1_" in path_v1
        assert "v2_" in path_v2
        assert path_v1 != path_v2

    async def test_save_sanitizes_filename(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Nettoie les caracteres problematiques du nom de fichier."""
        dangerous_filename = "../../etc/passwd"
        content = b"test content"

        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename=dangerous_filename,
            content=content,
            version=1,
        )

        # Le chemin ne doit pas contenir de traversee de repertoire
        assert ".." not in file_path
        # Le chemin doit etre dans le dossier du document, pas dans /etc
        assert str(test_document_id) in file_path


class TestLocalStorageBackendGet:
    """Tests pour la methode get()."""

    async def test_get_file_success(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Recupere un fichier existant."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="test.txt",
            content=sample_text_content,
            version=1,
        )

        retrieved_content = await local_backend.get(file_path)

        assert retrieved_content == sample_text_content

    async def test_get_file_not_found(self, local_backend: LocalStorageBackend):
        """Leve une exception si le fichier n'existe pas."""
        with pytest.raises(StorageFileNotFoundError) as exc_info:
            await local_backend.get("nonexistent/path/file.txt")

        assert "nonexistent/path/file.txt" in str(exc_info.value)


class TestLocalStorageBackendDelete:
    """Tests pour la methode delete()."""

    async def test_delete_file_success(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Supprime un fichier existant."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="to_delete.txt",
            content=sample_text_content,
            version=1,
        )

        result = await local_backend.delete(file_path)

        assert result is True
        assert await local_backend.exists(file_path) is False

    async def test_delete_nonexistent_file(self, local_backend: LocalStorageBackend):
        """Retourne False si le fichier n'existe pas."""
        result = await local_backend.delete("nonexistent/file.txt")
        assert result is False

    async def test_delete_document_folder(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Supprime le dossier complet d'un document."""
        # Creer plusieurs versions
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v1",
            version=1,
        )
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v2",
            version=2,
        )

        result = await local_backend.delete_document_folder(test_user_id, test_document_id)

        assert result is True
        versions = await local_backend.list_document_versions(test_user_id, test_document_id)
        assert len(versions) == 0


class TestLocalStorageBackendExists:
    """Tests pour la methode exists()."""

    async def test_exists_true(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Retourne True si le fichier existe."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="exists.txt",
            content=sample_text_content,
            version=1,
        )

        assert await local_backend.exists(file_path) is True

    async def test_exists_false(self, local_backend: LocalStorageBackend):
        """Retourne False si le fichier n'existe pas."""
        assert await local_backend.exists("nonexistent.txt") is False


class TestLocalStorageBackendFileInfo:
    """Tests pour la methode get_file_info()."""

    async def test_get_file_info_success(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Recupere les metadonnees d'un fichier."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="info.txt",
            content=sample_text_content,
            version=1,
        )

        info = await local_backend.get_file_info(file_path)

        assert isinstance(info, FileInfo)
        assert info.path == file_path
        assert info.size == len(sample_text_content)
        assert info.mime_type == "text/plain"
        assert "info.txt" in info.filename

    async def test_get_file_info_not_found(self, local_backend: LocalStorageBackend):
        """Leve une exception si le fichier n'existe pas."""
        with pytest.raises(StorageFileNotFoundError):
            await local_backend.get_file_info("nonexistent.txt")


class TestLocalStorageBackendListFiles:
    """Tests pour les methodes de listing."""

    async def test_list_user_files(
        self, local_backend: LocalStorageBackend, test_user_id
    ):
        """Liste tous les fichiers d'un utilisateur."""
        doc1_id = uuid4()
        doc2_id = uuid4()

        await local_backend.save(
            user_id=test_user_id,
            document_id=doc1_id,
            filename="doc1.txt",
            content=b"content1",
            version=1,
        )
        await local_backend.save(
            user_id=test_user_id,
            document_id=doc2_id,
            filename="doc2.txt",
            content=b"content2",
            version=1,
        )

        files = await local_backend.list_user_files(test_user_id)

        assert len(files) == 2

    async def test_list_user_files_empty(self, local_backend: LocalStorageBackend):
        """Retourne une liste vide pour un utilisateur sans fichiers."""
        files = await local_backend.list_user_files(uuid4())
        assert files == []

    async def test_list_document_versions(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Liste toutes les versions d'un document."""
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v1",
            version=1,
        )
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v2",
            version=2,
        )
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"v3",
            version=3,
        )

        versions = await local_backend.list_document_versions(test_user_id, test_document_id)

        assert len(versions) == 3
        # Verifier l'ordre (trie par version)
        assert "v1_" in versions[0]
        assert "v2_" in versions[1]
        assert "v3_" in versions[2]


class TestLocalStorageBackendStats:
    """Tests pour les statistiques."""

    async def test_get_storage_stats(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Recupere les statistiques globales."""
        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=b"content",
            version=1,
        )

        stats = await local_backend.get_storage_stats()

        assert isinstance(stats, StorageStats)
        assert stats.total_bytes > 0
        assert stats.file_count >= 1
        assert stats.user_count >= 1

    async def test_get_user_stats(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Recupere les statistiques d'un utilisateur."""
        content = b"test content for stats"

        await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="doc.txt",
            content=content,
            version=1,
        )

        stats = await local_backend.get_user_stats(test_user_id)

        assert isinstance(stats, UserStorageStats)
        assert stats.user_id == test_user_id
        assert stats.used_bytes == len(content)
        assert stats.file_count == 1

    async def test_get_user_stats_empty(self, local_backend: LocalStorageBackend):
        """Statistiques pour un utilisateur sans fichiers."""
        stats = await local_backend.get_user_stats(uuid4())

        assert stats.used_bytes == 0
        assert stats.file_count == 0


class TestLocalStorageBackendDownload:
    """Tests pour le telechargement."""

    async def test_get_download_path(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id, sample_text_content
    ):
        """Retourne le chemin absolu pour telechargement."""
        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="download.txt",
            content=sample_text_content,
            version=1,
        )

        download_path = await local_backend.get_download_path(file_path)

        assert download_path.startswith("/")  # Chemin absolu
        assert "download.txt" in download_path

    async def test_stream_file(
        self, local_backend: LocalStorageBackend, test_user_id, test_document_id
    ):
        """Stream un fichier par chunks."""
        content = b"A" * 1000  # 1000 bytes

        file_path = await local_backend.save(
            user_id=test_user_id,
            document_id=test_document_id,
            filename="stream.txt",
            content=content,
            version=1,
        )

        chunks = []
        async for chunk in local_backend.stream_file(file_path, chunk_size=100):
            chunks.append(chunk)

        # Verifier que le contenu est complet
        assert b"".join(chunks) == content
        # Verifier le nombre de chunks (1000 / 100 = 10)
        assert len(chunks) == 10
