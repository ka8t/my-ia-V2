#!/bin/bash
# =============================================================================
# MY-IA - Fonctions d'installation bare-metal (sans Docker)
# =============================================================================
# Ce fichier contient les fonctions pour installer MY-IA nativement
# sur un serveur Linux ou macOS, sans Docker.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/prereqs.sh"
#   source "$SCRIPT_DIR/lib/baremetal.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#   - prereqs.sh doit etre source avant ce fichier (OS_TYPE, OS_FAMILY, ARCH)
#
# =============================================================================

# =============================================================================
# VARIABLES DE CONFIGURATION BARE-METAL
# =============================================================================

# Repertoire d'installation (Linux: /opt/myia, macOS: repertoire courant)
INSTALL_DIR=""
SERVICE_USER=""
SERVICE_GROUP=""

# =============================================================================
# INITIALISATION DES VARIABLES BARE-METAL
# =============================================================================
# Configure les variables selon l'OS detecte.
#
# Usage:
#   init_baremetal_vars "/path/to/project"
#
# Parametres:
#   $1 - Chemin du projet source
# =============================================================================

init_baremetal_vars() {
    local project_root="$1"

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        # macOS: utiliser le repertoire courant, user courant
        INSTALL_DIR="$project_root"
        SERVICE_USER="$(whoami)"
        SERVICE_GROUP="staff"
    else
        # Linux: /opt/myia, user systeme dedie
        INSTALL_DIR="/opt/myia"
        SERVICE_USER="myia"
        SERVICE_GROUP="myia"
    fi

    export INSTALL_DIR SERVICE_USER SERVICE_GROUP
    log_debug "[init_baremetal_vars] INSTALL_DIR=$INSTALL_DIR SERVICE_USER=$SERVICE_USER"
}

# =============================================================================
# CREATION DE L'UTILISATEUR SYSTEME
# =============================================================================
# Cree l'utilisateur systeme 'myia' et le repertoire d'installation.
# Sur macOS, utilise l'utilisateur courant.
#
# Usage:
#   create_system_user
# =============================================================================

create_system_user() {
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        log_info "macOS: utilisation de l'utilisateur courant ($(whoami))"
        return 0
    fi

    log_step "Creation de l'utilisateur systeme..."

    if id "$SERVICE_USER" &> /dev/null; then
        log_success "Utilisateur '$SERVICE_USER' existe deja"
    else
        sudo useradd --system --create-home --home-dir "$INSTALL_DIR" \
            --shell /bin/bash "$SERVICE_USER"
        log_success "Utilisateur '$SERVICE_USER' cree"
    fi

    # Creer les repertoires necessaires
    sudo mkdir -p "$INSTALL_DIR"/{app,data/chroma,venv,logs}
    sudo chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"

    log_success "Repertoire $INSTALL_DIR configure"
}

# =============================================================================
# COPIE DES FICHIERS DE L'APPLICATION
# =============================================================================
# Copie les fichiers du projet vers le repertoire d'installation.
# Sur macOS, pas de copie necessaire (repertoire courant).
#
# Usage:
#   copy_application_files "/path/to/project"
# =============================================================================

copy_application_files() {
    local project_root="$1"

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        log_info "macOS: fichiers deja en place dans $project_root"
        return 0
    fi

    if [[ "$project_root" == "$INSTALL_DIR" || "$project_root" == "$INSTALL_DIR/app" ]]; then
        log_info "Fichiers deja dans le repertoire d'installation"
        return 0
    fi

    log_step "Copie des fichiers de l'application..."

    # Copier les dossiers essentiels
    local dirs_to_copy=("app" "scripts" "static-datas" "UI-FRONT" "UI-BACK" "UI-SHARED"
                        "alembic.ini" "requirements.txt" ".env.example")

    for item in "${dirs_to_copy[@]}"; do
        if [[ -e "$project_root/$item" ]]; then
            sudo cp -a "$project_root/$item" "$INSTALL_DIR/app/"
            log_debug "[copy_application_files] Copie: $item"
        fi
    done

    sudo chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/app"
    log_success "Fichiers copies vers $INSTALL_DIR/app"
}

