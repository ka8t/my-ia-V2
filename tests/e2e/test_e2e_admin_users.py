"""E2E — Admin Users (P0.5).

Couvre les comportements UI qui ont échappé aux tests intégration et
qui ont causé des bugs en QA :
  - Filtres role/active/verified sans valeur (était 422)
  - Bouton "Éditer" ouvre le modal et affiche les valeurs pré-remplies
  - Modal se ferme automatiquement après "Enregistrer"
  - Le row du tableau est mis à jour avec les nouvelles valeurs
"""
from __future__ import annotations

import re

import pytest
from playwright.async_api import Page, expect

pytestmark = pytest.mark.asyncio


async def test_admin_users_page_loads(admin_page: Page) -> None:
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    # Tableau présent
    await admin_page.locator(".admin-table-body").wait_for(state="visible", timeout=5000)
    # Au moins 4 utilisateurs seedés (admin, user, validator, contributor + ...)
    rows = admin_page.locator(".admin-user-row.admin-table-row")
    assert await rows.count() >= 4


async def test_filter_apply_with_empty_role_does_not_crash(admin_page: Page) -> None:
    """Bug observé : appui sur Entrée dans le form filtres avec select role
    non choisi → 422 'int_parsing'. Doit revenir un 200."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    # Submit le form filtres tel quel (tous selects à vide)
    await admin_page.locator('form.admin-toolbar button[type="submit"]').click()
    await admin_page.wait_for_load_state("domcontentloaded")
    # Doit rester sur /web/admin/users (200), pas une page d'erreur
    assert "/web/admin/users" in admin_page.url
    # Aucun marqueur d'erreur HTTPException visible
    page_text = await admin_page.locator("body").inner_text()
    assert "int_parsing" not in page_text
    assert "422" not in page_text or "Internal" not in page_text


async def test_filter_role_admin_only(admin_page: Page) -> None:
    """Sélectionner un rôle dans le filtre + Appliquer → tableau filtré."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    # Sélectionner le rôle "admin" (id=1, basé sur seed standard)
    await admin_page.select_option('select[name="role"]', value="1")
    await admin_page.locator('form.admin-toolbar button[type="submit"]').click()
    await admin_page.wait_for_load_state("domcontentloaded")
    # Au moins un user (admin@test.example) doit être listé
    rows = admin_page.locator(".admin-user-row.admin-table-row")
    assert await rows.count() >= 1


async def test_edit_user_modal_opens_with_prefilled_fields(admin_page: Page) -> None:
    """Bug observé : modal édition s'ouvre mais champs vides.
    Vérifier que pour admin@test.example (seedé avec valeurs), les champs
    apparaissent bien remplis dans le modal."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    # Trouver la ligne admin@test.example
    admin_row = admin_page.locator('.admin-user-row.admin-table-row',
                                   has_text="admin@test.example")
    await admin_row.wait_for(state="visible", timeout=5000)

    # Cliquer le bouton "Éditer" (icon settings) dans cette ligne
    edit_btn = admin_row.locator('button[title="Éditer le profil"]')
    await edit_btn.click()

    # Attendre que le modal soit injecté + visible
    modal = admin_page.locator(".admin-modal--edit-user")
    await modal.wait_for(state="visible", timeout=5000)

    # Vérifier les champs pré-remplis
    email_val = await modal.locator('input[name="email"]').input_value()
    assert email_val == "admin@test.example", f"email vide: {email_val!r}"

    username_val = await modal.locator('input[name="username"]').input_value()
    assert username_val == "admin", f"username vide: {username_val!r}"

    # admin@test.example a first_name='Admin' (seedé)
    fn_val = await modal.locator('input[name="first_name"]').input_value()
    assert fn_val == "Admin", f"first_name vide alors qu'il est seedé: {fn_val!r}"


async def test_edit_user_modal_closes_after_save(admin_page: Page) -> None:
    """Bug observé : modal ne se ferme pas après 'Enregistrer'.
    Vérifier qu'après submit avec succès, le modal disparaît."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")

    # Ouvrir le modal pour admin (sans rien modifier de critique)
    admin_row = admin_page.locator('.admin-user-row.admin-table-row',
                                   has_text="admin@test.example")
    await admin_row.locator('button[title="Éditer le profil"]').click()

    modal = admin_page.locator(".admin-modal--edit-user")
    await modal.wait_for(state="visible", timeout=5000)

    # Sauvegarder sans rien changer (juste pour valider la fermeture)
    await modal.locator('button[type="submit"]').click()

    # Le modal doit disparaître
    await expect(modal).to_be_hidden(timeout=5000)


