"""Tests d'intégration — Pages admin Système Sécurité/Ops (Phase 3.8.d).

Couvre Debug, Logging, Performance, Password Policy.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import PasswordPolicy, SystemConfig
from app.web.admin_system import DEBUG_KEYS, LOGGING_KEYS, PERF_KEYS

pytestmark = pytest.mark.asyncio

ALL_KEYS = DEBUG_KEYS + LOGGING_KEYS + PERF_KEYS


@pytest.fixture(autouse=True)
async def _snapshot_secops_keys():
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
#  Debug
# ─────────────────────────────────────────────────────────────────────────────
async def test_debug_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/debug")
    assert r.status_code == 200
    assert "debug.verbose_logging" in r.text
    assert "Timing headers" in r.text


async def test_debug_post_toggles(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/debug",
        data={
            "verbose_logging": "true", "timing_headers_enabled": "true",
            # endpoints_enabled non envoyé
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("debug.verbose_logging") is True
        assert await svc.get("debug.timing_headers_enabled") is True
        assert await svc.get("debug.endpoints_enabled") is False


async def test_debug_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/debug", data={"csrf_token": "wrong"}
    )
    assert r.status_code == 400


async def test_debug_anon_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/debug")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────────────────────────────────────
async def test_logging_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/logging")
    assert r.status_code == 200
    assert "logging.level" in r.text
    assert "Rétention BDD" in r.text


async def test_logging_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/logging",
        data={
            "level": "WARNING",
            "format": "%(asctime)s [%(levelname)s] %(message)s",
            "db_enabled": "true",
            "alert_cooldown_minutes": "30",
            "level_access": "INFO",
            "level_audit": "INFO",
            "level_infra": "DEBUG",
            "level_security": "WARNING",
            "level_technical": "ERROR",
            "retention_access_days": "60",
            "retention_audit_days": "730",
            "retention_infra_days": "30",
            "retention_security_days": "730",
            "retention_technical_days": "60",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("logging.level") == "WARNING"
        assert await svc.get("logging.level_infra") == "DEBUG"
        assert await svc.get("logging.retention_audit_days") == 730
        assert await svc.get("logging.db_enabled") is True


async def test_logging_invalid_level_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/logging",
        data={
            "level": "VERBOSE",  # invalide
            "format": "x", "alert_cooldown_minutes": "15",
            "level_access": "INFO", "level_audit": "INFO", "level_infra": "INFO",
            "level_security": "INFO", "level_technical": "INFO",
            "retention_access_days": "30", "retention_audit_days": "365",
            "retention_infra_days": "14", "retention_security_days": "365",
            "retention_technical_days": "30",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "invalide" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Performance
# ─────────────────────────────────────────────────────────────────────────────
async def test_perf_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/perf")
    assert r.status_code == 200
    assert "perf.embedding_batch_size" in r.text
    assert "Re-ranking" in r.text


async def test_perf_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/perf",
        data={
            "embedding_batch_size": "200",
            "embedding_cache_size": "5000",
            "embedding_max_concurrent": "8",
            "metrics_window_size": "2000",
            "pin_access_threshold": "10",
            "pinned_cache_size": "200",
            "query_cache_size": "1000",
            "query_cache_ttl": "600.5",
            "rag_config_cache_ttl": "60.0",
            "rerank_timeout_ms": "200",
            "rerank_top_k": "10",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("perf.embedding_batch_size") == 200
        assert await svc.get("perf.embedding_max_concurrent") == 8
        assert await svc.get("perf.query_cache_ttl") == 600.5
        assert await svc.get("perf.rerank_top_k") == 10


async def test_perf_max_concurrent_clamped(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/perf",
        data={
            "embedding_batch_size": "100",
            "embedding_cache_size": "1000",
            "embedding_max_concurrent": "999",  # clamp à 64
            "metrics_window_size": "1000",
            "pin_access_threshold": "5",
            "pinned_cache_size": "100",
            "query_cache_size": "500",
            "query_cache_ttl": "300",
            "rag_config_cache_ttl": "30",
            "rerank_timeout_ms": "100",
            "rerank_top_k": "5",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("perf.embedding_max_concurrent") == 64


# ─────────────────────────────────────────────────────────────────────────────
#  Password Policy
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
async def _snapshot_password_policy():
    """Snapshot/restore de la policy active (table dédiée hors system_configs)."""
    async with async_session_maker() as s:
        result = await s.execute(
            select(PasswordPolicy).where(PasswordPolicy.is_active == True).limit(1)
        )
        policy = result.scalar_one_or_none()
        snapshot = None
        if policy is not None:
            snapshot = {
                "id": policy.id,
                "min_length": policy.min_length,
                "max_length": policy.max_length,
                "require_uppercase": policy.require_uppercase,
                "require_lowercase": policy.require_lowercase,
                "require_digit": policy.require_digit,
                "require_special": policy.require_special,
                "special_characters": policy.special_characters,
                "expire_days": policy.expire_days,
                "history_count": policy.history_count,
                "max_failed_attempts": policy.max_failed_attempts,
                "lockout_duration_minutes": policy.lockout_duration_minutes,
            }
    yield
    if snapshot:
        async with async_session_maker() as s:
            policy = await s.get(PasswordPolicy, snapshot["id"])
            if policy is not None:
                for k, v in snapshot.items():
                    if k != "id":
                        setattr(policy, k, v)
                await s.commit()


async def test_password_policy_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/password-policy")
    assert r.status_code == 200
    assert "Longueur minimale" in r.text
    assert "Tentatives max" in r.text


async def test_password_policy_post_updates(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/password-policy",
        data={
            "min_length": "12",
            "max_length": "200",
            "require_uppercase": "true",
            "require_lowercase": "true",
            "require_digit": "true",
            # require_special non envoyé → False
            "special_characters": "!@#",
            "expire_days": "90",
            "history_count": "5",
            "max_failed_attempts": "10",
            "lockout_duration_minutes": "60",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        result = await s.execute(
            select(PasswordPolicy).where(PasswordPolicy.is_active == True).limit(1)
        )
        policy = result.scalar_one()
        assert policy.min_length == 12
        assert policy.max_length == 200
        assert policy.require_special is False
        assert policy.expire_days == 90
        assert policy.lockout_duration_minutes == 60


async def test_password_policy_min_too_low_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/password-policy",
        data={
            "min_length": "2",  # < 4
            "max_length": "128",
            "require_uppercase": "true", "require_lowercase": "true",
            "require_digit": "true", "require_special": "true",
            "special_characters": "!", "expire_days": "0",
            "history_count": "0", "max_failed_attempts": "5",
            "lockout_duration_minutes": "30",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    assert "min_length" in r.text


async def test_password_policy_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/password-policy",
        data={"min_length": "8", "max_length": "128", "csrf_token": "wrong"},
    )
    assert r.status_code == 400