# =============================================================================
# INSTALLATION DE POSTGRESQL
# =============================================================================
# Installe et configure PostgreSQL.
#
# Usage:
#   install_postgresql
# =============================================================================

install_postgresql() {
    log_step "Configuration de PostgreSQL..."

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        _install_postgresql_macos
    else
        _install_postgresql_linux
    fi

    # Creer la base et l'utilisateur applicatif
    _setup_postgresql_database
}

_install_postgresql_macos() {
    if command -v psql &> /dev/null; then
        log_success "PostgreSQL deja installe"
    else
        log_info "Installation de PostgreSQL via Homebrew..."
        brew install postgresql@15
    fi

    # Demarrer le service
    if brew services list 2>/dev/null | grep -q "postgresql.*started"; then
        log_success "PostgreSQL deja demarre"
    else
        brew services start postgresql@15 2>/dev/null || brew services start postgresql 2>/dev/null
        sleep 3
        log_success "PostgreSQL demarre via brew services"
    fi
}

_install_postgresql_linux() {
    if command -v psql &> /dev/null; then
        log_success "PostgreSQL deja installe"
    else
        log_info "Installation de PostgreSQL..."
        case "$OS_FAMILY" in
            debian)
                sudo apt update -qq
                $PKG_INSTALL postgresql postgresql-contrib
                ;;
            rhel)
                $PKG_INSTALL postgresql-server postgresql-contrib
                sudo postgresql-setup --initdb 2>/dev/null || true
                ;;
        esac
    fi

    # Activer et demarrer
    sudo systemctl enable --now postgresql
    log_success "PostgreSQL actif"
}

_setup_postgresql_database() {
    log_info "Configuration de la base de donnees..."

    # Charger les variables d'environnement
    local pg_user="${POSTGRES_USER:-myia_postgres_admin}"
    local pg_password="${POSTGRES_PASSWORD:-changeme}"
    local app_user="${APP_DB_USER:-myia_db_user}"
    local app_password="${APP_DB_PASSWORD:-changeme}"
    local app_db="${APP_DB_NAME:-myia_db}"

    # Creer le superuser PostgreSQL si absent
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$pg_user'" 2>/dev/null | grep -q 1; then
        log_info "Role PostgreSQL '$pg_user' existe deja"
    else
        sudo -u postgres psql -c "CREATE USER $pg_user WITH SUPERUSER PASSWORD '$pg_password';" 2>/dev/null
        log_success "Role PostgreSQL '$pg_user' cree"
    fi

    # Creer l'utilisateur applicatif si absent
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$app_user'" 2>/dev/null | grep -q 1; then
        log_info "Role PostgreSQL '$app_user' existe deja"
    else
        sudo -u postgres psql -c "CREATE USER $app_user WITH PASSWORD '$app_password';" 2>/dev/null
        log_success "Role PostgreSQL '$app_user' cree"
    fi

    # Creer la base si absente
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$app_db'" 2>/dev/null | grep -q 1; then
        log_info "Base '$app_db' existe deja"
    else
        sudo -u postgres psql -c "CREATE DATABASE $app_db OWNER $app_user;" 2>/dev/null
        log_success "Base '$app_db' creee"
    fi

    # Extension uuid-ossp
    sudo -u postgres psql -d "$app_db" -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" 2>/dev/null
    log_success "Extension uuid-ossp activee"
}

# =============================================================================
# INSTALLATION D'OLLAMA
# =============================================================================
# Installe Ollama nativement.
#
# Usage:
#   install_ollama_native
# =============================================================================

