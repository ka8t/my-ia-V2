"""Tests d'intégration — Pages admin Système Storage + Speech (Phase 3.8.b)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import SystemConfig
from app.web.admin_system import SPEECH_KEYS, STORAGE_KEYS

pytestmark = pytest.mark.asyncio

ALL_KEYS = STORAGE_KEYS + SPEECH_KEYS


@pytest.fixture(autouse=True)
async def _snapshot_infra_keys():
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
#  Storage
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_storage_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/storage")
    assert r.status_code == 303


async def test_storage_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/storage")
    assert r.status_code == 200
    assert "storage.backend" in r.text
    assert "MIME types acceptés" in r.text


async def test_storage_post_saves_lists(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/storage",
        data={
            "backend": "local",
            "local_path": "/data/uploads",
            "max_file_size_mb": "200",
            "default_quota_mb": "500",
            "allowed_mime_types": "application/pdf\ntext/plain\nimage/png",
            "blocked_extensions": ".exe\nbat\n.sh",  # bat sans point → normalisé
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("storage.max_file_size_mb") == 200
        assert await svc.get("storage.default_quota_mb") == 500
        mimes = await svc.get("storage.allowed_mime_types")
        assert mimes == ["application/pdf", "text/plain", "image/png"]
        exts = await svc.get("storage.blocked_extensions")
        assert exts == [".exe", ".bat", ".sh"]


async def test_storage_invalid_backend_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/storage",
        data={
            "backend": "ftp",  # invalide
            "local_path": "/data/uploads",
            "max_file_size_mb": "50",
            "default_quota_mb": "100",
            "allowed_mime_types": "",
            "blocked_extensions": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "invalide" in r.text


async def test_storage_max_file_size_clamped(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/storage",
        data={
            "backend": "local",
            "local_path": "/data/uploads",
            "max_file_size_mb": "0",  # → clamp à 1
            "default_quota_mb": "100",
            "allowed_mime_types": "",
            "blocked_extensions": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("storage.max_file_size_mb") == 1


async def test_storage_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/storage",
        data={"backend": "local", "csrf_token": "wrong"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Speech
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_speech_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/speech")
    assert r.status_code == 303


async def test_speech_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/speech")
    assert r.status_code == 200
    assert "speech.enabled" in r.text
    assert "Whisper" in r.text


async def test_speech_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/speech",
        data={
            "enabled": "true",
            "default_language": "en",
            "model": "medium",
            "max_duration": "120",
            "timeout": "180",
            "silence_duration_ms": "2000",
            "silence_threshold": "0.05",
            "auto_send_enabled": "true",
            "tts_enabled": "true",
            "tts_mode": "server",
            "tts_default_rate": "1.2",
            "whisper_host": "whisper",
            "whisper_port": "8000",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("speech.enabled") is True
        assert await svc.get("speech.model") == "medium"
        assert await svc.get("speech.tts_default_rate") == 1.2
        assert await svc.get("speech.silence_threshold") == 0.05
        assert await svc.get("whisper.host") == "whisper"


async def test_speech_invalid_model_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/speech",
        data={
            "enabled": "true", "default_language": "fr",
            "model": "xxl",  # invalide
            "max_duration": "60", "timeout": "120",
            "silence_duration_ms": "1500", "silence_threshold": "0.01",
            "tts_mode": "native", "tts_default_rate": "1.0",
            "whisper_host": "whisper", "whisper_port": "8000",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "invalide" in r.text


async def test_speech_tts_rate_out_of_range_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/speech",
        data={
            "enabled": "true", "default_language": "fr", "model": "small",
            "max_duration": "60", "timeout": "120",
            "silence_duration_ms": "1500", "silence_threshold": "0.01",
            "tts_mode": "native", "tts_default_rate": "5.0",  # hors borne
            "whisper_host": "whisper", "whisper_port": "8000",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "tts_default_rate" in r.text


async def test_speech_unchecked_bools_are_false(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/speech",
        data={
            # enabled, auto_send_enabled, tts_enabled : NON envoyés
            "default_language": "fr", "model": "small",
            "max_duration": "60", "timeout": "120",
            "silence_duration_ms": "1500", "silence_threshold": "0.01",
            "tts_mode": "off", "tts_default_rate": "1.0",
            "whisper_host": "whisper", "whisper_port": "8000",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("speech.enabled") is False
        assert await svc.get("speech.auto_send_enabled") is False
        assert await svc.get("speech.tts_enabled") is False


async def test_speech_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/speech",
        data={"model": "small", "csrf_token": "wrong"},
    )
    assert r.status_code == 400
