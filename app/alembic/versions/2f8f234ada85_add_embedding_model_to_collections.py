"""add_embedding_model_to_collections

Revision ID: 2f8f234ada85
Revises: e2f3g4h5i6j7
Create Date: 2026-01-30

Ajoute la colonne embedding_model a la table collections
pour tracer le modele d'embedding utilise lors de l'indexation.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2f8f234ada85'
down_revision = 'e2f3g4h5i6j7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('collections', sa.Column('embedding_model', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('collections', 'embedding_model')
