"""Add missing audit actions

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-01-14

Ajoute toutes les actions d'audit manquantes qui sont appelees dans le code
mais n'existent pas en base de donnees. Cela corrige le probleme de
defaillance silencieuse du systeme d'audit.

Categories d'actions ajoutees:
- Admin users: creation, modification, suppression, activation
- Bulk operations: actions groupees sur users/documents/conversations
- Password policy: CRUD politiques de mot de passe
- Config: rechargement, creation, suppression
- Export: exports de donnees
- CRUD Admin: roles, audit_actions, resource_types, conversation_modes
- User: login_success, password_reset_requested
- Sessions: revocation de sessions
- Documents: upload, deindexation, reindexation, visibilite
- Conversations: archivage
- Messages: suppression definitive, restauration
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'm4n5o6p7q8r9'
down_revision = 'l3m4n5o6p7q8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ajoute les actions d'audit manquantes"""
    op.execute("""
        INSERT INTO audit_actions (name, display_name, severity) VALUES
            -- === Admin User Operations ===
            ('admin_user_created', 'Utilisateur créé (admin)', 'info'),
            ('admin_user_updated', 'Utilisateur modifié (admin)', 'info'),
            ('admin_user_deleted', 'Utilisateur supprimé (admin)', 'warning'),
            ('user_role_changed', 'Rôle utilisateur modifié', 'warning'),
            ('password_reset_by_admin', 'Mot de passe réinitialisé par admin', 'warning'),
            ('user_activated', 'Utilisateur activé', 'info'),
            ('user_deactivated', 'Utilisateur désactivé', 'warning'),

            -- === Bulk Operations ===
            ('bulk_users_activated', 'Activation groupée utilisateurs', 'info'),
            ('bulk_users_deactivated', 'Désactivation groupée utilisateurs', 'warning'),
            ('bulk_users_deleted', 'Suppression groupée utilisateurs', 'warning'),
            ('bulk_users_role_changed', 'Changement rôle groupé', 'warning'),
            ('bulk_conversations_deleted', 'Suppression groupée conversations', 'warning'),
            ('bulk_documents_deleted', 'Suppression groupée documents', 'warning'),
            ('bulk_sessions_revoked', 'Révocation groupée sessions', 'warning'),

            -- === Password Policy ===
            ('password_policy_created', 'Politique mot de passe créée', 'info'),
            ('password_policy_updated', 'Politique mot de passe modifiée', 'info'),
            ('password_policy_deleted', 'Politique mot de passe supprimée', 'warning'),

            -- === Config ===
            ('config_reloaded', 'Configuration rechargée', 'info'),
            ('config_created', 'Configuration créée', 'info'),
            ('config_deleted', 'Configuration supprimée', 'warning'),

            -- === Export ===
            ('data_exported', 'Données exportées', 'info'),
            ('conversation_exported', 'Conversation exportée', 'info'),

            -- === CRUD Admin - Roles ===
            ('role_created', 'Rôle créé', 'info'),
            ('role_updated', 'Rôle modifié', 'info'),
            ('role_deleted', 'Rôle supprimé', 'warning'),

            -- === CRUD Admin - Audit Actions ===
            ('audit_action_created', 'Action audit créée', 'info'),
            ('audit_action_updated', 'Action audit modifiée', 'info'),
            ('audit_action_deleted', 'Action audit supprimée', 'warning'),

            -- === CRUD Admin - Resource Types ===
            ('resource_type_created', 'Type ressource créé', 'info'),
            ('resource_type_updated', 'Type ressource modifié', 'info'),
            ('resource_type_deleted', 'Type ressource supprimé', 'warning'),

            -- === CRUD Admin - Conversation Modes ===
            ('conversation_mode_created', 'Mode conversation créé', 'info'),
            ('conversation_mode_updated', 'Mode conversation modifié', 'info'),
            ('conversation_mode_deleted', 'Mode conversation supprimé', 'warning'),

            -- === User Authentication ===
            ('login_success', 'Connexion réussie', 'info'),
            ('password_reset_requested', 'Réinitialisation demandée', 'info'),

            -- === Sessions ===
            ('all_sessions_revoked', 'Toutes sessions révoquées', 'warning'),

            -- === Documents ===
            ('document_uploaded', 'Document uploadé', 'info'),
            ('document_deindexed', 'Document désindexé', 'info'),
            ('document_reindexed', 'Document réindexé', 'info'),
            ('document_visibility_updated', 'Visibilité document modifiée', 'info'),

            -- === Conversations ===
            ('conversation_archived', 'Conversation archivée', 'info'),
            ('conversation_unarchived', 'Conversation désarchivée', 'info'),
            ('conversation_updated', 'Conversation modifiée', 'info'),

            -- === Messages ===
            ('message_created', 'Message créé', 'info'),
            ('message_deleted', 'Message supprimé', 'info'),
            ('message_hard_deleted', 'Message supprimé définitivement', 'warning'),
            ('message_restored', 'Message restauré', 'info'),

            -- === Documents (user actions) ===
            ('document_updated', 'Document modifié', 'info'),

            -- === User Profile ===
            ('preferences_updated', 'Préférences modifiées', 'info'),
            ('preferences_updated_by_admin', 'Préférences modifiées par admin', 'info'),

            -- === User Conversations ===
            ('user_conversations_deleted', 'Conversations utilisateur supprimées', 'warning')

        ON CONFLICT (name) DO NOTHING;
    """)


def downgrade() -> None:
    """Supprime les actions d'audit ajoutees"""
    op.execute("""
        DELETE FROM audit_actions WHERE name IN (
            'admin_user_created',
            'admin_user_updated',
            'admin_user_deleted',
            'user_role_changed',
            'password_reset_by_admin',
            'user_activated',
            'user_deactivated',
            'bulk_users_activated',
            'bulk_users_deactivated',
            'bulk_users_deleted',
            'bulk_users_role_changed',
            'bulk_conversations_deleted',
            'bulk_documents_deleted',
            'bulk_sessions_revoked',
            'password_policy_created',
            'password_policy_updated',
            'password_policy_deleted',
            'config_reloaded',
            'config_created',
            'config_deleted',
            'data_exported',
            'conversation_exported',
            'role_created',
            'role_updated',
            'role_deleted',
            'audit_action_created',
            'audit_action_updated',
            'audit_action_deleted',
            'resource_type_created',
            'resource_type_updated',
            'resource_type_deleted',
            'conversation_mode_created',
            'conversation_mode_updated',
            'conversation_mode_deleted',
            'login_success',
            'password_reset_requested',
            'all_sessions_revoked',
            'document_uploaded',
            'document_deindexed',
            'document_reindexed',
            'document_visibility_updated',
            'document_updated',
            'conversation_archived',
            'conversation_unarchived',
            'conversation_updated',
            'message_created',
            'message_deleted',
            'message_hard_deleted',
            'message_restored',
            'preferences_updated',
            'preferences_updated_by_admin',
            'user_conversations_deleted'
        );
    """)
