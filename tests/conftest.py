"""Fixtures globales pour la suite de tests V2.

Stratégie d'intégration : les tests parlent à l'app FastAPI via
``httpx.AsyncClient(ASGITransport)`` et utilisent la BDD Postgres réelle de
dev (montée par docker-compose). Pas de magic transaction-rollback : chaque
test s'isole en préfixant ses slugs (``pytest-XXX``) ; un teardown autouse
nettoie ce qu'il a créé.

Pré-requis : utilisateur ``admin@test.example`` seedé avec le mot de passe
de référence (voir MEMORY.md).
"""
from __future__ import annotations

import re
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_maker
from app.main import app
from app.models import ContextSource, Corpus

ADMIN_EMAIL = "admin@test.example"
ADMIN_PASSWORD = "0vpFCb^8BYbM@%w^Q#75p6.1"
TEST_PREFIX = "pytest-"


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
_CSRF_RE = re.compile(
    r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']'
    r'|value=["\']([^"\']+)["\']\s+name=["\']csrf_token["\']'
)


def extract_csrf(html: str) -> str:
    """Extract a csrf_token value from any form embedded in *html*.

    Supports both attribute orderings (``name`` first OR ``value`` first).
    """
    m = _CSRF_RE.search(html)
    assert m, "csrf_token introuvable dans le HTML"
    return m.group(1) or m.group(2)


def fresh_slug() -> str:
    """Slug unique préfixé pytest- (cleanup automatique)."""
    return f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures core
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Anonymous httpx client over ASGI (cookies persisted across calls)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    """Logged-in admin httpx client. Performs a real ``/web/login`` round-trip."""
    r = await client.get("/web/login")
    assert r.status_code == 200, r.text
    csrf = extract_csrf(r.text)

    r = await client.post(
        "/web/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "csrf_token": csrf},
    )
    assert r.status_code in (302, 303), (
        f"login a échoué (status={r.status_code}): {r.text[:300]}"
    )
    return client


@pytest_asyncio.fixture
async def admin_csrf(admin_client: AsyncClient) -> str:
    """CSRF token valide post-login (récupéré depuis le dashboard admin)."""
    r = await admin_client.get("/web/admin")
    assert r.status_code == 200, r.text
    return extract_csrf(r.text)


# ─────────────────────────────────────────────────────────────────────────────
#  Cleanup autouse — supprime tout ce que les tests ont créé
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _cleanup_test_data() -> AsyncGenerator[None, None]:
    yield
    async with async_session_maker() as s:
        await s.execute(delete(Corpus).where(Corpus.name.like(f"{TEST_PREFIX}%")))
        await s.execute(delete(ContextSource).where(ContextSource.name.like(f"{TEST_PREFIX}%")))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Markers
# ─────────────────────────────────────────────────────────────────────────────
def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
