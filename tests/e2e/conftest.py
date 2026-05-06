"""Fixtures E2E — pilote un vrai navigateur (Chromium headless) contre l'app
qui tourne en local sur http://localhost:8080 (interne du container app).

Chromium est installé sous /opt/ms-playwright (PLAYWRIGHT_BROWSERS_PATH).

Stratégie cleanup : préfixe ``e2e-`` sur les slugs créés (Corpus, ContextSource,
Document, Collection) pour qu'un teardown supprime tout en bout de session.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from sqlalchemy import delete

from app.db import async_session_maker
from app.models import Collection, ContextSource, Corpus, Document

# Le test tourne dans le même container que l'app : http://localhost:8080
# (port interne, mappé sur 8090 côté hôte).
BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8080")
ADMIN_EMAIL = "admin@test.example"
ADMIN_PASSWORD = "0vpFCb^8BYbM@%w^Q#75p6.1"
E2E_PREFIX = "e2e-"

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/ms-playwright")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fresh_e2e_slug() -> str:
    return f"{E2E_PREFIX}{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures Playwright (session scope pour partager le browser)
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def playwright_instance():
    async with async_playwright() as p:
        yield p


@pytest_asyncio.fixture(scope="session")
async def browser(playwright_instance) -> AsyncGenerator[Browser, None]:
    browser = await playwright_instance.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    yield browser
    await browser.close()


@pytest_asyncio.fixture
async def context(browser: Browser) -> AsyncGenerator[BrowserContext, None]:
    """Nouveau context isolé par test (cookies frais)."""
    ctx = await browser.new_context(base_url=BASE_URL, ignore_https_errors=True)
    yield ctx
    await ctx.close()


@pytest_asyncio.fixture
async def page(context: BrowserContext) -> AsyncGenerator[Page, None]:
    p = await context.new_page()
    yield p


@pytest_asyncio.fixture
async def admin_page(page: Page) -> Page:
    """Login admin via formulaire web → atterrit sur /web/admin.

    waitUntil=domcontentloaded car les CDN externes (HTMX, Alpine via unpkg)
    peuvent ralentir le ``load`` event sans être nécessaires aux assertions.
    """
    await page.goto("/web/login", wait_until="domcontentloaded")
    await page.fill('input[name="email"]', ADMIN_EMAIL)
    await page.fill('input[name="password"]', ADMIN_PASSWORD)
    await page.click('button[type="submit"]')
    await page.wait_for_url(re.compile(r".*/web/admin/?$"), timeout=10000)
    return page


# ─────────────────────────────────────────────────────────────────────────────
#  Cleanup BDD — supprime tout ce qui a été créé en e2e-*
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _cleanup_e2e_data() -> AsyncGenerator[None, None]:
    yield
    async with async_session_maker() as s:
        await s.execute(delete(Corpus).where(Corpus.name.like(f"{E2E_PREFIX}%")))
        await s.execute(delete(ContextSource).where(ContextSource.name.like(f"{E2E_PREFIX}%")))
        await s.execute(delete(Document).where(Document.filename.like(f"{E2E_PREFIX}%")))
        await s.execute(delete(Collection).where(Collection.name.like(f"{E2E_PREFIX}%")))
        await s.commit()
