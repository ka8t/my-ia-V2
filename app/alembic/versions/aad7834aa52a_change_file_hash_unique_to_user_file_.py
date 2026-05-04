"""Change file_hash unique constraint to (user_id, file_hash)

Permet à différents utilisateurs d'avoir le même fichier dans leurs collections.
La contrainte était globale, elle devient par utilisateur.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aad7834aa52a'
down_revision = 'u2v3w4x5y6z7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Supprimer l'ancienne contrainte unique globale sur file_hash
    op.drop_constraint('documents_file_hash_key', 'documents', type_='unique')

    # Créer la nouvelle contrainte unique composite (user_id, file_hash)
    op.create_unique_constraint(
        'uq_document_user_file_hash',
        'documents',
        ['user_id', 'file_hash']
    )


def downgrade() -> None:
    # Supprimer la contrainte composite
    op.drop_constraint('uq_document_user_file_hash', 'documents', type_='unique')

    # Recréer la contrainte unique globale sur file_hash
    op.create_unique_constraint('documents_file_hash_key', 'documents', ['file_hash'])
