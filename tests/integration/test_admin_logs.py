"""Tests d'intégration — App logs viewer (Phase 3.9.b)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_anon_logs_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/logs")
    assert r.status_code == 303


async def test_logs_page_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs")
    assert r.status_code == 200
    assert "Logs" in r.text
    assert 'name="level"' in r.text
    assert 'name="log_category"' in r.text
    assert 'name="search"' in r.text


async def test_logs_filter_level(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?level=ERROR")
    assert r.status_code == 200


async def test_logs_filter_category(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?log_category=access")
    assert r.status_code == 200


async def test_logs_search_text(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?search=login")
    assert r.status_code == 200


async def test_logs_filter_alerts_only(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?is_alert=yes")
    assert r.status_code == 200


async def test_logs_invalid_level_silently_ignored(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?level=NUCLEAR")
    assert r.status_code == 200


async def test_logs_invalid_date_silently_ignored(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?date_from=foo")
    assert r.status_code == 200


async def test_logs_pagination_clamp(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/logs?page=0&page_size=99999")
    assert r.status_code == 200
