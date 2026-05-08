"""Tests d'intégration — UX statut indexation user (P0.3).

Couvre :
  - _doc_status() distingue 'pending' / 'error' via ReindexManager
  - Le partial row.html arrête le polling sur erreur (pas de hx-trigger)
  - Le partial affiche un bouton "Réessayer" sur erreur
  - POST /web/documents/{id}/reindex relance l'indexation (owner only)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.common.utils.reindex import (
    clear_doc_reindex_progress,
    set_doc_reindex_progress,
)
from app.db import async_session_maker
from app.models import Collection, Corpus, Document, User
from tests.conftest import extract_csrf, fresh_slug

pytestmark = pytest.mark.asyncio

USER_EMAIL = "user@test.example"
USER_PASSWORD = "5#d%o3x3^7%uOwrZw_UIRS60"


@dataclass
class DocSnapshot:
    id: uuid.UUID
    filename: str


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def user_client(client: AsyncClient) -> AsyncClient:
    """Logged-in user httpx client (user@test.example)."""
    r = await client.get("/web/login")
    csrf = extract_csrf(r.text)
    r = await client.post(
        "/web/login",
        data={"email": USER_EMAIL, "password": USER_PASSWORD, "csrf_token": csrf},
    )
    assert r.status_code in (302, 303), f"login user failed: {r.status_code}"
    return client


@pytest_asyncio.fixture
async def user_csrf(user_client: AsyncClient) -> str:
    r = await user_client.get("/web/documents")
    assert r.status_code == 200
    return extract_csrf(r.text)


@pytest_asyncio.fixture
async def pending_document() -> AsyncGenerator[DocSnapshot, None]:
    """Crée un Document chunk_count=0 (donc statut pending) en BDD pour le
    user de test, le yield, puis le supprime."""
    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.email == USER_EMAIL))).unique().scalar_one()
        # Trouver / créer le corpus perso
        corp = (
            await s.execute(select(Corpus).where(Corpus.name == f"user_{u.id}"))
        ).unique().scalar_one_or_none()
        if corp is None:
            corp = Corpus(
                name=f"user_{u.id}",
                display_name="Personnel",
                description="pytest",
            )
            s.add(corp)
            await s.flush()
        # Trouver / créer collection privée user
        col = (
            await s.execute(
                select(Collection).where(Collection.owner_id == u.id, Collection.type == "private")
            )
        ).unique().scalar_one_or_none()
        if col is None:
            col = Collection(
                name=f"user_{u.id}",
                display_name="Personnel",
                type="private",
                owner_id=u.id,
            )
            s.add(col)
            await s.flush()
        slug = fresh_slug()
        doc = Document(
            user_id=u.id,
            collection_id=col.id,
            filename=f"{slug}.txt",
            file_hash=f"hash-{slug}",
            file_size=42,
            file_type="text/plain",
            chunk_count=0,
            embedding_count=0,
            is_indexed=False,
            visibility="private",
            current_version=1,
        )
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        snap = DocSnapshot(id=doc.id, filename=doc.filename)
    yield snap
    async with async_session_maker() as s:
        await s.execute(delete(Document).where(Document.id == snap.id))
        await s.commit()
    clear_doc_reindex_progress(str(snap.id))


# ─────────────────────────────────────────────────────────────────────────────
#  GET /row — affichage statut
# ─────────────────────────────────────────────────────────────────────────────
async def test_row_shows_pending_when_no_progress_state(
    user_client: AsyncClient, pending_document: DocSnapshot
) -> None:
    """Sans état in-memory, le row reste sur 'Indexation…' avec polling."""
    clear_doc_reindex_progress(str(pending_document.id))
    r = await user_client.get(f"/web/documents/{pending_document.id}/row")
    assert r.status_code == 200
    assert "docs-status--pending" in r.text
    # Polling actif
    assert 'hx-trigger="every 4s"' in r.text
    # Pas de bouton "Réessayer"
    assert "docs-row__action--retry" not in r.text


async def test_row_shows_error_when_reindex_failed(
    user_client: AsyncClient, pending_document: DocSnapshot
) -> None:
    """Si ReindexManager indique status=failed, row affiche 'Erreur' et
    arrête le polling."""
    set_doc_reindex_progress(
        str(pending_document.id),
        0,
        "failed",
        status="failed",
        error_message="partition_xlsx() not available",
        document_name=pending_document.filename,
    )
    r = await user_client.get(f"/web/documents/{pending_document.id}/row")
    assert r.status_code == 200
    assert "docs-status--error" in r.text
    # L'apostrophe est encodée HTML par Jinja (autoescape) → utiliser variantes
    assert "Erreur d&#39;indexation" in r.text or "Erreur d'indexation" in r.text
    # Polling stoppé (pas de hx-trigger every Xs)
    assert 'hx-trigger="every' not in r.text
    # Bouton "Réessayer" affiché
    assert "docs-row__action--retry" in r.text


async def test_row_truncates_long_error_message(
    user_client: AsyncClient, pending_document: DocSnapshot
) -> None:
    long = "X" * 200
    set_doc_reindex_progress(
        str(pending_document.id),
        0,
        "error",
        status="failed",
        error_message=long,
    )
    r = await user_client.get(f"/web/documents/{pending_document.id}/row")
    assert r.status_code == 200
    # Tronqué à ~120 chars + ellipsis
    assert "XXXXXXX…" in r.text
    # Pas la chaîne complète (200 X's)
    assert long not in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  POST /reindex — bouton Réessayer
# ─────────────────────────────────────────────────────────────────────────────
async def test_reindex_anon_redirects_to_login(client: AsyncClient) -> None:
    r = await client.post(f"/web/documents/{uuid.uuid4()}/reindex", data={"csrf_token": "x"})
    assert r.status_code == 303


async def test_reindex_csrf_missing_returns_400(
    user_client: AsyncClient, pending_document: DocSnapshot
) -> None:
    r = await user_client.post(f"/web/documents/{pending_document.id}/reindex", data={})
    assert r.status_code == 400


async def test_reindex_unknown_doc_returns_404(
    user_client: AsyncClient, user_csrf: str
) -> None:
    r = await user_client.post(
        f"/web/documents/{uuid.uuid4()}/reindex",
        data={"csrf_token": user_csrf},
    )
    assert r.status_code == 404


async def test_reindex_doc_without_file_path_returns_400(
    user_client: AsyncClient, user_csrf: str, pending_document: DocSnapshot
) -> None:
    """Doc créé en BDD sans file_path (cas notre fixture) → 400 'fichier source absent'."""
    r = await user_client.post(
        f"/web/documents/{pending_document.id}/reindex",
        data={"csrf_token": user_csrf},
    )
    assert r.status_code == 400
    assert "Fichier source absent" in r.text


async def test_reindex_other_users_doc_returns_404(
    user_client: AsyncClient, user_csrf: str
) -> None:
    """Owner check : un user ne peut pas reindex le doc d'un autre user."""
    # Créer un doc appartenant à admin (pas l'user du client)
    async with async_session_maker() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@test.example"))
        ).unique().scalar_one()
        slug = fresh_slug()
        doc = Document(
            user_id=admin.id,
            filename=f"{slug}.txt",
            file_hash=f"hash-{slug}",
            file_size=10,
            file_type="text/plain",
            chunk_count=0,
            embedding_count=0,
            is_indexed=False,
            visibility="private",
            current_version=1,
        )
        s.add(doc)
        await s.commit()
        doc_id = doc.id

    try:
        r = await user_client.post(
            f"/web/documents/{doc_id}/reindex",
            data={"csrf_token": user_csrf},
        )
        # Doit retourner 404 (filtre user_id == current user → pas trouvé)
        assert r.status_code == 404
    finally:
        async with async_session_maker() as s:
            await s.execute(delete(Document).where(Document.id == doc_id))
            await s.commit()
