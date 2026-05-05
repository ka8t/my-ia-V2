"""normalize list-type system_configs to JSON arrays

Revision ID: 20260505_1200
Revises: 20260221_1945
Create Date: 2026-05-05 12:00:00.000000

Phase 3.7.a — Vague 1.5 (fix limitation Admin config).

Les valeurs ``system_configs.value`` avec ``value_type='list'`` étaient
historiquement stockées en CSV alors que l'éditeur générique attend du JSON.
Cette migration convertit les valeurs CSV en arrays JSON pour aligner le
stockage sur le contrat de l'éditeur.

Stratégie de détection (idempotente) :
- Tenter ``json.loads(value)`` ; si déjà une liste → ne rien faire.
- Sinon, splitter par virgule, trim, filtrer les vides → re-sérialiser en JSON.

Le ``downgrade`` reconvertit JSON → CSV pour les mêmes clés.
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260505_1200'
down_revision = '20260221_1945'
branch_labels = None
depends_on = None


def _csv_to_json_list(raw: str) -> str:
    """CSV → JSON array (compact, sans espaces). Idempotent."""
    raw = (raw or "").strip()
    if not raw:
        return "[]"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError:
        pass
    items = [s.strip() for s in raw.split(",")]
    items = [s for s in items if s]
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


def _json_list_to_csv(raw: str) -> str:
    """JSON array → CSV. Idempotent (laisse le CSV intact si déjà tel)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return ",".join(str(s) for s in parsed)
    except json.JSONDecodeError:
        pass
    return raw


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT key, value FROM system_configs WHERE value_type = 'list'")
    ).fetchall()
    for key, value in rows:
        normalized = _csv_to_json_list(value)
        if normalized != value:
            conn.execute(
                sa.text("UPDATE system_configs SET value = :v WHERE key = :k"),
                {"v": normalized, "k": key},
            )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT key, value FROM system_configs WHERE value_type = 'list'")
    ).fetchall()
    for key, value in rows:
        denormalized = _json_list_to_csv(value)
        if denormalized != value:
            conn.execute(
                sa.text("UPDATE system_configs SET value = :v WHERE key = :k"),
                {"v": denormalized, "k": key},
            )
