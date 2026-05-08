"""Tests de régression — bugs observés en QA et fixés (P0.4).

Chaque test cible un bug constaté en prod ou local pendant la session de
QA, pour empêcher sa réapparition. Référence : PLAN-PARITE-CORRECTIONS.html
P0.4.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_maker
from app.models import AppLog, Document, User
from tests.conftest import fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Bug A — VARCHAR(50) trop court pour mime types Office (xlsx/docx/pptx)
#  Migration : 20260507_1700_extend_document_file_type (50 → 150).
# ─────────────────────────────────────────────────────────────────────────────
async def test_document_file_type_accepts_long_office_mime() -> None:
    """Régression : insert d'un Document avec mime xlsx (71 chars) ne plante
    plus avec StringDataRightTruncationError."""
    XLSX_MIME = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(XLSX_MIME) > 50, "le test n'est utile que si le mime > 50 chars"

    slug = fresh_slug()
    async with async_session_maker() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@test.example"))
        ).unique().scalar_one()
        doc = Document(
            user_id=admin.id,
            filename=f"{slug}.xlsx",
            file_hash=f"hash-{slug}",
            file_size=1234,
            file_type=XLSX_MIME,
            chunk_count=0,
            embedding_count=0,
            is_indexed=False,
            visibility="private",
            current_version=1,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        assert doc.file_type == XLSX_MIME

    # Cleanup
    async with async_session_maker() as s:
        await s.execute(delete(Document).where(Document.filename == f"{slug}.xlsx"))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Bug B — LocalStorageBackend.save() : UnboundLocalError sur file_path
#  quand mkdir échoue (PermissionError). Le fix initialise file_path avant
#  le try.
# ─────────────────────────────────────────────────────────────────────────────
async def test_local_storage_save_permission_error_no_unbound_local(
    tmp_path,
) -> None:
    """Régression : si mkdir échoue, l'except handler doit avoir accès à
    file_path (sinon UnboundLocalError au lieu de StoragePermissionError)."""
    from app.common.storage.backends.local import LocalStorageBackend
    from app.common.storage.exceptions import (
        StoragePermissionError,
        StorageIOError,
    )

    # Préparer un base_path en lecture seule (chmod 0o500)
    base = tmp_path / "ro-storage"
    base.mkdir()
    base.chmod(0o500)  # r-x sans w → mkdir parents échouera dans save

    backend = LocalStorageBackend(base_path=str(base))
    user_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    try:
        # On s'attend à une StoragePermissionError ou StorageIOError, PAS à
        # UnboundLocalError.
        with pytest.raises((StoragePermissionError, StorageIOError, OSError)):
            await backend.save(
                user_id=user_id,
                document_id=doc_id,
                filename="test.txt",
                content=b"hello",
            )
    finally:
        base.chmod(0o700)


# ─────────────────────────────────────────────────────────────────────────────
#  Bug D — GET /api/admin/logs/stats : 500 'list object has no attribute items'
#  Cause : LogStatsResponse retourne by_level: List[LogLevelStats] et le code
#  tentait .items() dessus comme si c'était un dict.
# ─────────────────────────────────────────────────────────────────────────────
async def test_admin_logs_stats_endpoint_returns_200(
    admin_client: AsyncClient,
) -> None:
    """Régression : la route /admin/logs/stats web doit renvoyer 200 et un
    HTML valide avec les compteurs Total / Alertes / by_level / by_category."""
    r = await admin_client.get("/web/admin/logs/stats")
    assert r.status_code == 200, r.text[:300]
    body = r.text
    # Le partial doit contenir au moins les compteurs principaux
    assert "Total" in body or "total" in body
    # Pas de message d'erreur Python brut
    assert "object has no attribute 'items'" not in body
    assert "AttributeError" not in body


# ─────────────────────────────────────────────────────────────────────────────
#  Bug E — GET /api/admin/logs/{id}/details : 500 'AppLog has no attribute
#  created_at'. Cause : le modèle utilise `timestamp`, pas `created_at`.
# ─────────────────────────────────────────────────────────────────────────────
async def test_admin_logs_details_endpoint_returns_200(
    admin_client: AsyncClient,
) -> None:
    """Régression : la route /admin/logs/{id}/details doit renvoyer 200
    sur un log valide, sans AttributeError sur created_at."""
    # Créer un log de test
    slug = fresh_slug()
    async with async_session_maker() as s:
        log = AppLog(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            log_category="technical",
            service="test",
            environment="test",
            message=f"regression test {slug}",
            logger_name="test.regression",
        )
        s.add(log)
        await s.commit()
        log_id = log.id

    try:
        r = await admin_client.get(f"/web/admin/logs/{log_id}/details")
        assert r.status_code == 200, r.text[:300]
        body = r.text
        assert "created_at" not in body or "AttributeError" not in body
        # Pas de stack trace AttributeError visible
        assert "object has no attribute" not in body
    finally:
        async with async_session_maker() as s:
            await s.execute(delete(AppLog).where(AppLog.id == log_id))
            await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Bug C — partition_xlsx() not available (couvert par P0.2 dans
#  test_ingestion_formats.py) — pas de re-test ici pour éviter la
#  duplication.
# ─────────────────────────────────────────────────────────────────────────────
