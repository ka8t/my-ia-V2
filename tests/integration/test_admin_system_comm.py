"""Tests d'intégration — Pages admin Système SMTP + Notifications (Phase 3.8.c)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import SystemConfig
from app.web.admin_system import NOTIFICATIONS_KEYS, SMTP_KEYS

pytestmark = pytest.mark.asyncio

ALL_KEYS = SMTP_KEYS + NOTIFICATIONS_KEYS


@pytest.fixture(autouse=True)
async def _snapshot_comm_keys():
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
#  SMTP
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_smtp_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/smtp")
    assert r.status_code == 303


async def test_smtp_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/smtp")
    assert r.status_code == 200
    assert "email.backend" in r.text
    assert "STARTTLS" in r.text


async def test_smtp_post_saves_basics(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/smtp",
        data={
            "backend": "smtp",
            "email_from": "noreply@example.com",
            "email_from_name": "MY-IA",
            "smtp_host": "smtp.example.com",
            "smtp_port": "465",
            "smtp_user": "alerts",
            "smtp_password": "secret-1",
            "smtp_tls": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("email.backend") == "smtp"
        assert await svc.get("email.from") == "noreply@example.com"
        assert await svc.get("notification.email_smtp_host") == "smtp.example.com"
        assert await svc.get("notification.email_smtp_port") == 465
        assert await svc.get("notification.email_smtp_password") == "secret-1"
        assert await svc.get("notification.email_smtp_tls") is True


async def test_smtp_password_preserved_when_empty(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Soumettre password="" ne doit pas écraser la valeur stockée."""
    # Pré-poser un password
    async with async_session_maker() as s:
        await SystemConfigService(s).set(
            "notification.email_smtp_password", "kept-secret",
            updated_by=None, value_type="string",
        )

    r = await admin_client.post(
        "/web/admin/system/smtp",
        data={
            "backend": "smtp",
            "email_from": "noreply@example.com",
            "email_from_name": "MY-IA",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_user": "alerts",
            "smtp_password": "",  # vide → conserve "kept-secret"
            "smtp_tls": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get(
            "notification.email_smtp_password"
        ) == "kept-secret"


async def test_smtp_invalid_backend_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/smtp",
        data={
            "backend": "sendmail",  # invalide
            "email_from": "x@y.z", "email_from_name": "x",
            "smtp_host": "", "smtp_port": "587",
            "smtp_user": "", "smtp_password": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "invalide" in r.text


async def test_smtp_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/smtp",
        data={"backend": "console", "csrf_token": "wrong"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Notifications
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_notifications_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/system/notifications")
    assert r.status_code == 303


async def test_notifications_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/notifications")
    assert r.status_code == 200
    assert "Slack" in r.text
    assert "Webhook" in r.text


async def test_notifications_post_saves_all_channels(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/notifications",
        data={
            "email_enabled": "true",
            "email_from_address": "alerts@example.com",
            "email_to_addresses": "a@x.com,b@x.com",
            "slack_enabled": "true",
            "slack_webhook_url": "https://hooks.slack.com/services/AAA/BBB/CCC",
            "webhook_enabled": "true",
            "webhook_url": "https://example.com/hook",
            "webhook_secret": "hmac-key-1",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("notification.email_enabled") is True
        assert await svc.get("notification.email_to_addresses") == "a@x.com,b@x.com"
        assert await svc.get("notification.slack_enabled") is True
        assert await svc.get("notification.webhook_enabled") is True
        assert await svc.get("notification.webhook_secret") == "hmac-key-1"


async def test_notifications_unchecked_means_false(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/notifications",
        data={
            # email_enabled, slack_enabled, webhook_enabled non envoyés
            "email_from_address": "",
            "email_to_addresses": "",
            "slack_webhook_url": "",
            "webhook_url": "",
            "webhook_secret": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("notification.email_enabled") is False
        assert await svc.get("notification.slack_enabled") is False
        assert await svc.get("notification.webhook_enabled") is False


async def test_notifications_webhook_secret_preserved_when_empty(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    async with async_session_maker() as s:
        await SystemConfigService(s).set(
            "notification.webhook_secret", "kept-hmac",
            updated_by=None, value_type="string",
        )

    r = await admin_client.post(
        "/web/admin/system/notifications",
        data={
            "webhook_enabled": "true",
            "webhook_url": "https://example.com/hook",
            "webhook_secret": "",  # vide → conserve
            "email_from_address": "",
            "email_to_addresses": "",
            "slack_webhook_url": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("notification.webhook_secret") == "kept-hmac"


async def test_notifications_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/notifications",
        data={"email_enabled": "true", "csrf_token": "wrong"},
    )
    assert r.status_code == 400
