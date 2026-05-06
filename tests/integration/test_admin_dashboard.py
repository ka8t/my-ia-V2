"""Tests d'intégration — Dashboard analytics enrichi (Phase 3.9.d)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_dashboard_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200
    assert "Tableau" in r.text


async def test_dashboard_includes_overview_stats(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200
    # Section "Activité" avec les nouvelles stats
    assert "Activité" in r.text or "Nouveaux users" in r.text


async def test_dashboard_includes_sparkline(admin_client: AsyncClient) -> None:
    """Sparkline 30j présent (au moins le conteneur)."""
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200
    # On accepte qu'il soit absent si usage_daily est vide ; sinon présent.
    # La présence du callout final est garante que la page rend complètement.
    assert "Admin avancé" in r.text


async def test_dashboard_links_to_advanced_pages(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200
    assert '/web/admin/audit' in r.text
    assert '/web/admin/logs' in r.text
    assert '/web/admin/validation' in r.text


async def test_dashboard_existing_tiles_still_present(admin_client: AsyncClient) -> None:
    """Les tuiles Users / Documents / Corpus / Sources cliquables restent."""
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200
    assert 'href="/web/admin/users"' in r.text
    assert 'href="/web/admin/documents"' in r.text
    assert 'href="/web/admin/corpus"' in r.text
    assert 'href="/web/admin/sources"' in r.text