install_ollama_native() {
    log_step "Configuration d'Ollama..."

    if command -v ollama &> /dev/null; then
        log_success "Ollama deja installe"
    else
        log_info "Installation d'Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        log_success "Ollama installe"
    fi

    # Demarrer Ollama
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        # Sur macOS, Ollama est une app standalone
        if pgrep -x "ollama" > /dev/null 2>&1; then
            log_success "Ollama deja en cours d'execution"
        else
            log_info "Demarrage d'Ollama..."
            ollama serve &> /dev/null &
            sleep 3
            log_success "Ollama demarre"
        fi
    else
        sudo systemctl enable --now ollama 2>/dev/null || true
        log_success "Service Ollama actif"
    fi

    # Telecharger les modeles
    local llm_model="${LLM_MODEL:-gemma2:2b}"
    local embed_model="${EMBED_MODEL:-nomic-embed-text}"

    log_info "Verification des modeles..."
    sleep 2

    if ! ollama list 2>/dev/null | grep -q "^$llm_model"; then
        log_info "Telechargement de $llm_model (peut prendre plusieurs minutes)..."
        ollama pull "$llm_model"
        log_success "Modele $llm_model telecharge"
    else
        log_success "Modele $llm_model deja present"
    fi

    if ! ollama list 2>/dev/null | grep -q "^$embed_model"; then
        log_info "Telechargement de $embed_model..."
        ollama pull "$embed_model"
        log_success "Modele $embed_model telecharge"
    else
        log_success "Modele $embed_model deja present"
    fi
}

# =============================================================================
# INSTALLATION DE CHROMADB
# =============================================================================
# Installe ChromaDB via pip.
#
# Usage:
#   install_chromadb_native
# =============================================================================

install_chromadb_native() {
    log_step "Configuration de ChromaDB..."

    local chroma_data_dir="$INSTALL_DIR/data/chroma"

    # Creer le repertoire de donnees
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        mkdir -p "$chroma_data_dir"
    else
        sudo mkdir -p "$chroma_data_dir"
        sudo chown -R "$SERVICE_USER:$SERVICE_GROUP" "$chroma_data_dir"
    fi

    log_success "Repertoire ChromaDB: $chroma_data_dir"
    # ChromaDB sera installe via requirements.txt dans le venv
}

# =============================================================================
# CONFIGURATION DE L'ENVIRONNEMENT PYTHON
# =============================================================================
# Cree le virtualenv et installe les dependances.
#
# Usage:
#   setup_python_venv "/path/to/project"
# =============================================================================

setup_python_venv() {
    local project_root="$1"
    local venv_dir="$INSTALL_DIR/venv"
    local requirements="$project_root/requirements.txt"

    log_step "Configuration de l'environnement Python..."

    if [[ ! -f "$requirements" ]]; then
        # Essayer dans le repertoire d'installation
        requirements="$INSTALL_DIR/app/requirements.txt"
    fi

    if [[ ! -f "$requirements" ]]; then
        log_error "Fichier requirements.txt non trouve"
        return 1
    fi

    # Creer le virtualenv si absent
    if [[ ! -d "$venv_dir" ]]; then
        log_info "Creation du virtualenv..."
        if [[ "$OS_FAMILY" == "darwin" ]]; then
            python3 -m venv "$venv_dir"
        else
            sudo -u "$SERVICE_USER" python3 -m venv "$venv_dir"
        fi
        log_success "Virtualenv cree: $venv_dir"
    else
        log_info "Virtualenv existant: $venv_dir"
    fi

    # Installer les dependances
    log_info "Installation des dependances Python..."
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        "$venv_dir/bin/pip" install --upgrade pip
        "$venv_dir/bin/pip" install -r "$requirements"
    else
        sudo -u "$SERVICE_USER" "$venv_dir/bin/pip" install --upgrade pip
        sudo -u "$SERVICE_USER" "$venv_dir/bin/pip" install -r "$requirements"
    fi

    log_success "Dependances Python installees"
}

