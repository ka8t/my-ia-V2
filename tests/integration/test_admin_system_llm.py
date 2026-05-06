"""Tests d'intégration — Pages admin Système LLM (Phase 3.8.a, C2).

Couvre :
- /web/admin/system/llm/provider (GET + POST)
- /web/admin/system/llm/ollama   (GET + POST)
- /web/admin/system/llm/llamacpp (GET + POST)

Stratégie cleanup : capture l'état initial des clés touchées, restaure en
teardown. Les valeurs ne sont pas préfixées (clés fixes), donc on snapshot.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import SystemConfig
from app.web.admin_system import LLM_LLAMACPP_KEYS, LLM_OLLAMA_KEYS, LLM_PROVIDER_KEYS

pytestmark = pytest.mark.asyncio

ALL_KEYS = LLM_PROVIDER_KEYS + LLM_OLLAMA_KEYS + LLM_LLAMACPP_KEYS


# ─────────────────────────────────────────────────────────────────────────────
#  Fixture autouse — snapshot/restore des clés touchées
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
async def _snapshot_llm_keys():
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
async def test_anon_provider_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/llm/provider")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  Page Provider
# ─────────────────────────────────────────────────────────────────────────────
async def test_provider_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/llm/provider")
    assert r.status_code == 200
    assert "llm.provider" in r.text
    assert "Ollama" in r.text and "llama.cpp" in r.text
    assert 'name="csrf_token"' in r.text


async def test_provider_post_valid_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/provider",
        data={"provider": "llamacpp", "embedding_provider": "llamacpp", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "enregistrée" in r.text

    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("llm.provider") == "llamacpp"
        assert await svc.get("llm.embedding_provider") == "llamacpp"


async def test_provider_post_invalid_value_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/provider",
        data={"provider": "vllm", "embedding_provider": "ollama", "csrf_token": admin_csrf},
    )
    # Le formulaire est ré-affiché avec un callout error (status 200)
    assert r.status_code == 200
    assert "invalide" in r.text


async def test_provider_post_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/provider",
        data={"provider": "ollama", "embedding_provider": "ollama", "csrf_token": "wrong"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Page Ollama
# ─────────────────────────────────────────────────────────────────────────────
async def test_ollama_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/llm/ollama")
    assert r.status_code == 200
    assert "llm.ollama.llm_model" in r.text
    assert "llm.ollama.embedding_model" in r.text


async def test_ollama_post_full_form_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/ollama",
        data={
            "llm_model": "gemma2:2b",
            "embedding_model": "nomic-embed-text:latest",
            "host": "host.docker.internal",
            "port": "11434",
            "num_ctx": "4096",
            "num_gpu": "-1",
            "num_parallel": "2",
            "keep_alive": "10m",
            "auto_preload": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "enregistrée" in r.text

    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("llm.ollama.llm_model") == "gemma2:2b"
        assert await svc.get("llm.ollama.num_ctx") == 4096
        assert await svc.get("llm.ollama.num_gpu") == -1
        assert await svc.get("llm.ollama.auto_preload") is True


async def test_ollama_post_auto_preload_unchecked_means_false(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/ollama",
        data={
            "llm_model": "gemma2:2b",
            "embedding_model": "nomic-embed-text:latest",
            "host": "ollama",
            "port": "11434",
            "num_ctx": "2048",
            "num_gpu": "0",
            "num_parallel": "1",
            "keep_alive": "5m",
            # auto_preload non envoyé (checkbox non cochée)
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("llm.ollama.auto_preload") is False


# ─────────────────────────────────────────────────────────────────────────────
#  Page llama.cpp
# ─────────────────────────────────────────────────────────────────────────────
async def test_llamacpp_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/llm/llamacpp")
    assert r.status_code == 200
    assert "llm.llamacpp.llm_model" in r.text
    assert "Flash attention" in r.text


async def test_llamacpp_post_full_form_saves(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/llamacpp",
        data={
            "llm_model": "llama-3.1-8B.Q4.gguf",
            "embedding_model": "nomic-embed.f16.gguf",
            "host": "host.docker.internal",
            "port": "8081",
            "server_path": "/usr/local/bin/llama-server",
            "models_dir": "/code/models",
            "ctx_size": "8192",
            "batch_size": "1024",
            "gpu_layers": "20",
            "threads": "8",
            "parallel": "2",
            "mlock": "true",
            "mmap": "true",
            "flash_attn": "true",
            "embedding_mode": "true",
            # metrics_enabled non envoyé → False
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "enregistrée" in r.text

    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("llm.llamacpp.llm_model") == "llama-3.1-8B.Q4.gguf"
        assert await svc.get("llm.llamacpp.ctx_size") == 8192
        assert await svc.get("llm.llamacpp.gpu_layers") == 20
        assert await svc.get("llm.llamacpp.flash_attn") is True
        assert await svc.get("llm.llamacpp.embedding_mode") is True
        assert await svc.get("llm.llamacpp.metrics_enabled") is False


async def test_llamacpp_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/llm/llamacpp",
        data={"llm_model": "x", "csrf_token": "wrong"},
    )
    assert r.status_code == 400
