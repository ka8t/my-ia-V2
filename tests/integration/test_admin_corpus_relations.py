"""Tests d'intégration — Admin Corpus relations (Vagues 2.1+2.2+2.3).

Couvre :
- /web/admin/corpus/{id}/documents/picker, attach, detach
- /web/admin/corpus/{id}/sources/picker, attach, update, detach
- /web/admin/corpus/{id}/collections/picker, attach, update, detach
"""
from __future__ import annotations

import hashlib
import uuid as _uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import (
    Collection,
    ContextSource,
    Corpus,
    CorpusCollection,
    CorpusDocument,
    CorpusSource,
    Document,
    User,
)
from tests.conftest import ADMIN_EMAIL, fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Factories : créent et persistent des objets de test (cleanup auto via préfixe)
# ─────────────────────────────────────────────────────────────────────────────
async def _create_corpus(name: str | None = None) -> Corpus:
    name = name or f"Pytest Corpus {fresh_slug()}"
    async with async_session_maker() as s:
        c = Corpus(name=fresh_slug(), display_name=name, is_active=True)
        s.add(c)
        await s.commit()
        await s.refresh(c)
        return c


async def _create_document(filename_prefix: str = "doc") -> Document:
    """Crée un Document minimal attaché à l'admin de test."""
    async with async_session_maker() as s:
        admin = (
            await s.execute(select(User).where(User.email == ADMIN_EMAIL))
        ).unique().scalar_one()
        slug = fresh_slug()
        filename = f"{slug}-{filename_prefix}.txt"
        d = Document(
            user_id=admin.id,
            filename=filename,
            file_hash=hashlib.sha256(filename.encode()).hexdigest(),
            file_size=128,
            file_type="text/plain",
            chunk_count=0,
        )
        s.add(d)
        await s.commit()
        await s.refresh(d)
        return d


async def _create_source(name: str | None = None, source_type: str = "web") -> ContextSource:
    async with async_session_maker() as s:
        slug = fresh_slug()
        src = ContextSource(
            name=slug,
            display_name=name or f"Pytest Source {slug}",
            source_type=source_type,
            config={},
            is_enabled=False,
        )
        s.add(src)
        await s.commit()
        await s.refresh(src)
        return src


async def _create_collection(coll_type: str = "public", name: str | None = None) -> Collection:
    async with async_session_maker() as s:
        slug = fresh_slug()
        col = Collection(
            name=slug,
            display_name=name or f"Pytest Collection {slug}",
            type=coll_type,
            space="cosine",
        )
        s.add(col)
        await s.commit()
        await s.refresh(col)
        return col


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.1 — Documents
# ═════════════════════════════════════════════════════════════════════════════
async def test_doc_picker_lists_unattached(
    admin_client: AsyncClient,
) -> None:
    corpus = await _create_corpus()
    doc = await _create_document()

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/documents/picker")
    assert r.status_code == 200
    assert doc.filename in r.text