# =============================================================================
# ADAPTATION DU .ENV POUR BARE-METAL
# =============================================================================
# Post-traite le .env pour remplacer les hostnames Docker par localhost.
#
# Usage:
#   generate_baremetal_env "/path/to/.env"
# =============================================================================

generate_baremetal_env() {
    local env_file="$1"

    log_step "Adaptation du .env pour bare-metal..."

    if [[ ! -f "$env_file" ]]; then
        log_error "Fichier .env non trouve: $env_file"
        return 1
    fi

    # Remplacer les hostnames Docker par localhost
    local postgres_port="${POSTGRES_PORT:-5432}"
    local chroma_port="${CHROMA_PORT:-8000}"

    # DATABASE_URL: remplacer postgres:5432 par localhost:PORT
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        sed -i '' "s|@postgres:5432/|@localhost:${postgres_port}/|g" "$env_file"
        sed -i '' "s|@postgres:${postgres_port}/|@localhost:${postgres_port}/|g" "$env_file"
        sed -i '' "s|CHROMA_HOST=chroma|CHROMA_HOST=localhost|g" "$env_file"
        sed -i '' "s|OLLAMA_HOST=ollama|OLLAMA_HOST=localhost|g" "$env_file"
    else
        sed -i "s|@postgres:5432/|@localhost:${postgres_port}/|g" "$env_file"
        sed -i "s|@postgres:${postgres_port}/|@localhost:${postgres_port}/|g" "$env_file"
        sed -i "s|CHROMA_HOST=chroma|CHROMA_HOST=localhost|g" "$env_file"
        sed -i "s|OLLAMA_HOST=ollama|OLLAMA_HOST=localhost|g" "$env_file"
    fi

    # Adapter les chemins pour bare-metal
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        sed -i '' "s|DATASETS_DIR=/code/datasets|DATASETS_DIR=${INSTALL_DIR}/datasets|g" "$env_file"
        sed -i '' "s|STATIC_DATA_DIR=/code/static-datas|STATIC_DATA_DIR=${INSTALL_DIR}/static-datas|g" "$env_file"
    else
        sed -i "s|DATASETS_DIR=/code/datasets|DATASETS_DIR=${INSTALL_DIR}/app/datasets|g" "$env_file"
        sed -i "s|STATIC_DATA_DIR=/code/static-datas|STATIC_DATA_DIR=${INSTALL_DIR}/app/static-datas|g" "$env_file"
    fi

    log_success ".env adapte pour bare-metal (hostnames -> localhost)"
}

# =============================================================================
# EXECUTION DES MIGRATIONS ALEMBIC
# =============================================================================
# Execute les migrations de base de donnees.
#
# Usage:
#   run_alembic_migrations "/path/to/project"
# =============================================================================

run_alembic_migrations() {
    local project_root="$1"
    local venv_dir="$INSTALL_DIR/venv"
    local work_dir="$project_root"

    if [[ "$OS_FAMILY" != "darwin" && -d "$INSTALL_DIR/app" ]]; then
        work_dir="$INSTALL_DIR/app"
    fi

    log_step "Execution des migrations Alembic..."

    # Afficher la version avant migration
    local version_before=""
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        version_before=$(cd "$work_dir" && "$venv_dir/bin/python" -m alembic current 2>/dev/null | head -1 || true)
    else
        version_before=$(sudo -u "$SERVICE_USER" bash -c "cd '$work_dir' && '$venv_dir/bin/python' -m alembic current 2>/dev/null | head -1" || true)
    fi
    if [[ -n "$version_before" ]]; then
        log_info "Version Alembic avant migration: $version_before"
    else
        log_info "Version Alembic avant migration: (aucune / base vierge)"
    fi

    # Executer les migrations
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        cd "$work_dir" && "$venv_dir/bin/python" -m alembic upgrade head
    else
        sudo -u "$SERVICE_USER" bash -c "cd '$work_dir' && '$venv_dir/bin/python' -m alembic upgrade head"
    fi

    # Afficher la version apres migration
    local version_after=""
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        version_after=$(cd "$work_dir" && "$venv_dir/bin/python" -m alembic current 2>/dev/null | head -1 || true)
    else
        version_after=$(sudo -u "$SERVICE_USER" bash -c "cd '$work_dir' && '$venv_dir/bin/python' -m alembic current 2>/dev/null | head -1" || true)
    fi
    if [[ -n "$version_after" ]]; then
        log_info "Version Alembic apres migration: $version_after"
    else
        log_warn "Impossible de lire la version Alembic apres migration"
    fi

    log_success "Migrations executees"
}

