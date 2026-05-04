#!/bin/bash
# =============================================================================
# MY-IA - Generation du fichier .env
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE_FILE="$PROJECT_ROOT/.env.example"
OUTPUT_FILE="$PROJECT_ROOT/.env"

# Charger les fonctions partagees
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/env.sh"

# Prefixe pour les logs
LOG_PREFIX="ENV"

# =============================================================================
# AIDE
# =============================================================================

show_help() {
    cat << 'EOF'
MY-IA - Generation du fichier .env
==================================

DESCRIPTION:
    Ce script genere le fichier .env final a partir de plusieurs sources.

    Il effectue les operations suivantes:
      1. Lit la configuration depuis .env.example
      2. Charge les valeurs existantes depuis .env (si present)
      3. Charge les credentials depuis .external_secrets (si present)
      4. Propose un menu interactif d'edition (16 categories)
      5. Verifie la disponibilite des ports (propose alternatives si occupes)
      6. Applique les regles de nommage PostgreSQL (sanitization)
      7. Genere les cles de securite (JWT, ENCRYPTION, API, etc.)
      8. Ecrit le fichier .env avec toutes les variables

USAGE:
    ./scripts/generate-env.sh [OPTIONS]

OPTIONS:
    -h, --help      Affiche cette aide
    -f, --force     Force la regeneration meme si .env existe deja
    -d, --debug     Active le mode debug (affiche toutes les actions detaillees)

EXEMPLES:
    # Generer .env (echoue si existe deja)
    ./scripts/generate-env.sh

    # Forcer la regeneration
    ./scripts/generate-env.sh --force

    # Mode debug (affiche toutes les etapes)
    ./scripts/generate-env.sh --debug

    # Combiner les options
    ./scripts/generate-env.sh --force --debug

FICHIERS:
    .env.example              Configuration generale (ports, backends, options)
    external_secrets.template Modele pour les credentials (reference)
    .external_secrets         Vos credentials reels (SMTP, OAuth, SMS)
    .env                      Fichier final genere (utilise par Docker)

SECRETS EXTERNES (.external_secrets):
    Ce fichier optionnel contient vos credentials sensibles:
      - SMTP (host, port, username, password)
      - SendGrid (API key)
      - OAuth Google/GitHub (client ID, secret)
      - SMS Twilio/OVH/Vonage/AWS/MessageBird

    Installation:
      cp external_secrets.template .external_secrets
      nano .external_secrets
      ./scripts/generate-env.sh --force

    Le menu interactif (categorie 16) permet aussi d'editer ces secrets
    et de les sauvegarder dans .external_secrets.

VARIABLES GENEREES:
    POSTGRES_USER       ${prefix_sanitize}_postgres_admin
    APP_DB_USER         ${prefix_sanitize}_db_user
    APP_DB_NAME         ${prefix_sanitize}_db
    DATABASE_URL        URL de connexion complete
    JWT_SECRET_KEY      Cle 64 hex (openssl rand -hex 32)
    ENCRYPTION_KEY      Cle 64 hex (openssl rand -hex 32)
    SECRET_KEY          Cle 64 hex (openssl rand -hex 32)
    API_KEY             Cle 32 hex (openssl rand -hex 16)

VERIFICATION DOCKER:
    Avant de generer le .env, le script verifie si des containers
    Docker existent deja avec le meme prefixe (APP_NAME_PREFIX).

    Containers verifies:
      - ${prefix}_postgres    - Base de donnees
      - ${prefix}_chroma      - ChromaDB
      - ${prefix}_ollama      - Ollama LLM
      - ${prefix}_app         - API FastAPI
      - ${prefix}_ui_front    - Interface utilisateur
      - ${prefix}_ui_back     - Interface admin

    Si des containers existent:
      1. Propose de tous les arreter/supprimer d'un coup
      2. Ou gestion individuelle (arreter puis supprimer chacun)

    Cela evite les conflits de noms Docker au demarrage.

VERIFICATION DES PORTS:
    Les ports suivants sont verifies au demarrage:
      - FRONTEND_PORT (3000)  - Interface utilisateur
      - ADMIN_PORT (8081)     - Interface admin
      - APP_PORT (8080)       - API FastAPI
      - POSTGRES_PORT (5432)  - PostgreSQL
      - CHROMA_PORT (8000)    - ChromaDB
      - OLLAMA_PORT (11434)   - Ollama LLM

    Si un port est occupe, le script propose automatiquement
    un port alternatif ou permet une saisie manuelle.

REGLES DE NOMMAGE POSTGRESQL:
    Les identifiants PostgreSQL (users, databases) sont automatiquement
    normalises selon les regles de CLAUDE.md:
      - Caracteres autorises: a-z, 0-9, _
      - Pas de tirets, pas de caracteres speciaux
      - Conversion en minuscules automatique

    Les mots de passe ne sont PAS modifies.

VOIR AUSSI:
    ./scripts/start.sh              Demarre l'application (appelle ce script)
    ./scripts/stop.sh               Arrete l'application
    docs/technique/CONFIGURATION.md Documentation complete du systeme de config
    CLAUDE.md                       Regles de nommage PostgreSQL

EOF
    exit 0
}