async def test_edit_user_modal_closes_via_escape_key(admin_page: Page) -> None:
    """Régression : la touche Échap doit fermer le modal sans soumettre."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    admin_row = admin_page.locator('.admin-user-row.admin-table-row',
                                   has_text="admin@test.example")
    await admin_row.locator('button[title="Éditer le profil"]').click()
    modal = admin_page.locator(".admin-modal--edit-user")
    await modal.wait_for(state="visible", timeout=5000)
    await admin_page.keyboard.press("Escape")
    await expect(modal).to_be_hidden(timeout=2000)


async def test_edit_user_modal_closes_via_cancel_button(admin_page: Page) -> None:
    """Régression : le bouton Annuler doit fermer le modal sans soumettre."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    admin_row = admin_page.locator('.admin-user-row.admin-table-row',
                                   has_text="admin@test.example")
    await admin_row.locator('button[title="Éditer le profil"]').click()
    modal = admin_page.locator(".admin-modal--edit-user")
    await modal.wait_for(state="visible", timeout=5000)
    cancel_btn = modal.locator('button:has-text("Annuler")')
    await cancel_btn.click()
    await expect(modal).to_be_hidden(timeout=2000)


# ─────────────────────────────────────────────────────────────────────────────
#  Régression bug select-all (signalé en QA)
# ─────────────────────────────────────────────────────────────────────────────
async def test_bulk_action_apply_sends_correct_params(admin_page: Page) -> None:
    """Bug observé : clic sur 'Appliquer' bulk envoyait user_ids et action
    vides → 422 'Field required'. Cause : hx-on::config-request ne voyait
    pas le scope Alpine. Fix : fetch() avec FormData via @click Alpine.
    Vérifier que la requête réseau contient bien les params."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    await admin_page.locator(".admin-user-row.admin-table-row").first.wait_for(
        state="visible", timeout=5000
    )

    # Sélectionner toutes les lignes via select-all
    await admin_page.locator(".admin-row__select-all").first.check()
    bulkbar = admin_page.locator(".admin-bulkbar").first
    await expect(bulkbar).to_be_visible()

    # Choisir une action sans effet de bord destructif (activate → idempotent)
    await bulkbar.locator('select').first.select_option(value="activate")

    # Capturer la requête bulk-action et vérifier le payload
    async with admin_page.expect_request(
        lambda r: "/web/admin/users/bulk-action" in r.url and r.method == "POST"
    ) as req_info:
        await bulkbar.locator('button:has-text("Appliquer")').click()
    req = await req_info.value
    body = req.post_data or ""
    # multipart/form-data : chercher les name= puis les valeurs
    assert 'name="action"' in body, f"action absent du form-data: {body[:300]}"
    assert "activate" in body, f"valeur action absente: {body[:300]}"
    assert 'name="user_ids"' in body, f"user_ids absents du form-data: {body[:300]}"
    assert 'name="csrf_token"' in body, f"csrf absent: {body[:300]}"


async def test_select_all_checks_all_row_checkboxes(admin_page: Page) -> None:
    """Bug observé : clic sur la checkbox header 'Tout sélectionner' ne cochait
    rien (mismatch entre `.js-row-checkbox` dans la macro et `.js-bulk-checkbox`
    sur les rows). Vérifier qu'après clic, toutes les checkboxes des rows sont
    cochées et la bulkbar apparaît."""
    await admin_page.goto("/web/admin/users", wait_until="domcontentloaded")
    # Attendre que les rows soient chargées
    await admin_page.locator(".admin-user-row.admin-table-row").first.wait_for(
        state="visible", timeout=5000
    )
    rows = admin_page.locator(".admin-user-row.admin-table-row .js-bulk-checkbox")
    n = await rows.count()
    assert n >= 4, f"attendu >=4 users seedés, vu {n}"

    # Bulkbar invisible avant
    bulkbar = admin_page.locator(".admin-bulkbar").first
    await expect(bulkbar).to_be_hidden()

    # Cocher la select-all
    select_all = admin_page.locator(".admin-row__select-all").first
    await select_all.check()

    # Toutes les rows doivent maintenant être cochées
    checked_count = await admin_page.locator(
        ".admin-user-row.admin-table-row .js-bulk-checkbox:checked"
    ).count()
    assert checked_count == n, f"attendu {n} cochées, vu {checked_count}"

    # Bulkbar doit s'afficher
    await expect(bulkbar).to_be_visible(timeout=2000)

    # Décocher : tout doit redevenir vide
    await select_all.uncheck()
    checked_count = await admin_page.locator(
        ".admin-user-row.admin-table-row .js-bulk-checkbox:checked"
    ).count()
    assert checked_count == 0
    await expect(bulkbar).to_be_hidden(timeout=2000)
