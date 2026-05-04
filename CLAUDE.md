# MY-IA — Règles de Développement

> Appliquer à chaque génération. Langue : Français.

## Contexte
Chatbot RAG (FastAPI, PostgreSQL/SQLAlchemy 2.0, ChromaDB, Ollama, JWT). MacBook M1, Docker.

## Règles Fondamentales
- **Validation** : Expliquer + lister fichiers → attendre "oui/ok/valide"
- **Tests** : Executer après chaque modif jusqu'à succès, sans demander
- **Code** : Afficher le code complet généré
- **Commits** : Auteur KL, jamais de référence Claude/Co-Authored-By. **TOUJOURS demander avant de commit** (ne jamais commiter automatiquement)

## Architecture
```
app/
├── main.py              # MINIMAL (pas de logique métier)
├── core/                # Config, deps
├── common/              # Utils, exceptions, schemas partagés
└── features/[feature]/  # Router → Service → Repository → Schemas
```
**Interdit** : Logique métier dans `main.py` ou `router.py`.
**Réutilisation API** : Toujours vérifier si une API ou une fonction similaire n'existe pas déjà (via `grep` ou exploration des dossiers `features/`) avant d'implémenter une nouvelle demande.

## Git & Docker
- `main` = Production (VPS), jamais de dev direct ni `--force`
- `dev` = Développement, merger vers main quand testé
- Rebuild uniquement si : `requirements.txt`, `Dockerfile`, `docker-compose.yml`
- **Commits** : Ne JAMAIS commit sans demande explicite de l'utilisateur
- **Déploiement** : Ne JAMAIS déployer (`./scripts/deploy.sh remote`) sans demande explicite de l'utilisateur
- **audit.config.json** : Ne JAMAIS modifier ce fichier sans demande explicite de l'utilisateur

## Code Backend
- **Async/Await** : Typage strict + `async/await` systématique.
- **Opérations Lourdes** : Les tâches comme l'embedding ou l'indexation doivent obligatoirement être asynchrones (BackgroundTasks ou queue) pour ne pas bloquer l'API.
- **Logging** : Chaque `try/except` dans un service doit loguer l'erreur avec un contexte précis.
  *Ex: `logger.error(f"Erreur lors de la création du corpus {name}: {e}")`*
- **Sécurité** : Toute route de modification (POST, PUT, DELETE) doit valider la propriété de la ressource ou les droits `superuser`/`admin`.

## PostgreSQL & Migrations
- Style : `snake_case`, pas de tirets, pas de mots réservés.
- **Migrations** : Toute modification de schéma doit impérativement s'accompagner d'un script de migration Alembic dans `app/alembic/versions/`.

## Workflow Type : Upload & Indexation
```
  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
  │  Admin  │    │ Nginx   │    │ FastAPI │    │ Storage │    │ Ollama  │
  │ Browser │    │ :8081   │    │ :8080   │    │ (disk)  │    │ :11434  │
  └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
       │              │              │              │              │
       │ 1. POST /upload/v2/async (multipart)       │              │
       │──HTTPS:8081─▶│──HTTP:8080──▶│              │              │
       │              │              │──save file──▶│              │
       │              │              │──INSERT doc──▶PostgreSQL    │
       │◀{doc_id, status:"pending"}──│              │              │
       │              │              │              │              │
       │              │              │ 2. Background task          │
       │              │              │──parse PDF───▶│              │
       │              │              │◀─text chunks──│              │
       │              │              │              │              │
       │              │              │ 3. Generate embeddings      │
       │              │              │─────────────────────────────▶│
       │              │              │◀─vectors────────────────────│
       │              │              │              │              │
       │              │              │ 4. Store in ChromaDB        │
       │              │              │──────────────▶ChromaDB:8000 │
       │              │              │              │              │
       │ 5. GET /documents/{id}/reindex/status      │              │
       │──polling────▶│─────────────▶│              │              │
       │◀{progress:75}│◀─────────────│              │              │
```

## Frontend (UI-SHARED) & Rendu
**Règle d'or : Tout code de rendu d'affichage doit impérativement utiliser le système de template et le système de render.**

**Mutualisation UI** :
- Les templates doivent être **communs/partagés au maximum**.
- Vérifier systématiquement si un template existant (dans `UI-SHARED/js/Templates.js`) peut être utilisé ou adapté avant d'en créer un nouveau.

