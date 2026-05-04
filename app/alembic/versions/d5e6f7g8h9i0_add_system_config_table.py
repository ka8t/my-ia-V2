"""Add system_config table

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
Create Date: 2025-12-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7g8h9i0'
down_revision: Union[str, None] = 'c4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creer la table system_configs
    op.create_table(
        'system_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('value_type', sa.String(20), server_default='string', nullable=False),
        sa.Column('category', sa.String(50), server_default='general', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_sensitive', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('key')
    )
    op.create_index('ix_system_configs_key', 'system_configs', ['key'])
    op.create_index('ix_system_configs_category', 'system_configs', ['category'])

    # Inserer les valeurs par defaut pour le storage
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('storage.allowed_mime_types',
         'application/pdf,text/plain,text/csv,text/markdown,text/html,application/json,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/msword,application/vnd.ms-excel,application/vnd.ms-powerpoint,image/png,image/jpeg,image/gif,image/webp',
         'list', 'storage', 'Types MIME autorisés pour l''upload de documents (séparés par des virgules)'),
        ('storage.blocked_extensions',
         '.exe,.bat,.sh,.cmd,.ps1,.dll,.so,.bin',
         'list', 'storage', 'Extensions de fichiers bloqués (séparés par des virgules)'),
        ('storage.max_file_size_mb',
         '50',
         'int', 'storage', 'Taille maximale par fichier en Mo'),
        ('storage.default_quota_mb',
         '100',
         'int', 'storage', 'Quota de stockage par défaut par utilisateur en Mo'),
        ('rag.default_top_k',
         '4',
         'int', 'rag', 'Nombre de documents retournés par défaut pour le RAG'),
        ('rag.embedding_model',
         'nomic-embed-text',
         'string', 'rag', 'Modèle d''embedding utilisé'),
        ('rag.chunk_size',
         '1000',
         'int', 'rag', 'Taille des chunks pour le découpage des documents'),
        ('rag.chunk_overlap',
         '200',
         'int', 'rag', 'Chevauchement entre les chunks')
    """)


def downgrade() -> None:
    op.drop_index('ix_system_configs_category', 'system_configs')
    op.drop_index('ix_system_configs_key', 'system_configs')
    op.drop_table('system_configs')
