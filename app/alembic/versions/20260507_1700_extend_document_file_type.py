"""extend documents.file_type VARCHAR(50) → VARCHAR(150)

Bug : mime type xlsx (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)
fait 71 chars, dépassait la colonne VARCHAR(50) → StringDataRightTruncationError
sur upload xlsx/docx/pptx.

Revision ID: 20260507_1700
Revises: 20260505_1200
Create Date: 2026-05-07 17:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260507_1700"
down_revision = "20260505_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "file_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=150),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Si on revient en arrière, attention : tout file_type > 50 chars sera tronqué
    op.alter_column(
        "documents",
        "file_type",
        existing_type=sa.String(length=150),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
