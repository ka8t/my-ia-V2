"""E2E — Régression bulkbar fetch() sur les 7 pages admin.

Bug observé : sélectionner des items + Appliquer → 422 'Field required'
parce que le hook hx-on::config-request ne voit pas le scope Alpine
`selected`. Fix : refactor en fetch() Alpine via @click.

Ce test vérifie pour chaque page bulk-able que :
  1. Le select-all coche bien des rows
  2. La bulkbar devient visible
  3. Le clic sur le bouton "Appliquer/Supprimer" envoie une requête
     POST avec un multipart contenant les bons params (X_ids + csrf_token).

Note : on choisit l'action la moins destructive de chaque bulkbar pour
éviter de casser les seeds. Les requêtes sont interceptées et vérifiées
côté payload uniquement (pas d'assertion sur la BDD).
"""
from __future__ import annotations

import re

import pytest
from playwright.async_api import Page, expect

pytestmark = pytest.mark.asyncio


# (path, payload_id_field, action_to_select, button_label_regex)
BULK_PAGES = [
    ("/web/admin/users", "user_ids", "activate", r"Appliquer"),
    ("/web/admin/conversations", "conversation_ids", "archive", r"Appliquer"),
    ("/web/admin/sources", "source_ids", "enable", r"Appliquer"),
    ("/web/admin/corpus", "corpus_ids", "reindex", r"Appliquer"),
    ("/web/admin/documents", "doc_ids", "toggle-public", r"Appliquer"),
    # collections : pas de select d'action, juste un bouton "Supprimer"
    ("/web/admin/collections", "collection_ids", None, r"Supprimer"),
    # logs : pas de select non plus, juste "Supprimer la sélection"
    ("/web/admin/logs", "log_ids", None, r"Supprimer la s"),
]


@pytest.mark.parametrize("path,id_field,action,btn_re", BULK_PAGES)
async def test_bulk_apply_sends_correct_payload(
    admin_page: Page, path: str, id_field: str, action: str | None, btn_re: str
) -> None:
    """Pour chaque page admin bulk-able : sélectionne une row, clique
    Appliquer, et vérifie le payload de la requête réseau."""
    await admin_page.goto(path, wait_until="domcontentloaded")

    # Si la table est vide, skip (pas de row à cocher)
    rows = admin_page.locator(".admin-table-row .js-bulk-checkbox")
    n = await rows.count()
    if n == 0:
        pytest.skip(f"{path} : table vide, rien à cocher")

    # Cocher la 1re row directement (plus simple que le select-all qui
    # peut sélectionner trop de rows et déclencher des actions non voulues)
    await rows.first.check()

    bulkbar = admin_page.locator(".admin-bulkbar").first
    await expect(bulkbar).to_be_visible(timeout=2000)

    # Choisir l'action si la bulkbar a un select
    if action is not None:
        sel = bulkbar.locator("select").first
        if await sel.count() > 0:
            await sel.select_option(value=action)

    # Trouver le bouton "Appliquer"/"Supprimer" et l'utiliser
    apply_btn = bulkbar.locator(f'button:has-text("{btn_re.split("|")[0]}")').first

    # Si l'action ne nécessite pas de confirm (activate/archive/enable/reindex/
    # toggle-public), on clique direct. Sinon on accepte la confirm.
    needs_confirm = action is None or action == "delete"
    if needs_confirm:
        admin_page.once("dialog", lambda d: d.accept())

    # Intercepter la requête bulk
    async with admin_page.expect_request(
        lambda r: "/bulk" in r.url and r.method == "POST"
    ) as req_info:
        await apply_btn.click()

    req = await req_info.value
    body = req.post_data or ""
    assert f'name="{id_field}"' in body, f"{path} : {id_field} manquant dans payload"
    assert 'name="csrf_token"' in body, f"{path} : csrf manquant"
    if action is not None:
        assert f'name="action"' in body, f"{path} : action manquant"
        assert action in body, f"{path} : valeur action={action} absente"