async def test_doc_picker_excludes_already_attached(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    doc = await _create_document()

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(doc.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 200, r.text

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/documents/picker")
    assert r.status_code == 200
    assert doc.filename not in r.text


async def test_doc_attach_returns_row(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    doc = await _create_document()

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(doc.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert f'id="corpus-doc-{doc.id}"' in r.text
    assert doc.filename in r.text

    async with async_session_maker() as s:
        cd = (
            await s.execute(
                select(CorpusDocument).where(
                    CorpusDocument.corpus_id == corpus.id,
                    CorpusDocument.document_id == doc.id,
                )
            )
        ).scalar_one_or_none()
        assert cd is not None


async def test_doc_attach_duplicate_returns_409(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    doc = await _create_document()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(doc.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(doc.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 409


async def test_doc_attach_unknown_doc_returns_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(_uuid.uuid4()), "csrf_token": admin_csrf},
    )
    assert r.status_code == 404


async def test_doc_detach_ok(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    doc = await _create_document()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/documents",
        data={"document_id": str(doc.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.delete(
        f"/web/admin/corpus/{corpus.id}/documents/{doc.id}"
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        cd = (
            await s.execute(
                select(CorpusDocument).where(
                    CorpusDocument.corpus_id == corpus.id,
                    CorpusDocument.document_id == doc.id,
                )
            )
        ).scalar_one_or_none()
        assert cd is None


async def test_doc_detach_unknown_returns_404(
    admin_client: AsyncClient,
) -> None:
    corpus = await _create_corpus()
    r = await admin_client.delete(
        f"/web/admin/corpus/{corpus.id}/documents/{_uuid.uuid4()}"
    )
    assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.2 — Sources
# ═════════════════════════════════════════════════════════════════════════════
async def test_source_picker_lists_unattached(
    admin_client: AsyncClient,
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/sources/picker")
    assert r.status_code == 200
    assert src.display_name in r.text


async def test_source_attach_with_priority_and_enabled(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={
            "source_id": str(src.id),
            "priority": "42",
            "is_enabled": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert f'id="corpus-src-{src.id}"' in r.text

    async with async_session_maker() as s:
        cs = (
            await s.execute(
                select(CorpusSource).where(
                    CorpusSource.corpus_id == corpus.id,
                    CorpusSource.source_id == src.id,
                )
            )
        ).scalar_one()
        assert cs.priority == 42
        assert cs.is_enabled is True


async def test_source_attach_duplicate_returns_409(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={"source_id": str(src.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={"source_id": str(src.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 409


async def test_source_update_priority_and_toggle(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={"source_id": str(src.id), "csrf_token": admin_csrf, "is_enabled": "true"},
    )

    r = await admin_client.patch(
        f"/web/admin/corpus/{corpus.id}/sources/{src.id}",
        data={"priority": "5", "csrf_token": admin_csrf},  # is_enabled non envoyé → False
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        cs = (
            await s.execute(
                select(CorpusSource).where(
                    CorpusSource.corpus_id == corpus.id,
                    CorpusSource.source_id == src.id,
                )
            )
        ).scalar_one()
        assert cs.priority == 5
        assert cs.is_enabled is False


async def test_source_update_priority_clamped(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={"source_id": str(src.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.patch(
        f"/web/admin/corpus/{corpus.id}/sources/{src.id}",
        data={"priority": "9999", "csrf_token": admin_csrf, "is_enabled": "true"},
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        cs = (
            await s.execute(
                select(CorpusSource).where(
                    CorpusSource.corpus_id == corpus.id,
                    CorpusSource.source_id == src.id,
                )
            )
        ).scalar_one()
        assert cs.priority == 1000


async def test_source_detach_ok(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    src = await _create_source()
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/sources",
        data={"source_id": str(src.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.delete(f"/web/admin/corpus/{corpus.id}/sources/{src.id}")
    assert r.status_code == 200

    async with async_session_maker() as s:
        cs = (
            await s.execute(
                select(CorpusSource).where(
                    CorpusSource.corpus_id == corpus.id,
                    CorpusSource.source_id == src.id,
                )
            )
        ).scalar_one_or_none()
        assert cs is None


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.3 — Collections (publiques uniquement)
# ═════════════════════════════════════════════════════════════════════════════
async def test_collection_picker_only_public(
    admin_client: AsyncClient,
) -> None:
    corpus = await _create_corpus()
    pub = await _create_collection(coll_type="public")
    priv = await _create_collection(coll_type="private")

    r = await admin_client.get(f"/web/admin/corpus/{corpus.id}/collections/picker")
    assert r.status_code == 200
    assert pub.display_name in r.text
    assert priv.display_name not in r.text


async def test_collection_attach_public_ok(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    coll = await _create_collection(coll_type="public")

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(coll.id), "priority": "10", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert f'id="corpus-col-{coll.id}"' in r.text

    async with async_session_maker() as s:
        cc = (
            await s.execute(
                select(CorpusCollection).where(
                    CorpusCollection.corpus_id == corpus.id,
                    CorpusCollection.collection_id == coll.id,
                )
            )
        ).scalar_one()
        assert cc.priority == 10


async def test_collection_attach_private_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    priv = await _create_collection(coll_type="private")

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(priv.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 400


async def test_collection_attach_duplicate_returns_409(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    coll = await _create_collection(coll_type="public")
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(coll.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(coll.id), "csrf_token": admin_csrf},
    )
    assert r.status_code == 409


async def test_collection_update_priority(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    coll = await _create_collection(coll_type="public")
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(coll.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.patch(
        f"/web/admin/corpus/{corpus.id}/collections/{coll.id}",
        data={"priority": "7", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        cc = (
            await s.execute(
                select(CorpusCollection).where(
                    CorpusCollection.corpus_id == corpus.id,
                    CorpusCollection.collection_id == coll.id,
                )
            )
        ).scalar_one()
        assert cc.priority == 7


async def test_collection_detach_ok(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    corpus = await _create_corpus()
    coll = await _create_collection(coll_type="public")
    await admin_client.post(
        f"/web/admin/corpus/{corpus.id}/collections",
        data={"collection_id": str(coll.id), "csrf_token": admin_csrf},
    )

    r = await admin_client.delete(
        f"/web/admin/corpus/{corpus.id}/collections/{coll.id}"
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        cc = (
            await s.execute(
                select(CorpusCollection).where(
                    CorpusCollection.corpus_id == corpus.id,
                    CorpusCollection.collection_id == coll.id,
                )
            )
        ).scalar_one_or_none()
        assert cc is None