# =============================================================================
# PARSING DES ARGUMENTS
# =============================================================================

# --help prioritaire
for arg in "$@"; do
    case $arg in
        -h|--help)
            show_help
            ;;
    esac
done

# Autres arguments
FORCE=false
FROM_TEMPLATE=false

for arg in "$@"; do
    case $arg in
        -f|--force)
            FORCE=true
            ;;
        -d|--debug)
            DEBUG_MODE=true
            export DEBUG_MODE
            ;;
        --from-template)
            FROM_TEMPLATE=true
            FORCE=true  # Implique --force car on regenere
            ;;
        -*)
            log_error "Option inconnue: $arg"
            echo "Utilisez --help pour voir les options disponibles"
            exit 1
            ;;
    esac
done

# Afficher le mode debug si active
if [[ "$DEBUG_MODE" == "true" ]]; then
    log_info "Mode DEBUG active - toutes les actions seront tracees"
    echo ""
fi

# =============================================================================
# VERIFICATIONS
# =============================================================================

log_debug "Verification du fichier template: $TEMPLATE_FILE"
if [[ ! -f "$TEMPLATE_FILE" ]]; then
    log_error "Fichier .env.example introuvable"
    log_error "Copiez .env.example depuis le repository ou creez-le manuellement"
    exit 1
fi
log_debug "Fichier template trouve: $(ls -la "$TEMPLATE_FILE" 2>/dev/null | awk '{print $5, $6, $7, $8}' || echo "OK")"

# Si .env existe et pas de --force, indiquer comment forcer
log_debug "Verification du fichier .env existant: $OUTPUT_FILE"
if [[ -f "$OUTPUT_FILE" && "$FORCE" != "true" ]]; then
    log_debug "Fichier .env existe et --force non specifie"
    log_warn "Fichier .env existe deja. Utilisez --force pour regenerer."
    exit 0
fi
if [[ -f "$OUTPUT_FILE" ]]; then
    log_debug "Fichier .env existant sera ecrase (--force actif)"
fi

# Verifier les prerequis
log_debug "Verification des prerequis: openssl"
if ! check_prerequisites openssl; then
    exit 1
fi
log_debug "Prerequis OK: openssl version $(openssl version 2>/dev/null | head -1)"

# =============================================================================
# CHARGEMENT DES VARIABLES
# =============================================================================

# Toujours lire le template d'abord (valeurs par defaut)
log_debug "Debut du chargement des variables depuis le template"
log_info "Lecture de .env.example..."
read_template_vars "$TEMPLATE_FILE"
log_debug "Lecture template terminee"

# Charger depuis .env existant sauf si --from-template
if [[ "$FROM_TEMPLATE" != "true" && -f "$OUTPUT_FILE" ]]; then
    log_debug "Chargement des valeurs existantes depuis .env (--from-template non actif)"
    log_info "Chargement des valeurs existantes depuis .env..."
    # Desactiver temporairement set -e car source peut echouer sur certaines lignes
    set +e
    set -a
    source "$OUTPUT_FILE" 2>/dev/null
    set +a
    set -e
    # Corriger le format JSON de CORS_ORIGINS (peut etre casse dans ancien .env)
    log_debug "Correction du format CORS_ORIGINS: $CORS_ORIGINS"
    CORS_ORIGINS=$(fix_json_array "$CORS_ORIGINS")
    log_debug "CORS_ORIGINS corrige: $CORS_ORIGINS"
    log_success "Variables pre-remplies depuis .env existant"
else
    log_debug "Utilisation des valeurs par defaut (pas de .env existant ou --from-template actif)"
    log_info "Utilisation des valeurs par defaut de .env.example"
fi

# =============================================================================
# CHARGEMENT DES SECRETS EXTERNES
# =============================================================================

log_debug "Recherche du fichier .external_secrets"
load_external_secrets "$PROJECT_ROOT"

# Verifier le prefixe
log_debug "Verification APP_NAME_PREFIX"
if [[ -z "$APP_NAME_PREFIX" ]]; then
    log_error "APP_NAME_PREFIX non defini dans .env.example"
    exit 1
fi

log_info "APP_NAME_PREFIX: $APP_NAME_PREFIX"

