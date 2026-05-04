# MY-IA V2 — Règles de Développement

> Appliquer à chaque génération. Langue : Français.

## Contexte
Refonte 100% Python de [my-ia](https://github.com/ka8t/my-ia). Stack : FastAPI + Jinja2 + HTMX + Alpine.js + SQLAlchemy 2.0 async + PostgreSQL + ChromaDB + Ollama/llama.cpp + JWT (API) / cookies session (HTML). MacBook M1, Docker.

**Origine** : tag `v1.0.0-js-final` sur `ka8t/my-ia`.

## Règles Fondamentales
- **Validation** : Expliquer + lister fichiers → attendre "oui/ok/valide"
- **Tests** : Exécuter après chaque modif jusqu'à succès, sans demander
- **Code** : Afficher le code complet généré
- **Commits** : Auteur KL, jamais de référence Claude/Co-Authored-By. **TOUJOURS demander avant de commit**

## Architecture

```
app/
├── main.py               # MINIMAL — montage routers, middleware, lifespan
├── core/                 # config, deps, bootstrap, logging
├── common/               # llm, rag, storage, crypto, i18n, utils, schemas
├── features/             # Logique métier (Service/Repository/Schemas par feature)
├── api/v1/               # Routes JSON (clients tiers, mobile)
├── web/                  # Routes HTML (Jinja2 + HTMX)
├── templates/            # layouts/, pages/, partials/, macros/
├── static/               # css, js (htmx, alpine), icons, images
├── locales/              # fr.json, en.json (port direct)
└── alembic/versions/     # Migrations
```

**Interdit** :
- Logique métier dans `main.py`, `api/v1/*.py`, `web/*.py` → tout passe par `features/[feature]/service.py`
- Réécrire un service déjà présent dans `app/common/` ou `features/[feature]/` (toujours `grep` avant)

## Code Backend
- **Async/Await** : Typage strict + `async/await` systématique
- **Opérations lourdes** (embedding, indexation) → `BackgroundTasks` ou queue, jamais bloquer la requête
- **Logging** : Chaque `try/except` dans un service doit loguer avec contexte précis
  *Ex : `logger.error(f"Erreur création corpus {name}: {e}")`*
- **Sécurité** : Toute route POST/PUT/DELETE doit valider la propriété de la ressource ou les droits `superuser`/`admin`
- **API versioning** : Toutes les routes JSON sous `/api/v1/`

## Frontend Jinja2 / HTMX (V2)

**Règle d'or** : tout HTML rendu **côté serveur** via Jinja. Aucune génération de DOM en JS.

### Structure templates
```
templates/
├── layouts/{base,auth,user,admin}.html
├── pages/{auth,chat,documents,admin}/*.html       # Pages complètes
├── partials/                                       # Fragments rendus par HTMX
└── macros/{card,form,table,icon,badge,toast}.html # Composants mutualisés
```

### Règles obligatoires
- **Macros mutualisées** : avant de créer un nouveau template, vérifier `templates/macros/`
- **Pas de HTML dupliqué** entre pages — extraire en macro ou partial
- **HTMX pour les updates** : `hx-get`, `hx-post`, `hx-swap`, `hx-target`
- **Alpine.js** uniquement pour : toggles, dropdowns, modals locaux (pas de state global)
- **CSRF** : token automatique sur tous les `hx-post`/`hx-put`/`hx-delete` via middleware
- **SVG icons** : macro `{{ icon('nom') }}` lisant `app/static/icons/*.svg`

### i18n
- Locales : `app/locales/{fr,en}.json` (port direct depuis my-ia)
- Helper Jinja : `{{ t('cle') }}` (fonction injectée dans le contexte)
- **TOUS les textes** affichés à l'utilisateur via `t()`, jamais de hardcode

### Notifications (toasts)
- **Persistance** : Warning et Error → persistants. Success/Info → temporaires (auto-dismiss CSS)
- **Traduction obligatoire** via `t('cle')`
- **DRY** : vérifier `app/locales/` avant d'ajouter une clé doublon

### Tableaux
- Tout tableau via macro `{{ table(headers, rows) }}` doit être triable
- Tri serveur : `hx-get="?sort=col"` → re-render du tbody

| Interdit | Utiliser |
|----------|----------|
| HTML inline dans le code Python | Templates Jinja + macros |
| Manipulation DOM JS pour rendu | `hx-get` → partial Jinja |
| Texte hardcodé | `{{ t('cle') }}` |
| `style="..."` dans templates | Classes CSS dans `app/static/css/` |
| SVG inline copié-collé | `{{ icon('nom') }}` |

## Auth Web
- **Cookies HttpOnly** signés (itsdangerous) via `SessionMiddleware`
- **CSRF token** sur toutes les actions de modification (POST/PUT/DELETE) côté HTML
- **JWT** réservé aux clients API (`/api/v1/*`)
- `fastapi-users` gère les deux

## Streaming Chat
- **SSE via HTMX** (`hx-ext="sse"`, `sse-connect`, `sse-swap`)
- Endpoint backend : `EventSourceResponse` (sse-starlette ou natif)
- Token-by-token streaming RAG vers `partials/chat/message.html`

## PostgreSQL & Migrations
- Style : `snake_case`, pas de tirets, pas de mots réservés
- **Migrations** : Toute modification de schéma → script Alembic dans `app/alembic/versions/`
- BDD V2 : `my_ia_v2_db` (séparée de my-ia v1)

## Corpus — Actions en Cascade
Un **corpus** regroupe **documents** et **sources**. Toute fonctionnalité (réindexation, annulation) doit :
1. S'appliquer aux deux types avec code partagé
2. Supporter actions en cascade : action sur corpus → tous ses éléments
3. Utiliser `app/common/utils/reindex.py` (`ReindexManager`)

## Git & Docker
- `main` = Production (VPS), jamais de dev direct ni `--force`
- `dev` = Développement, merger vers main quand testé
- Rebuild uniquement si : `requirements.txt`, `Dockerfile`, `docker-compose.yml`
- **Commits** : Ne JAMAIS commit sans demande explicite
- **Déploiement** : Ne JAMAIS déployer sans demande explicite
- Préfixe Docker : `my_ia_v2` (cohabitation avec my-ia v1 possible)

## Tests
```bash
docker-compose exec app python -m pytest tests/[module]/ -v --tb=short
```
- Docker obligatoire (SQLite incompatible UUID)
- Fixtures : `@pytest_asyncio.fixture`
- Jointures : `.unique().scalar_one_or_none()`
- **E2E** : Playwright (vrai navigateur, HTMX/Alpine évalués)
- **Avant commit** : créer les tests unitaires manquants pour le code modifié, puis exécuter

### Structure
```
tests/
├── unit/              # Logique pure (services, utils)
├── integration/       # Routes API + DB
└── e2e/               # Playwright — pages HTML rendues
```

## Documentation & Scripts
- **Format** : HTML (pas Markdown) dans `docs/` avec `docs/assets/doc-style.css`
- **Plans** : `docs/Plans/PLAN-*.html` (en cours) ou `docs/Plans/Closed/` (terminés)
- **OBLIGATOIRE pour les Plans HTML** : utiliser les classes CSS de `docs/assets/doc-style.css` (header, page, toc, section, card, callout, badge-*, etc.)
- **Outils** : `./scripts/psql.sh`, `./scripts/start.sh`, `./scripts/stop.sh`, `./scripts/reset-password.sh`

## Checklist Pré-Commit
- [ ] API ou fonction existante vérifiée avant implémentation (grep `app/common/`, `app/features/`)
- [ ] Macro/partial Jinja existant vérifié et mutualisé avant création
- [ ] Rendu HTML côté serveur uniquement (pas de DOM JS)
- [ ] Tableaux triables côté serveur
- [ ] Toasts Warning/Error persistants
- [ ] TOUS les textes traduits via `t()` (sans doublons de clés)
- [ ] Tâches lourdes en BackgroundTasks / Async
- [ ] Migration Alembic créée si modification de modèle
- [ ] Logs détaillés dans les blocs `try/except`
- [ ] Vérification des droits (owner/admin) sur routes de modification
- [ ] CSRF token vérifié sur les routes HTML POST/PUT/DELETE
- [ ] Tests unitaires + E2E créés/mis à jour
- [ ] Tests exécutés et passants
