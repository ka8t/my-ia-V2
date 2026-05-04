"""corpus_documents many to many

Revision ID: 20260221_1945
Revises: 20260221_1520
Create Date: 2026-02-21 19:45:00.000000

Migration vers relation N-N entre Documents et Corpus via table pivot corpus_documents.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260221_1945'
down_revision = '20260221_1520'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. Créer la nouvelle table corpus_documents
    op.create_table(
        'corpus_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('corpus_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('priority', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['corpus_id'], ['corpus.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('corpus_id', 'document_id', name='uq_corpus_document')
    )
    op.create_index('idx_corpus_documents_corpus', 'corpus_documents', ['corpus_id'])
    op.create_index('idx_corpus_documents_document', 'corpus_documents', ['document_id'])

    # 2. Vérifier si la colonne corpus_id existe avant de migrer
    result = conn.execute(sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'corpus_id'
    """))
    if result.fetchone():
        # Migrer les données existantes (documents avec corpus_id)
        conn.execute(sa.text("""
            INSERT INTO corpus_documents (id, corpus_id, document_id, priority, created_at)
            SELECT gen_random_uuid(), corpus_id, id, 0, NOW()
            FROM documents WHERE corpus_id IS NOT NULL
        """))

        # 3. Supprimer la contrainte existante si elle existe
        constraint_result = conn.execute(sa.text("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name = 'documents' AND constraint_name = 'ck_document_corpus_or_collection'
        """))
        if constraint_result.fetchone():
            op.drop_constraint('ck_document_corpus_or_collection', 'documents')

        # 4. Supprimer la colonne corpus_id
        op.drop_column('documents', 'corpus_id')


def downgrade():
    # 1. Recréer la colonne corpus_id
    op.add_column('documents', sa.Column(
        'corpus_id', postgresql.UUID(as_uuid=True), nullable=True
    ))
    op.create_index('ix_documents_corpus_id', 'documents', ['corpus_id'])
    op.create_foreign_key(
        'fk_documents_corpus_id', 'documents', 'corpus',
        ['corpus_id'], ['id'], ondelete='CASCADE'
    )

    # 2. Restaurer les données (prendre le premier corpus pour chaque document)
    op.execute("""
        UPDATE documents d
        SET corpus_id = (
            SELECT corpus_id FROM corpus_documents cd
            WHERE cd.document_id = d.id
            ORDER BY cd.priority, cd.created_at
            LIMIT 1
        )
    """)

    # 3. Recréer la contrainte (optionnel, peut ne pas être nécessaire)
    # op.create_check_constraint(
    #     'ck_document_corpus_or_collection',
    #     'documents',
    #     '(corpus_id IS NOT NULL AND collection_id IS NULL) OR '
    #     '(corpus_id IS NULL AND collection_id IS NOT NULL)'
    # )

    # 4. Supprimer la table corpus_documents
    op.drop_table('corpus_documents')