# =============================================================================
# EXECUTION DU SCRIPT DE SEED
# =============================================================================
# Execute le script de seed pour creer les donnees initiales.
#
# Usage:
#   run_seed_script "/path/to/project"
# =============================================================================

run_seed_script() {
    local project_root="$1"
    local venv_dir="$INSTALL_DIR/venv"
    local work_dir="$project_root"
    local seed_script="scripts/docker/seed.py"

    if [[ "$OS_FAMILY" != "darwin" && -d "$INSTALL_DIR/app" ]]; then
        work_dir="$INSTALL_DIR/app"
    fi

    if [[ ! -f "$work_dir/$seed_script" ]]; then
        log_warn "Script de seed non trouve: $work_dir/$seed_script"
        return 0
    fi

    log_step "Execution du script de seed..."

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        cd "$work_dir" && "$venv_dir/bin/python" "$seed_script"
    else
        sudo -u "$SERVICE_USER" bash -c "cd '$work_dir' && '$venv_dir/bin/python' '$seed_script'"
    fi

    log_success "Seed execute"
}

# =============================================================================
# SUBSTITUTION DE TEMPLATE
# =============================================================================
# Substitue les placeholders {{VAR}} dans un template par les valeurs .env.
#
# Usage:
#   generate_from_template "template.conf" "/etc/output.conf"
#
# Parametres:
#   $1 - Chemin du template source
#   $2 - Chemin du fichier de sortie
# =============================================================================

generate_from_template() {
    local template="$1"
    local output="$2"

    if [[ ! -f "$template" ]]; then
        log_error "Template non trouve: $template"
        return 1
    fi

    log_debug "[generate_from_template] $template -> $output"

    local content
    content=$(cat "$template")

    # Substituer les variables connues
    content=$(echo "$content" | sed \
        -e "s|{{APP_PORT}}|${APP_PORT:-8080}|g" \
        -e "s|{{ADMIN_PORT}}|${ADMIN_PORT:-8081}|g" \
        -e "s|{{CHROMA_PORT}}|${CHROMA_PORT:-8000}|g" \
        -e "s|{{FRONTEND_PORT}}|${FRONTEND_PORT:-3000}|g" \
        -e "s|{{PUBLIC_HOST}}|${PUBLIC_HOST:-localhost}|g" \
        -e "s|{{INSTALL_DIR}}|${INSTALL_DIR}|g" \
        -e "s|{{SERVICE_USER}}|${SERVICE_USER}|g" \
        -e "s|{{SERVICE_GROUP}}|${SERVICE_GROUP}|g" \
    )

    echo "$content" | sudo tee "$output" > /dev/null
    log_success "Fichier genere: $output"
}

# =============================================================================
# CREATION DU SERVICE API (SYSTEMD)
# =============================================================================
# Cree et active le service systemd pour l'API FastAPI.
#
# Usage:
#   create_api_service "/path/to/scripts"
# =============================================================================

create_api_service() {
    local script_dir="$1"

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        log_info "macOS: pas de service systemd"
        echo ""
        echo "  Pour demarrer l'API manuellement:"
        echo "    cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8080} --workers 4"
        echo ""
        return 0
    fi

    log_step "Creation du service API..."

    generate_from_template \
        "$script_dir/templates/myia-api.service" \
        "/etc/systemd/system/myia-api.service"

    sudo systemctl daemon-reload
    sudo systemctl enable --now myia-api
    log_success "Service myia-api actif"
}