**Tableaux & UX** :
- Tout tableau généré via template doit pouvoir être **trié** sur les colonnes pertinentes (hors actions/sélection).

**Notifications (Toasts) & i18n** :
- **Persistance** : Les toasts de type **Warning** ou **Error** doivent être **persistants** (ne pas disparaître automatiquement). Les types **Success** ou **Info** peuvent être temporaires.
- **Traduction (Obligatoire)** : **TOUS** les toasts (Success, Info, Warning, Error) doivent être systématiquement traduits via `t('cle')`. Aucun texte hardcodé n'est autorisé.
- **DRY Toasts** : Éviter la duplication de clés de traduction pour des messages identiques (ex: "Erreur lors de la sauvegarde"). Vérifier `UI-SHARED/locales/` avant d'ajouter une clé.

| Interdit | Utiliser |
|----------|----------|
| HTML inline / Manipulation DOM directe | `Templates.card()`, `Templates.render()` |
| `style=""` | Classes CSS (`UI-SHARED/css/components/`) |
| SVG inline | `Icons.nomIcone()` |
| Texte hardcodé | `t('cle')` — `UI-SHARED/locales/{fr,en}.json` |

## Corpus — Actions en Cascade
Un **corpus** regroupe des **documents** et **sources**. Toute fonctionnalité (réindexation, annulation, etc.) doit :
1. **S'appliquer aux deux types** (documents ET sources) avec code partagé
2. **Supporter les actions en cascade** : action sur corpus → appliquée à tous ses éléments
3. **Utiliser `app/common/utils/reindex.py`** : `ReindexManager` centralise progression et annulation

## Tests
```bash
docker-compose exec app python -m pytest tests/[module]/ -v --tb=short
```
- Docker obligatoire (SQLite incompatible UUID).
- Fixtures : `@pytest_asyncio.fixture`.
- Jointures : `.unique().scalar_one_or_none()`.
- **Avant commit** : Créer les tests unitaires manquants pour le code modifié/ajouté, puis exécuter tous les tests concernés jusqu'à succès.
- **Structure** : Tests dans `tests/[module]/test_[feature].py` (ex: `tests/admin/test_admin_bulk_users.py`).

## Documentation & Scripts
- **Format** : HTML (pas Markdown) dans `docs/` avec `docs/assets/doc-style.css`.
- **Plans** : `docs/Plans/PLAN-*.html` (en cours) ou `docs/Plans/Closed/` (terminés).
- **OBLIGATOIRE pour les Plans HTML** : Toujours utiliser les classes CSS de `docs/assets/doc-style.css`. Ne JAMAIS créer de HTML sans styles.
  ```html
  <link rel="stylesheet" href="../assets/doc-style.css">
  ```
  **Classes requises** :
  - `.header` + `.page` : En-tête avec icône et métadonnées
  - `.toc` + `.toc-grid` : Table des matières
  - `.section` + `.section-header` : Chaque section
  - `.card`, `.cards` : Cartes d'information
  - `.flow`, `.flow-step` : Diagrammes de flux horizontaux
  - `.vflow`, `.vflow-step` : Timeline verticale
  - `.callout`, `.callout-info/warning/danger` : Alertes
  - `.checklist` : Listes de tâches
  - `.feature-list` : Listes avec bordure accent
  - `.badge-*` : Badges colorés
- **Outils** : `./scripts/psql.sh`, `./scripts/start.sh`, `./scripts/stop.sh`.

## Checklist Pré-Commit
- [ ] API ou fonction existante vérifiée avant implémentation.
- [ ] Template existant vérifié et mutualisé.
- [ ] Rendu d'affichage via système de template et render uniquement.
- [ ] Tableaux triables (hors actions/sélection).
- [ ] Toasts Warning/Error persistants.
- [ ] TOUS les toasts traduits via i18n (sans doublons de clés).
- [ ] Tâches lourdes en BackgroundTasks / Async.
- [ ] Migration Alembic créée si modification de modèle.
- [ ] Logs détaillés dans les blocs `try/except`.
- [ ] Vérification des droits (owner/admin) on modification routes.
- [ ] **Tests unitaires créés/mis à jour** pour le code modifié.
- [ ] **Tests exécutés et passants** avant commit.
