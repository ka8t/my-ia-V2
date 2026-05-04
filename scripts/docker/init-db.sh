#!/bin/bash
set -e

# =============================================================================
# Script d'initialisation PostgreSQL - MY-IA
# =============================================================================
# Ce script est exécuté automatiquement au premier démarrage du container
# PostgreSQL (via docker-entrypoint-initdb.d/).
#
# Il crée les utilisateurs et bases de données nécessaires à l'application.
# =============================================================================

# Se connecter en tant que super-utilisateur pour créer les autres rôles et bases
export PGPASSWORD=$POSTGRES_PASSWORD

# Récupérer le hostname du container
CONTAINER_HOST=$(hostname)

# Fonction pour créer un utilisateur et une base de données
# Prend en paramètres : USER, PASSWORD, DATABASE
create_db_and_user() {
  local user=$1
  local password=$2
  local db=$3

  # Vérifie si le mot de passe est 'none' ou vide, et ajuste la commande SQL
  # NOTE: Un mot de passe vide est une mauvaise pratique, mais géré ici pour la flexibilité en dev
  if [[ -z "$password" || "$password" == "none" ]]; then
    password_clause="WITH PASSWORD NULL" # Crée un rôle sans mot de passe, désactivant le login par mot de passe
    echo "Creating user '$user' with a NULL password (login will likely fail without other auth methods)."
  else
    password_clause="WITH PASSWORD '$password'"
    echo "Creating user '$user' with a specified password."
  fi

  # --- Convertir en minuscules pour PostgreSQL ---
  # PostgreSQL convertit les identifiants non-quotés en minuscules
  local user_lower=$(echo "$user" | tr '[:upper:]' '[:lower:]')
  local db_lower=$(echo "$db" | tr '[:upper:]' '[:lower:]')

  echo "Normalized names: user='$user_lower', db='$db_lower'"

  # --- Etape 1: Créer l'utilisateur ---
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
      DO \$\$
      BEGIN
          IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = '$user_lower') THEN
              CREATE USER $user_lower $password_clause;
              RAISE NOTICE 'User $user_lower created';
          ELSE
              RAISE NOTICE 'User $user_lower already exists';
          END IF;
      END
      \$\$;
EOSQL

  # --- Etape 2: Créer la base de données (si n'existe pas) ---
  if ! psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_lower'" | grep -q 1; then
      echo "Creating database '$db_lower' with owner '$user_lower'..."
      psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE $db_lower OWNER $user_lower;"
  else
      echo "Database '$db_lower' already exists."
  fi

  # --- Etape 3: Accorder les privilèges sur la base ---
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
      GRANT ALL PRIVILEGES ON DATABASE $db_lower TO $user_lower;
EOSQL

  # --- Etape 4: PostgreSQL 15+ - Accorder les droits sur le schéma public ---
  # (doit être exécuté EN ÉTANT CONNECTÉ à la base cible)
  echo "Granting schema permissions on '$db_lower'..."
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db_lower" <<-EOSQL
      -- Accorder les droits sur le schéma public (requis depuis PostgreSQL 15)
      GRANT ALL ON SCHEMA public TO $user_lower;
      GRANT CREATE ON SCHEMA public TO $user_lower;

      -- Droits par défaut sur les futurs objets créés dans ce schéma
      ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $user_lower;
      ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $user_lower;
      ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO $user_lower;
EOSQL

  echo "Database '$db_lower' configured successfully."
}

# --- Création des bases et utilisateurs ---

# 1. Pour N8N (Workflow Automation)
if [[ -n "$N8N_DB_USER" && -n "$N8N_DB_NAME" ]]; then
  echo "--- Provisioning N8N Database ---"
  create_db_and_user "$N8N_DB_USER" "$N8N_DB_PASSWORD" "$N8N_DB_NAME"
  echo "N8N database and user provisioned."
fi

# 2. Pour l'application MY-IA
if [[ -n "$APP_DB_USER" && -n "$APP_DB_NAME" ]]; then
  echo "--- Provisioning Application Database ---"
  create_db_and_user "$APP_DB_USER" "$APP_DB_PASSWORD" "$APP_DB_NAME"
  echo "Application database and user provisioned."
fi

# =============================================================================
# RÉSUMÉ DES ACCÈS CRÉÉS
# =============================================================================
echo ""
echo "============================================================================="
echo " POSTGRESQL - INITIALISATION TERMINÉE"
echo "============================================================================="
echo ""
echo " Container Host : $CONTAINER_HOST"
echo " Port interne   : 5432"
echo ""
echo "-----------------------------------------------------------------------------"
echo " SUPERUSER (Administration uniquement)"
echo "-----------------------------------------------------------------------------"
echo " Utilisateur    : $POSTGRES_USER"
echo " Mot de passe   : ********"
echo " Base           : postgres (base système)"
echo " Usage          : Maintenance, création de bases, backups"
echo " Connexion      : psql -U $POSTGRES_USER -d postgres"
echo ""
echo "-----------------------------------------------------------------------------"
echo " APPLICATION (Utilisé par FastAPI)"
echo "-----------------------------------------------------------------------------"
if [[ -n "$APP_DB_USER" && -n "$APP_DB_NAME" ]]; then
echo " Utilisateur    : $APP_DB_USER"
echo " Mot de passe   : ********"
echo " Base           : $APP_DB_NAME"
echo " Propriétaire   : Oui (OWNER)"
echo " Usage          : API Backend, migrations Alembic, CRUD"
echo " Connexion      : psql -U $APP_DB_USER -d $APP_DB_NAME"
echo ""
echo " Droits accordés :"
echo "   - ALL PRIVILEGES ON DATABASE  : Accès complet à la base"
echo "   - ALL ON SCHEMA public        : Lecture/écriture schéma public"
echo "   - CREATE ON SCHEMA public     : Création de tables/index"
echo "   - DEFAULT PRIVILEGES TABLES   : Droits auto sur futures tables"
echo "   - DEFAULT PRIVILEGES SEQUENCES: Droits auto sur futures séquences"
echo "   - DEFAULT PRIVILEGES FUNCTIONS: Droits auto sur futures fonctions"
else
echo " [Non configuré - variables APP_DB_* manquantes]"
fi
echo ""
echo "-----------------------------------------------------------------------------"
echo " CHAÎNES DE CONNEXION"
echo "-----------------------------------------------------------------------------"
echo " Depuis Docker (interne) :"
echo "   postgresql://$APP_DB_USER:****@postgres:5432/$APP_DB_NAME"
echo ""
echo " Depuis l'hôte (externe) :"
echo "   postgresql://$APP_DB_USER:****@localhost:5432/$APP_DB_NAME"
echo ""
echo "============================================================================="
echo ""