# =============================================================================
# CREATION DU SERVICE CHROMADB (SYSTEMD)
# =============================================================================
# Cree et active le service systemd pour ChromaDB.
#
# Usage:
#   create_chromadb_service "/path/to/scripts"
# =============================================================================

create_chromadb_service() {
    local script_dir="$1"

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        log_info "macOS: pas de service systemd pour ChromaDB"
        echo ""
        echo "  Pour demarrer ChromaDB manuellement:"
        echo "    $INSTALL_DIR/venv/bin/chroma run --host 0.0.0.0 --port ${CHROMA_PORT:-8000} --path $INSTALL_DIR/data/chroma"
        echo ""
        return 0
    fi

    log_step "Creation du service ChromaDB..."

    generate_from_template \
        "$script_dir/templates/myia-chromadb.service" \
        "/etc/systemd/system/myia-chromadb.service"

    sudo systemctl daemon-reload
    sudo systemctl enable --now myia-chromadb
    log_success "Service myia-chromadb actif"
}

# =============================================================================
# CONFIGURATION DU REVERSE PROXY NGINX
# =============================================================================
# Configure nginx comme reverse proxy pour l'API et les frontends.
#
# Usage:
#   setup_nginx_reverse_proxy "/path/to/scripts"
# =============================================================================

setup_nginx_reverse_proxy() {
    local script_dir="$1"

    if ! command -v nginx &> /dev/null; then
        log_warn "nginx non installe, configuration ignoree"
        return 0
    fi

    log_step "Configuration du reverse proxy nginx..."

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        local nginx_conf_dir="/usr/local/etc/nginx"
        if [[ ! -d "$nginx_conf_dir" ]]; then
            nginx_conf_dir="/opt/homebrew/etc/nginx"
        fi

        generate_from_template \
            "$script_dir/templates/myia-nginx.conf" \
            "$nginx_conf_dir/servers/myia.conf"

        # Tester et recharger
        if nginx -t 2>/dev/null; then
            brew services restart nginx 2>/dev/null
            log_success "nginx configure et recharge (macOS)"
        else
            log_error "Configuration nginx invalide"
            return 1
        fi
    else
        generate_from_template \
            "$script_dir/templates/myia-nginx.conf" \
            "/etc/nginx/sites-available/myia"

        # Creer le lien symbolique
        sudo ln -sf /etc/nginx/sites-available/myia /etc/nginx/sites-enabled/myia

        # Supprimer le site par defaut si present
        if [[ -L /etc/nginx/sites-enabled/default ]]; then
            sudo rm /etc/nginx/sites-enabled/default
        fi

        # Tester et recharger
        if sudo nginx -t 2>/dev/null; then
            sudo systemctl reload nginx
            log_success "nginx configure et recharge"
        else
            log_error "Configuration nginx invalide"
            return 1
        fi
    fi
}

# =============================================================================
# CONFIGURATION CERTBOT HTTPS
# =============================================================================
# Installe et configure Certbot pour HTTPS.
#
# Usage:
#   setup_certbot_https
# =============================================================================

setup_certbot_https() {
    local host="${PUBLIC_HOST:-localhost}"

    if [[ "$host" == "localhost" || "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_warn "HTTPS Certbot ignore (localhost ou IP)"
        echo "  Certbot necessite un nom de domaine pour generer un certificat."
        return 0
    fi

    if [[ "$OS_FAMILY" == "darwin" ]]; then
        log_warn "Certbot non supporte sur macOS en production"
        return 0
    fi

    log_step "Configuration HTTPS avec Certbot..."

    if ! command -v certbot &> /dev/null; then
        log_info "Installation de Certbot..."
        case "$OS_FAMILY" in
            debian)
                $PKG_INSTALL certbot python3-certbot-nginx
                ;;
            rhel)
                $PKG_INSTALL certbot python3-certbot-nginx
                ;;
        esac
    fi

    if command -v certbot &> /dev/null; then
        log_info "Generation du certificat pour $host..."
        sudo certbot --nginx -d "$host" --non-interactive --agree-tos \
            --email "${PGADMIN_EMAIL:-admin@local.dev}" \
            || log_warn "Certbot: echec (verifiez le DNS et les ports 80/443)"
    fi
}

