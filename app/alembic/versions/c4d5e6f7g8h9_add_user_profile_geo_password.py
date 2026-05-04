"""Add user profile fields, geo tables, password policy

Ajoute:
- Champs de profil utilisateur (chiffres + index de recherche)
- Tables geographiques (countries, cities)
- Tables politique mot de passe (password_policies, password_history)
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c4d5e6f7g8h9'
down_revision = 'eaf9d0f30976'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === 1. Tables geographiques (doivent etre creees AVANT les FK dans users) ===

    # Table des pays
    op.create_table('countries',
        sa.Column('code', sa.String(2), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('flag', sa.String(10), nullable=False),
        sa.Column('phone_prefix', sa.String(5), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='999'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('code')
    )

    # Insertion IMMEDIATE des pays (AVANT les FK sur users)
    op.execute("""
        INSERT INTO countries (code, name, flag, phone_prefix, is_active, display_order) VALUES
        ('FR', 'France', E'\U0001F1EB\U0001F1F7', '+33', true, 1),
        ('BE', 'Belgique', E'\U0001F1E7\U0001F1EA', '+32', true, 2),
        ('CH', 'Suisse', E'\U0001F1E8\U0001F1ED', '+41', true, 3),
        ('LU', 'Luxembourg', E'\U0001F1F1\U0001F1FA', '+352', true, 4),
        ('MC', 'Monaco', E'\U0001F1F2\U0001F1E8', '+377', true, 5),
        ('DE', 'Allemagne', E'\U0001F1E9\U0001F1EA', '+49', true, 10),
        ('IT', 'Italie', E'\U0001F1EE\U0001F1F9', '+39', true, 11),
        ('ES', 'Espagne', E'\U0001F1EA\U0001F1F8', '+34', true, 12),
        ('PT', 'Portugal', E'\U0001F1F5\U0001F1F9', '+351', true, 13),
        ('GB', 'Royaume-Uni', E'\U0001F1EC\U0001F1E7', '+44', true, 14),
        ('NL', 'Pays-Bas', E'\U0001F1F3\U0001F1F1', '+31', true, 15),
        ('AT', 'Autriche', E'\U0001F1E6\U0001F1F9', '+43', true, 16),
        ('IE', 'Irlande', E'\U0001F1EE\U0001F1EA', '+353', true, 17),
        ('US', 'Etats-Unis', E'\U0001F1FA\U0001F1F8', '+1', true, 20),
        ('CA', 'Canada', E'\U0001F1E8\U0001F1E6', '+1', true, 21)
    """)

    # Table des villes
    op.create_table('cities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('postal_code', sa.String(10), nullable=False),
        sa.Column('country_code', sa.String(2), nullable=False),
        sa.Column('department_code', sa.String(10), nullable=True),
        sa.Column('department_name', sa.String(100), nullable=True),
        sa.Column('region_name', sa.String(100), nullable=True),
        sa.Column('latitude', sa.Numeric(10, 8), nullable=True),
        sa.Column('longitude', sa.Numeric(11, 8), nullable=True),
        sa.Column('population', sa.Integer(), nullable=True),
        sa.Column('search_name', sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(['country_code'], ['countries.code']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cities_search_name', 'cities', ['search_name'], unique=False)
    op.create_index('ix_cities_postal_code', 'cities', ['postal_code', 'country_code'], unique=False)

    # === 2. Tables politique mot de passe ===

    op.create_table('password_policies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('min_length', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('max_length', sa.Integer(), nullable=False, server_default='128'),
        sa.Column('require_uppercase', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('require_lowercase', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('require_digit', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('require_special', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('special_characters', sa.String(50), nullable=False, server_default="'!@#$%^&*()_+-=[]{}|;:,.<>?'"),
        sa.Column('expire_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('history_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_failed_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('lockout_duration_minutes', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Politique par defaut
    op.execute("""
        INSERT INTO password_policies (name, min_length, max_length, require_uppercase, require_lowercase, require_digit, require_special, special_characters, expire_days, history_count, max_failed_attempts, lockout_duration_minutes, is_active)
        VALUES ('default', 8, 128, true, true, true, true, '!@#$%^&*()_+-=[]{}|;:,.<>?', 0, 0, 5, 30, true)
    """)

    op.create_table('password_history',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('hashed_password', sa.String(1024), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_password_history_user_id', 'password_history', ['user_id', 'created_at'], unique=False)

    # === 3. Ajout des champs profil dans users ===

    # Champs chiffres PII
    op.add_column('users', sa.Column('first_name', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('first_name_search', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('last_name_search', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('phone', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('phone_blind_index', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('address_line1', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('address_line2', sa.Text(), nullable=True))

    # References geographiques (sans valeur par defaut pour eviter les problemes FK)
    op.add_column('users', sa.Column('city_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('country_code', sa.String(2), nullable=True))

    # Index pour recherche
    op.create_index('ix_users_phone_blind_index', 'users', ['phone_blind_index'], unique=False)

    # Foreign keys
    op.create_foreign_key('fk_users_city_id', 'users', 'cities', ['city_id'], ['id'])
    op.create_foreign_key('fk_users_country_code', 'users', 'countries', ['country_code'], ['code'])

    # Suppression de l'ancien champ full_name (remplace par first_name + last_name)
    op.drop_column('users', 'full_name')


def downgrade() -> None:
    # Suppression des FK users
    op.drop_constraint('fk_users_country_code', 'users', type_='foreignkey')
    op.drop_constraint('fk_users_city_id', 'users', type_='foreignkey')

    # Suppression index
    op.drop_index('ix_users_phone_blind_index', table_name='users')

    # Suppression colonnes users
    op.drop_column('users', 'country_code')
    op.drop_column('users', 'city_id')
    op.drop_column('users', 'address_line2')
    op.drop_column('users', 'address_line1')
    op.drop_column('users', 'phone_blind_index')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'last_name_search')
    op.drop_column('users', 'last_name')
    op.drop_column('users', 'first_name_search')
    op.drop_column('users', 'first_name')

    # Restaure full_name
    op.add_column('users', sa.Column('full_name', sa.String(255), nullable=True))

    # Suppression tables
    op.drop_index('ix_password_history_user_id', table_name='password_history')
    op.drop_table('password_history')
    op.drop_table('password_policies')

    op.drop_index('ix_cities_postal_code', table_name='cities')
    op.drop_index('ix_cities_search_name', table_name='cities')
    op.drop_table('cities')
    op.drop_table('countries')