# Sanitizer le prefixe pour les noms Docker
log_debug "Sanitization du prefixe '$APP_NAME_PREFIX'"
SANITIZED_PREFIX=$(sanitize "$APP_NAME_PREFIX")
log_debug "Resultat sanitization: '$APP_NAME_PREFIX' -> '$SANITIZED_PREFIX'"
log_info "Prefixe sanitize: $SANITIZED_PREFIX"

# =============================================================================
# EDITION INTERACTIVE DE LA CONFIGURATION
# =============================================================================

log_debug "Lancement de l'edition interactive"
# Edition interactive (toujours proposee)
edit_config_interactive

# Re-sanitizer le prefixe si modifie
log_debug "Re-sanitization du prefixe apres edition interactive"
SANITIZED_PREFIX=$(sanitize "$APP_NAME_PREFIX")
log_debug "Prefixe final: '$SANITIZED_PREFIX'"

# =============================================================================
# VERIFICATION DES PORTS
# =============================================================================

log_debug "Debut de la verification des ports"
log_step "Verification des ports..."

# Fonction pour verifier et mettre a jour un port
check_and_update_port() {
    local var_name="$1"
    local service_name="$2"
    local current_port="${!var_name}"

    log_debug "Verification port $var_name=$current_port pour $service_name"

    if [[ -z "$current_port" ]]; then
        log_debug "Port $var_name non defini, ignore"
        return 0
    fi

    local new_port=$(check_port_interactive "$current_port" "$service_name")

    if [[ "$new_port" != "$current_port" ]]; then
        # Mettre a jour la variable globale
        eval "$var_name=$new_port"
        log_debug "Port $var_name mis a jour: $current_port -> $new_port"
        log_success "$service_name: port $current_port -> $new_port"
    else
        log_debug "Port $current_port disponible pour $service_name"
        log_success "$service_name: port $current_port disponible"
    fi
}

# Verifier chaque port
check_and_update_port "FRONTEND_PORT" "Frontend"
check_and_update_port "ADMIN_PORT" "Admin UI"
check_and_update_port "APP_PORT" "API FastAPI"
check_and_update_port "POSTGRES_PORT" "PostgreSQL"
check_and_update_port "CHROMA_PORT" "ChromaDB"
check_and_update_port "OLLAMA_PORT" "Ollama"

log_debug "Verification des ports terminee"
log_debug "Ports finaux: FRONTEND=$FRONTEND_PORT, ADMIN=$ADMIN_PORT, APP=$APP_PORT, POSTGRES=$POSTGRES_PORT, CHROMA=$CHROMA_PORT, OLLAMA=$OLLAMA_PORT"
echo ""

# Generer les identifiants PostgreSQL
log_debug "Generation des identifiants PostgreSQL"
log_info "Generation des identifiants PostgreSQL (sanitizes)..."
generate_pg_identifiers "$APP_NAME_PREFIX"
log_debug "Identifiants PostgreSQL generes:"
log_debug "  POSTGRES_USER=$POSTGRES_USER"
log_debug "  APP_DB_USER=$APP_DB_USER"
log_debug "  APP_DB_NAME=$APP_DB_NAME"

# Les mots de passe ne sont pas modifies
log_debug "Traitement des mots de passe (non modifies)"
POSTGRES_PASSWORD=$(sanitize "$POSTGRES_PASSWORD" true)
APP_DB_PASSWORD=$(sanitize "$APP_DB_PASSWORD" true)
log_debug "Mots de passe conserves (longueur POSTGRES: ${#POSTGRES_PASSWORD}, APP: ${#APP_DB_PASSWORD})"

# Generer les cles de securite
log_debug "Generation des cles de securite"
log_info "Generation des cles de securite..."
generate_security_keys
log_debug "Cles de securite generees:"
log_debug "  JWT_SECRET_KEY: ${JWT_SECRET_KEY:0:8}... (${#JWT_SECRET_KEY} chars)"
log_debug "  ENCRYPTION_KEY: ${ENCRYPTION_KEY:0:8}... (${#ENCRYPTION_KEY} chars)"
log_debug "  SECRET_KEY: ${SECRET_KEY:0:8}... (${#SECRET_KEY} chars)"
log_debug "  API_KEY: ${API_KEY:0:8}... (${#API_KEY} chars)"

# Ecrire le fichier .env
log_debug "Ecriture du fichier .env: $OUTPUT_FILE"
log_info "Ecriture du fichier .env..."
write_env_file "$OUTPUT_FILE"
log_debug "Fichier .env ecrit: $(ls -la "$OUTPUT_FILE" 2>/dev/null | awk '{print $5, "bytes"}' || echo "OK")"

# Afficher le resume
log_debug "Affichage du resume final"
show_env_summary

log_debug "Script termine avec succes"