# =============================================================================
# HEALTH CHECK BARE-METAL
# =============================================================================
# Verifie que tous les services natifs fonctionnent.
#
# Usage:
#   baremetal_health_check
# =============================================================================

baremetal_health_check() {
    log_step "Verification de la sante des services..."

    local all_ok=true

    # PostgreSQL
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        if pg_isready -q 2>/dev/null; then
            log_success "PostgreSQL: actif"
        else
            log_warn "PostgreSQL: inactif"
            all_ok=false
        fi
    else
        if systemctl is-active --quiet postgresql 2>/dev/null; then
            log_success "PostgreSQL: actif"
        else
            log_warn "PostgreSQL: inactif"
            all_ok=false
        fi
    fi

    # Ollama
    if curl -sf "http://localhost:${OLLAMA_PORT:-11434}/api/tags" > /dev/null 2>&1; then
        log_success "Ollama: actif (port ${OLLAMA_PORT:-11434})"
    else
        log_warn "Ollama: inactif"
        all_ok=false
    fi

    # ChromaDB
    if [[ "$OS_FAMILY" != "darwin" ]]; then
        if systemctl is-active --quiet myia-chromadb 2>/dev/null; then
            log_success "ChromaDB: actif"
        else
            log_warn "ChromaDB: inactif"
            all_ok=false
        fi
    fi

    # API
    local app_port="${APP_PORT:-8080}"
    local max_attempts=30
    local attempt=1

    echo "  Attente de l'API (port $app_port)..."
    while [[ $attempt -le $max_attempts ]]; do
        if curl -sf "http://localhost:$app_port/health" > /dev/null 2>&1; then
            log_success "API: actif (port $app_port)"
            break
        fi
        sleep 2
        attempt=$((attempt + 1))
    done

    if [[ $attempt -gt $max_attempts ]]; then
        log_warn "API: pas de reponse apres ${max_attempts} tentatives"
        all_ok=false
    fi

    # nginx
    if command -v nginx &> /dev/null; then
        if [[ "$OS_FAMILY" == "darwin" ]]; then
            if pgrep -x "nginx" > /dev/null 2>&1; then
                log_success "nginx: actif"
            else
                log_warn "nginx: inactif"
            fi
        else
            if systemctl is-active --quiet nginx 2>/dev/null; then
                log_success "nginx: actif"
            else
                log_warn "nginx: inactif"
            fi
        fi
    fi

    if [[ "$all_ok" != "true" ]]; then
        return 1
    fi

    return 0
}

# NOTE: generate_admin_token_native() a ete deplace dans scripts/lib/auth.sh

# =============================================================================
# INSTALLATION COMPLETE BARE-METAL
# =============================================================================
# Orchestre l'installation complete en mode bare-metal.
#
# Usage:
#   baremetal_install "/path/to/project" "/path/to/scripts"
# =============================================================================

baremetal_install() {
    local project_root="$1"
    local script_dir="$2"

    init_baremetal_vars "$project_root"
    create_system_user
    copy_application_files "$project_root"
    install_postgresql
    install_ollama_native
    install_chromadb_native
    setup_python_venv "$project_root"
    generate_baremetal_env "${project_root}/.env"
    run_alembic_migrations "$project_root"
    run_seed_script "$project_root"
    create_chromadb_service "$script_dir"
    create_api_service "$script_dir"
    setup_nginx_reverse_proxy "$script_dir"

    if [[ "${DEPLOY_ENV:-dev}" == "prod" ]]; then
        setup_certbot_https
    fi
}
