"""Tests d'intégration — Reindex / Clear / Cancel + polling (Vague 2.4)."""
from __future__ import annotations

import uuid as _uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.common.utils.reindex import ReindexManager
from app.db import async_session_maker
from app.models import Corpus
from tests.conftest import fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _create_corpus() -> Corpus:
    name = f"Pytest Corpus {fresh_slug()}"
    async with async_session_maker() as s:
        c = Corpus(name=fresh_slug(), display_name=name, is_active=True)
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c


@pytest.fixture(autouse=True)
def _isolate_reindex_manager():
    """Snapshots l'état du ReindexManager (in-memory) et le restaure post-test."""
    snap_progress = ReindexManager._progress.copy()
    snap_cancel = ReindexManager._cancel_flags.copy()
    snap_corpus = {k: v.copy() for k, v in ReindexManager._corpus_items.items()}
    yield
    ReindexManager._progress.clear()
    ReindexManager._progress.update(snap_progress)
    ReindexManager._cancel_flags.clear()
    ReindexManager._cancel_flags.update(snap_cancel)
    ReindexManager._corpus_items.clear()
    ReindexManager._corpus_items.update(snap_corpus)


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_status_redirected(client: AsyncClient) -> None:
    r = await client.get(f"/web/admin/corpus/{_uuid.uuid4()}/reindex/status")
    assert r.status_code == 303


async def test_anon_reindex_redirected(client: AsyncClient) -> None:
    r = await client.post(f"/web/admin/corpus/{_uuid.uuid4()}/reindex")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  Status — état idle quand corpus existe mais pas de reindex
# ─────────────────────────────────────────────────────────────────────────────
async def test_status_idle_when_no_progress(admin_client: AsyncClient) -> None:
    corpus = await _create_corpus()
    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/reindex/status")
    assert r.status_code == 200
    assert 'id="reindex-progress"' in r.text
    assert 'idle' in r.text
    # Pas de hx-trigger → polling stoppé
    assert 'hx-trigger="every 2s"' not in r.text


async def test_status_unknown_corpus_returns_404(admin_client: AsyncClient) -> None:
    r = await admin_client.get(f"/web/admin/corpus/{_uuid.uuid4()}/reindex/status")
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Status — running fait apparaître hx-trigger pour auto-refresh
# ─────────────────────────────────────────────────────────────────────────────
async def test_status_running_enables_polling(admin_client: AsyncClient) -> None:
    corpus = await _create_corpus()
    # Simuler 1 doc en cours pour ce corpus dans le ReindexManager
    fake_doc_uuid = str(_uuid.uuid4())
    ReindexManager.set_doc_progress(
        fake_doc_uuid,
        progress=42,
        message="indexing chunks",
        status="running",
        corpus_id=str(corpus.id),
    )

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/reindex/status")
    assert r.status_code == 200
    assert 'running' in r.text
    assert 'hx-trigger="every 2s"' in r.text
    # Le bouton "Annuler la réindexation" doit apparaître
    assert 'Annuler la réindexation' in r.text


async def test_status_completed_stops_polling(admin_client: AsyncClient) -> None:
    corpus = await _create_corpus()
    fake_doc_uuid = str(_uuid.uuid4())
    ReindexManager.set_doc_progress(
        fake_doc_uuid,
        progress=100,
        message="done",
        status="completed",
        corpus_id=str(corpus.id),
    )

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/reindex/status")
    assert r.status_code == 200
    assert 'completed' in r.text
    assert 'hx-trigger="every 2s"' not in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  POST reindex — corpus vide retourne idle (rien à faire)
# ─────────────────────────────────────────────────────────────────────────────
async def test_reindex_empty_corpus_returns_flash(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/reindex",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Aucun élément rattaché" in r.text
    assert 'hx-trigger="every 2s"' not in r.text


async def test_reindex_unknown_corpus_returns_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        f"/web/admin/corpus/{_uuid.uuid4()}/reindex",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 404


async def test_reindex_invalid_csrf(admin_client: AsyncClient) -> None:
    corpus = await _create_corpus()
    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/reindex",
        data={"csrf_token": "wrong"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  POST cancel — sans rien en cours
# ─────────────────────────────────────────────────────────────────────────────
async def test_cancel_no_running_shows_flash(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/reindex/cancel",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Aucune réindexation en cours" in r.text


async def test_cancel_running_requests_cancel(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    fake_doc_uuid = str(_uuid.uuid4())
    ReindexManager.set_doc_progress(
        fake_doc_uuid,
        progress=33,
        message="encoding",
        status="running",
        corpus_id=str(corpus.id),
    )

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/reindex/cancel",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Annulation demandée" in r.text
    # Le flag de cancel doit être posé sur le doc
    assert ReindexManager.is_doc_cancel_requested(fake_doc_uuid) is True


# ─────────────────────────────────────────────────────────────────────────────
#  POST clear-index — corpus vide → succès no-op
# ─────────────────────────────────────────────────────────────────────────────
async def test_clear_empty_corpus_ok(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/clear-index",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Index vidé" in r.text
    assert "0 document(s)" in r.text


async def test_clear_unknown_corpus_returns_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        f"/web/admin/corpus/{_uuid.uuid4()}/clear-index",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 404
