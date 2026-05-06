"""Smoke E2E — validation minimale du setup Playwright + login admin."""
from __future__ import annotations

import pytest
from playwright.async_api import Page

pytestmark = pytest.mark.asyncio


async def test_login_page_loads(page: Page) -> None:
    """La page login charge et contient le formulaire avec CSRF."""
    await page.goto("/web/login", wait_until="domcontentloaded")
    assert await page.title() != ""
    # Champs auth présents
    assert await page.locator('input[name="email"]').count() == 1
    assert await page.locator('input[name="password"]').count() == 1
    # CSRF token rendu dans la page
    assert await page.locator('input[name="csrf_token"]').count() >= 1


async def test_admin_login_lands_on_console(admin_page: Page) -> None:
    """Le redirect post-login admin doit pointer vers /web/admin et la console
    doit afficher la sidebar + le tableau de bord."""
    # Sidebar admin présente
    sidebar = admin_page.locator(".admin-nav")
    await sidebar.wait_for(state="visible", timeout=3000)
    # Au moins le lien Tableau de bord et Corpus
    assert await admin_page.locator('a[href="/web/admin"]').count() >= 1
    assert await admin_page.locator('a[href="/web/admin/corpus"]').count() >= 1
    assert await admin_page.locator('a[href="/web/admin/sources"]').count() >= 1
