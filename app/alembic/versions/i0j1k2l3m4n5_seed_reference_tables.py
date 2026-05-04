"""Seed reference tables with initial data

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2025-12-28

Initialise les tables de reference avec les donnees obligatoires :
- roles: admin, user, contributor (validator deja ajoute)
- conversation_modes: chatbot, assistant
- resource_types: user, document, conversation, message, collection
- audit_actions: actions de base (login, logout, etc.)
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'i0j1k2l3m4n5'
down_revision = 'h9i0j1k2l3m4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === 1. Roles de base ===
    # Note: validator (id=4) est deja insere par g8h9i0j1k2l3
    op.execute("""
        INSERT INTO roles (id, name, display_name, description) VALUES
            (1, 'admin', 'Administrateur', 'Acces complet a toutes les fonctionnalites'),
            (2, 'user', 'Utilisateur', 'Utilisateur standard avec acces limite'),
            (3, 'contributor', 'Contributeur', 'Peut uploader des documents publics')
        ON CONFLICT (id) DO NOTHING;
    """)
    # Resynchroniser la sequence apres insertion avec IDs explicites
    op.execute("SELECT setval('roles_id_seq', (SELECT COALESCE(MAX(id), 1) FROM roles));")

    # === 2. Modes de conversation ===
    op.execute("""
        INSERT INTO conversation_modes (id, name, display_name, description, system_prompt) VALUES
            (1, 'chatbot', 'Chatbot', 'Mode conversationnel standard',
             'Tu es un assistant IA serviable et precis. Reponds aux questions en te basant sur le contexte fourni.'),
            (2, 'assistant', 'Assistant', 'Mode oriente taches',
             'Tu es un assistant oriente taches. Aide l''utilisateur a accomplir ses objectifs de maniere efficace.')
        ON CONFLICT (id) DO NOTHING;
    """)
    op.execute("SELECT setval('conversation_modes_id_seq', (SELECT COALESCE(MAX(id), 1) FROM conversation_modes));")

    # === 3. Types de ressources (pour audit) ===
    op.execute("""
        INSERT INTO resource_types (id, name, display_name) VALUES
            (1, 'user', 'Utilisateur'),
            (2, 'document', 'Document'),
            (3, 'conversation', 'Conversation'),
            (4, 'message', 'Message'),
            (5, 'collection', 'Collection'),
            (6, 'role', 'Role'),
            (7, 'system_config', 'Configuration systeme')
        ON CONFLICT (id) DO NOTHING;
    """)
    op.execute("SELECT setval('resource_types_id_seq', (SELECT COALESCE(MAX(id), 1) FROM resource_types));")

    # === 4. Actions d'audit de base ===
    # Note: actions de validation deja inserees par h9i0j1k2l3m4
    op.execute("""
        INSERT INTO audit_actions (name, display_name, severity) VALUES
            ('login', 'Connexion', 'info'),
            ('logout', 'Deconnexion', 'info'),
            ('login_failed', 'Tentative de connexion echouee', 'warning'),
            ('password_changed', 'Mot de passe modifie', 'info'),
            ('password_reset', 'Reinitialisation mot de passe', 'info'),
            ('profile_updated', 'Profil mis a jour', 'info'),
            ('document_created', 'Document cree', 'info'),
            ('document_deleted', 'Document supprime', 'info'),
            ('document_indexed', 'Document indexe', 'info'),
            ('conversation_created', 'Conversation creee', 'info'),
            ('conversation_deleted', 'Conversation supprimee', 'info'),
            ('user_created', 'Utilisateur cree', 'info'),
            ('user_updated', 'Utilisateur modifie', 'info'),
            ('user_deleted', 'Utilisateur supprime', 'warning'),
            ('role_changed', 'Role modifie', 'warning'),
            ('collection_created', 'Collection creee', 'info'),
            ('collection_deleted', 'Collection supprimee', 'warning'),
            ('config_updated', 'Configuration modifiee', 'info')
        ON CONFLICT (name) DO NOTHING;
    """)


def downgrade() -> None:
    # Supprimer les donnees inserees (dans l'ordre inverse des FK)
    op.execute("""
        DELETE FROM audit_actions WHERE name IN (
            'login', 'logout', 'login_failed', 'password_changed',
            'password_reset', 'profile_updated', 'document_created',
            'document_deleted', 'document_indexed', 'conversation_created',
            'conversation_deleted', 'user_created', 'user_updated',
            'user_deleted', 'role_changed', 'collection_created',
            'collection_deleted', 'config_updated'
        );
    """)

    op.execute("DELETE FROM resource_types WHERE id BETWEEN 1 AND 7;")
    op.execute("DELETE FROM conversation_modes WHERE id IN (1, 2);")
    op.execute("DELETE FROM roles WHERE id IN (1, 2, 3);")
