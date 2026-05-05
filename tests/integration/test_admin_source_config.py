"""Tests d'intégration — Éditeur de config technique sources (Vague 2.6)."""
from __future__ import annotations

import json
import uuid as _uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import ContextSource
from tests.conftest import fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _create_source(source_type: str = "web", config: dict | None = None) -> ContextSource:
    async with async_session_maker() as s:
        slug = fresh_slug()
        src = ContextSource(
            name=slug,
            display_name=f"Pytest Cfg {slug}",
            source_type=source_type,
            config=config or {},
            is_enabled=False,
        )
        s.add(src)
        await s.commit()
        await s.refresh(src)
        return src


# ─────────────────────────────────────────────────────────────────────────────
#  GET /config — page éditeur
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_redirected_to_login(client: AsyncClient) -> None:
    r = await client.get(f"/web/admin/sources/{_uuid.uuid4()}/config")
    assert r.status_code == 303


async def test_get_config_unknown_returns_404(admin_client: AsyncClient) -> None:
    r = await admin_client.get(f"/web/admin/sources/{_uuid.uuid4()}/config")
    assert r.status_code == 404


async def test_get_config_renders_form(admin_client: AsyncClient) -> None:
    src = await _create_source(source_type="web", config={"provider": "duckduckgo"})
    r = await admin_client.get(f"/web/admin/sources/{src.id}/config")
    assert r.status_code == 200
    assert 'name="config_text"' in r.text
    assert "duckduckgo" in r.text
    # Aide affichée pour le type web
    assert "provider" in r.text
    assert "duckduckgo, google, url, scrape" in r.text


async def test_get_config_pretty_prints_existing(admin_client: AsyncClient) -> None:
    src = await _create_source(
        source_type="api",
        config={"base_url": "https://api.example.com", "endpoint": "/search"},
    )
    r = await admin_client.get(f"/web/admin/sources/{src.id}/config")
    assert r.status_code == 200
    # Le contenu d'un <textarea> est HTML-escapé par Jinja (auto-escape ON).
    # On cherche les sub-strings sans guillemets.
    assert "base_url" in r.text
    assert "https://api.example.com" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  POST /config — validation + save
# ─────────────────────────────────────────────────────────────────────────────
async def test_post_config_invalid_json_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": "not json {", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400
    assert "JSON invalide" in r.text


async def test_post_config_array_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": "[1, 2, 3]", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400
    assert "objet JSON" in r.text


async def test_post_config_invalid_csrf_returns_400(
    admin_client: AsyncClient,
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": "{}", "csrf_token": "wrong"},
    )
    assert r.status_code == 400


# Validation par type — web
async def test_post_web_missing_provider_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": "{}", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400
    # Apostrophes HTML-escapées dans la callout d'erreur → assertion sans quotes.
    assert "provider" in r.text
    assert "requis" in r.text


async def test_post_web_google_missing_keys_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={
            "config_text": json.dumps({"provider": "google"}),
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    assert "api_key" in r.text


async def test_post_web_url_provider_missing_url_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={
            "config_text": json.dumps({"provider": "url"}),
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    assert "url" in r.text


async def test_post_web_valid_saves(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={
            "config_text": json.dumps({"provider": "duckduckgo", "language": "fr"}),
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "Configuration enregistrée" in r.text

    async with async_session_maker() as session:
        refreshed = await session.get(ContextSource, src.id)
        assert refreshed is not None
        assert refreshed.config == {"provider": "duckduckgo", "language": "fr"}


# Validation par type — api
async def test_post_api_missing_base_url_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="api")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={
            "config_text": json.dumps({"endpoint": "/search"}),
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    assert "base_url" in r.text


async def test_post_api_valid_saves(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="api")
    config = {
        "base_url": "https://api.example.com",
        "endpoint": "/search",
        "method": "GET",
    }
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": json.dumps(config), "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Configuration enregistrée" in r.text


# Validation par type — database
async def test_post_database_missing_required_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="database")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={
            "config_text": json.dumps({"db_type": "postgres"}),
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    # query_template est testé en premier après db_type
    assert "query_template" in r.text or "host" in r.text


async def test_post_database_valid_saves(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="database")
    config = {
        "db_type": "postgres",
        "host": "localhost",
        "database": "mydb",
        "username": "user",
        "query_template": "SELECT id, content FROM docs WHERE content ILIKE :q LIMIT 10",
    }
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": json.dumps(config), "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Configuration enregistrée" in r.text

    async with async_session_maker() as session:
        refreshed = await session.get(ContextSource, src.id)
        assert refreshed is not None
        assert refreshed.config["db_type"] == "postgres"
        assert refreshed.config["query_template"].startswith("SELECT")


# Empty body → {} — accepté seulement si type sans champs requis (aucun ici)
async def test_post_empty_body_for_web_fails_validation(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    src = await _create_source(source_type="web")
    r = await admin_client.post(
        f"/web/admin/sources/{src.id}/config",
        data={"config_text": "", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400
    assert "provider" in r.text


async def test_post_unknown_source_returns_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        f"/web/admin/sources/{_uuid.uuid4()}/config",
        data={"config_text": "{}", "csrf_token": admin_csrf},
    )
    assert r.status_code == 404
