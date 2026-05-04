# MY-IA V2

Refonte complète de [MY-IA](https://github.com/ka8t/my-ia) — bascule du frontend JS vers une stack 100% Python (FastAPI + Jinja2 + HTMX).

## Statut

🚧 **En préparation** — voir [docs/Plans/PLAN-MIGRATION-PYTHON.html](docs/Plans/PLAN-MIGRATION-PYTHON.html)

## Stack cible

| Couche | Technologie |
|--------|-------------|
| API | FastAPI (Python 3.11+) |
| ORM | SQLAlchemy 2.0 async |
| BDD | PostgreSQL 16 |
| Vecteurs | ChromaDB |
| LLM | Ollama / llama.cpp |
| Templates | Jinja2 |
| Interactivité | HTMX + Alpine.js |
| Auth | fastapi-users (JWT + cookies session) |
| Migrations | Alembic |
| Tests | pytest + Playwright (E2E) |
| Containers | Docker / docker-compose |

## Origine

Snapshot de référence de la stack JS : tag [`v1.0.0-js-final`](https://github.com/ka8t/my-ia/releases/tag/v1.0.0-js-final) sur `my-ia`.

## Branches

- `main` — Production
- `dev` — Développement actif

## Règles projet

Voir [CLAUDE.md](CLAUDE.md).
