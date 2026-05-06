"""Tests d'intégration — Pages admin Système RAG (Phase 3.8.a, C3)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import SystemConfig
from app.web.admin_system import (
    RAG_BEHAVIOR_KEYS,
    RAG_CHUNKING_KEYS,
    RAG_OVERRIDES_KEYS,
    RAG_SEARCH_KEYS,
)

pytestmark = pytest.mark.asyncio

ALL_KEYS = RAG_CHUNKING_KEYS + RAG_SEARCH_KEYS + RAG_BEHAVIOR_KEYS + RAG_OVERRIDES_KEYS


@pytest.fixture(autouse=True)
async def _snapshot_rag_keys():
    async with async_session_maker() as s:
        rows = (
            await s.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_KEYS)))
        ).scalars().all()
        snapshot = {r.key: (r.value, r.value_type) for r in rows}
    yield
    async with async_session_maker() as s:
        rows = (
            await s.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_KEYS)))
        ).scalars().all()
        for r in rows:
            if r.key in snapshot:
                r.value, r.value_type = snapshot[r.key]
            else:
                await s.delete(r)
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_chunking_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/rag/chunking")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  RAG · Chunking
# ─────────────────────────────────────────────────────────────────────────────
async def test_chunking_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/rag/chunking")
    assert r.status_code == 200
    assert "rag.chunk_size" in r.text
    assert "Récursif" in r.text


async def test_chunking_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/chunking",
        data={
            "chunk_size": "1024",
            "chunk_overlap": "128",
            "chunking_strategy": "fixed",
            "min_chunk_length": "32",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("rag.chunk_size") == 1024
        assert await svc.get("rag.chunking_strategy") == "fixed"
        assert await svc.get("rag.min_chunk_length") == 32


async def test_chunking_invalid_strategy_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/chunking",
        data={
            "chunk_size": "800", "chunk_overlap": "100",
            "chunking_strategy": "evil", "min_chunk_length": "50",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "invalide" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  RAG · Search
# ─────────────────────────────────────────────────────────────────────────────
async def test_search_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/rag/search")
    assert r.status_code == 200
    assert "Top K" in r.text
    assert "similarity_threshold" in r.text


async def test_search_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/search",
        data={
            "top_k": "20",
            "similarity_threshold": "0.65",
            "keyword_boost": "0.3",
            "stopwords_language": "fr",
            "temperature": "0.5",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("rag.top_k") == 20
        assert await svc.get("rag.similarity_threshold") == 0.65
        assert await svc.get("rag.temperature") == 0.5


async def test_search_top_k_clamped(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/search",
        data={
            "top_k": "999",
            "similarity_threshold": "0.0",
            "keyword_boost": "0",
            "stopwords_language": "fr",
            "temperature": "0.7",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("rag.top_k") == 200


async def test_search_threshold_out_of_range_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/search",
        data={
            "top_k": "10",
            "similarity_threshold": "2.5",
            "keyword_boost": "0",
            "stopwords_language": "fr",
            "temperature": "0.7",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "similarity_threshold" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  RAG · Behavior
# ─────────────────────────────────────────────────────────────────────────────
async def test_behavior_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/rag/behavior")
    assert r.status_code == 200
    assert "rag.use_corpus" in r.text


async def test_behavior_post_unchecked_means_false(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/behavior",
        data={
            "default_group": "general",
            # use_corpus, include_global_sources, source_filter_by_collection : non envoyés
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("rag.use_corpus") is False
        assert await svc.get("rag.include_global_sources") is False
        assert await svc.get("rag.source_filter_by_collection") is False
        assert await svc.get("rag.default_group") == "general"


async def test_behavior_post_checked_means_true(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/behavior",
        data={
            "use_corpus": "true",
            "include_global_sources": "true",
            "source_filter_by_collection": "true",
            "default_group": "internal",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("rag.use_corpus") is True


# ─────────────────────────────────────────────────────────────────────────────
#  RAG · Overrides
# ─────────────────────────────────────────────────────────────────────────────
async def test_overrides_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/rag/overrides")
    assert r.status_code == 200
    assert "rag.ollama.top_k" in r.text
    assert "rag.llamacpp.temperature" in r.text
    assert "rag.mode.fast.top_k" in r.text
    assert "rag.mode.full.rerank_enabled" in r.text


async def test_overrides_post_saves_subset(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Le formulaire envoie seulement quelques clés, le reste n'est pas modifié."""
    r = await admin_client.post(
        "/web/admin/system/rag/overrides",
        data={
            "rag.ollama.top_k": "5",
            "rag.ollama.temperature": "0.3",
            "rag.mode.fast.max_context_tokens": "4096",
            "rag.mode.fast.rerank_enabled": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("rag.ollama.top_k") == 5
        assert await svc.get("rag.ollama.temperature") == 0.3
        assert await svc.get("rag.mode.fast.max_context_tokens") == 4096
        assert await svc.get("rag.mode.fast.rerank_enabled") is True


async def test_overrides_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/rag/overrides",
        data={"rag.ollama.top_k": "10", "csrf_token": "wrong"},
    )
    assert r.status_code == 400
