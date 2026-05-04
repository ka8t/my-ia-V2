#!/bin/bash
# =============================================================================
# MY-IA - Fonctions d'import de donnees
# =============================================================================
# Ce fichier contient les fonctions pour importer les donnees:
# - Pays (countries)
# - Villes (cities)
# - Utilisateurs de test
# - Barre de progression
# - Import streaming SSE
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/db.sh"
#   source "$SCRIPT_DIR/lib/auth.sh"
#   source "$SCRIPT_DIR/lib/data.sh"
#
# Prerequis:
#   - common.sh, db.sh et auth.sh doivent etre sources avant ce fichier
#
# =============================================================================

# =============================================================================
# BARRE DE PROGRESSION ASCII
# =============================================================================
# Affiche une barre de progression ASCII.
#
# Usage:
#   show_progress_bar 45 100 "Importation"
#   # Affiche: Importation [████████████████░░░░░░░░░░░░░░] 45% (45/100)
#
# Parametres:
#   $1 - Valeur courante
#   $2 - Valeur totale
#   $3 - Label (optionnel)
# =============================================================================

show_progress_bar() {
    local current="$1"
    local total="$2"
    local label="${3:-Progression}"
    local width=30

    if [[ "$total" -eq 0 ]]; then
        total=1
    fi

    local percent=$((current * 100 / total))
    local filled=$((width * current / total))
    local empty=$((width - filled))

    # Construire la barre
    local bar=""
    for ((i=0; i<filled; i++)); do
        bar="${bar}█"
    done
    for ((i=0; i<empty; i++)); do
        bar="${bar}░"
    done

    # Afficher (avec retour chariot pour ecraser la ligne)
    printf "\r  ${label}: [${bar}] %3d%% (%d/%d)  " "$percent" "$current" "$total"
}

# =============================================================================
# IMPORT AVEC STREAMING SSE
# =============================================================================
# Lance l'import des villes avec affichage de la progression via SSE.
#
# Usage:
#   import_cities_stream "container_name" "api_port" "token" "file|api"
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Port API
#   $3 - Token admin
#   $4 - Source: "file" ou "api"
#
# Retour:
#   0 si succes, 1 si erreur
# =============================================================================

import_cities_stream() {
    local container_name="$1"
    local api_port="$2"
    local admin_token="$3"
    local source="${4:-file}"

    local url="http://localhost:${api_port}/admin/geo/import/cities/stream"
    local body="{\"country_code\": \"FR\", \"source\": \"${source}\", \"reset\": true}"

    echo ""
    log_info "Demarrage de l'import (source: ${source})..."
    echo ""

    # Variables pour suivre la progression
    local last_progress=0
    local success=false
    local imported_count=0
    local duration=0
    local error_msg=""

    # Appel SSE avec curl
    # On utilise --no-buffer pour avoir les donnees en temps reel
    while IFS= read -r line; do
        # Ignorer les lignes vides
        [[ -z "$line" ]] && continue

        # Extraire le JSON apres "data: "
        if [[ "$line" == data:* ]]; then
            local json="${line#data: }"

            # Parser les champs JSON avec grep/sed (compatible bash 3.x)
            local event=$(echo "$json" | grep -o '"event":"[^"]*"' | cut -d'"' -f4)
            local progress=$(echo "$json" | grep -o '"progress":[0-9]*' | cut -d':' -f2)
            local current=$(echo "$json" | grep -o '"current":[0-9]*' | cut -d':' -f2)
            local total=$(echo "$json" | grep -o '"total":[0-9]*' | cut -d':' -f2)
            local status=$(echo "$json" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
            local message=$(echo "$json" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)

            case "$event" in
                progress)
                    # Afficher la barre de progression
                    if [[ -n "$current" && -n "$total" ]]; then
                        show_progress_bar "$current" "$total" "Import"
                    fi
                    ;;
                complete)
                    # Terminer la ligne de progression
                    echo ""
                    echo ""

                    # Extraire les resultats
                    success=$(echo "$json" | grep -o '"success":true' | grep -q 'true' && echo "true" || echo "false")
                    imported_count=$(echo "$json" | grep -o '"imported_count":[0-9]*' | cut -d':' -f2)
                    duration=$(echo "$json" | grep -o '"duration_seconds":[0-9.]*' | cut -d':' -f2)

                    if [[ "$success" == "true" ]]; then
                        log_success "Import termine: ${imported_count:-?} villes en ${duration:-?}s"
                        return 0
                    else
                        error_msg=$(echo "$json" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
                        log_error "Import echoue: ${error_msg:-Erreur inconnue}"
                        return 1
                    fi
                    ;;
                error)
                    echo ""
                    error_msg=$(echo "$json" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
                    log_error "Erreur: ${error_msg:-Erreur inconnue}"
                    return 1
                    ;;
            esac
        fi
    done < <(curl -sN -X POST "$url" \
        -H "Authorization: Bearer $admin_token" \
        -H "Content-Type: application/json" \
        -H "Accept: text/event-stream" \
        -d "$body" 2>/dev/null)

    # Si on arrive ici sans succes, c'est une erreur
    if [[ "$success" != "true" ]]; then
        echo ""
        log_error "Import interrompu ou echoue"
        return 1
    fi

    return 0
}

# =============================================================================
# IMPORT DES PAYS DEPUIS FICHIER
# =============================================================================
# Importe les pays depuis le fichier countries.json via l'API.
#
# Usage:
#   result=$(import_countries_from_file "api_port" "token" "reset")
#
# Parametres:
#   $1 - Port API
#   $2 - Token admin
#   $3 - Reset (true/false)
#
# Retour:
#   Nombre de pays importes, ou -1 si erreur
# =============================================================================

import_countries_from_file() {
    local api_port="$1"
    local admin_token="$2"
    local reset="${3:-false}"

    local url="http://localhost:${api_port}/admin/geo/import/countries/file"
    local body="{\"reset\": ${reset}}"

    local response
    response=$(curl -s -X POST "$url" \
        -H "Authorization: Bearer $admin_token" \
        -H "Content-Type: application/json" \
        -d "$body" 2>/dev/null)

    # Extraire le resultat
    local success=$(echo "$response" | grep -o '"success":true' | grep -q 'true' && echo "true" || echo "false")
    local imported_count=$(echo "$response" | grep -o '"imported_count":[0-9]*' | cut -d':' -f2)

    if [[ "$success" == "true" && -n "$imported_count" ]]; then
        echo "$imported_count"
    else
        echo "-1"
    fi
}

# =============================================================================
# CREATION DES UTILISATEURS DE TEST
# =============================================================================
# Cree les utilisateurs de test via l'API.
#
# Usage:
#   result=$(create_test_users "api_port" "token")
#
# Parametres:
#   $1 - Port API
#   $2 - Token admin
#
# Retour:
#   Nombre d'utilisateurs crees, ou -1 si erreur
# =============================================================================

create_test_users() {
    local api_port="$1"
    local admin_token="$2"

    local url="http://localhost:${api_port}/admin/users/create-test-users"

    local response
    response=$(curl -s -X POST "$url" \
        -H "Authorization: Bearer $admin_token" \
        -H "Content-Type: application/json" 2>/dev/null)

    # Extraire le resultat
    local success=$(echo "$response" | grep -o '"success":true' | grep -q 'true' && echo "true" || echo "false")
    local created_count=$(echo "$response" | grep -o '"created_count":[0-9]*' | cut -d':' -f2)

    if [[ "$success" == "true" && -n "$created_count" ]]; then
        echo "$created_count"
    else
        # Verifier si c'est parce que les users existent deja
        local already_exist=$(echo "$response" | grep -o '"already_exist":true' | grep -q 'true' && echo "true" || echo "false")
        if [[ "$already_exist" == "true" ]]; then
            echo "0"
        else
            echo "-1"
        fi
    fi
}

# =============================================================================
# VARIABLES GLOBALES POUR LE RECAPITULATIF
# =============================================================================

RECAP_COUNTRIES_STATUS=""
RECAP_CITIES_STATUS=""
RECAP_TEST_USERS_STATUS=""

# =============================================================================
# MENU D'IMPORT DES PAYS
# =============================================================================
# Affiche le menu d'import des pays et execute l'action choisie.
#
# Usage:
#   show_countries_menu "$app_container" "$app_port" "$admin_token" "$project_root"
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Port API
#   $3 - Token admin
#   $4 - Chemin du projet
# =============================================================================

show_countries_menu() {
    local app_container="$1"
    local app_port="$2"
    local admin_token="$3"
    local project_root="$4"

    local countries_file="$project_root/static-datas/countries.json"
    local countries_count
    countries_count=$(get_countries_count "$app_container")

    echo ""
    echo "============================================================================="
    echo "  IMPORT DES PAYS"
    echo "============================================================================="
    echo ""

    if [[ "$countries_count" -gt 0 ]]; then
        echo -e "  Statut: ${GREEN}${countries_count} pays en base${NC}"
        RECAP_COUNTRIES_STATUS="${countries_count} pays (existants)"
    else
        echo "  Statut: Aucun pays en base"
    fi

    if [[ -f "$countries_file" ]]; then
        echo "  Fichier local: countries.json"
    else
        echo -e "  Fichier local: ${YELLOW}Non trouve${NC}"
    fi
    echo ""

    if [[ "$countries_count" -eq 0 && -f "$countries_file" ]]; then
        echo "  Options disponibles:"
        echo "    [1] Importer les pays depuis countries.json"
        echo "    [2] Ignorer"
        echo ""
        printf "  Votre choix [1/2]: "
        read -r choice < /dev/tty

        case "$choice" in
            1)
                log_info "Import des pays..."
                local result
                result=$(import_countries_from_file "$app_port" "$admin_token" "false")
                if [[ "$result" -gt 0 ]]; then
                    log_success "${result} pays importes"
                    RECAP_COUNTRIES_STATUS="${result} pays importes"
                elif [[ "$result" -eq 0 ]]; then
                    log_info "Pays deja presents"
                    RECAP_COUNTRIES_STATUS="Pays deja presents"
                else
                    log_error "Erreur lors de l'import"
                    RECAP_COUNTRIES_STATUS="Erreur import"
                fi
                ;;
            2|*)
                log_info "Import ignore"
                RECAP_COUNTRIES_STATUS="Import ignore"
                ;;
        esac
    elif [[ "$countries_count" -gt 0 ]]; then
        echo "  Options disponibles:"
        echo "    [1] Reimporter (reset)"
        echo "    [2] Conserver les donnees actuelles"
        echo ""
        printf "  Votre choix [1/2]: "
        read -r choice < /dev/tty

        case "$choice" in
            1)
                log_info "Reimport des pays..."
                local result
                result=$(import_countries_from_file "$app_port" "$admin_token" "true")
                if [[ "$result" -gt 0 ]]; then
                    log_success "${result} pays reimportes"
                    RECAP_COUNTRIES_STATUS="${result} pays reimportes"
                else
                    log_error "Erreur lors du reimport"
                    RECAP_COUNTRIES_STATUS="Erreur reimport"
                fi
                ;;
            2|*)
                log_info "Donnees conservees"
                RECAP_COUNTRIES_STATUS="${countries_count} pays (conserves)"
                ;;
        esac
    else
        log_warn "Fichier countries.json non trouve"
        RECAP_COUNTRIES_STATUS="Fichier non trouve"
    fi
}

# =============================================================================
# MENU D'IMPORT DES VILLES
# =============================================================================
# Affiche le menu d'import des villes et execute l'action choisie.
#
# Usage:
#   show_cities_menu "$app_container" "$app_port" "$admin_token" "$project_root"
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Port API
#   $3 - Token admin
#   $4 - Chemin du projet
# =============================================================================

show_cities_menu() {
    local app_container="$1"
    local app_port="$2"
    local admin_token="$3"
    local project_root="$4"

    local geo_country="${GEO_DEFAULT_COUNTRY:-FR}"
    local geo_source="${GEO_CITIES_SOURCE:-file}"
    local geo_auto="${GEO_AUTO_IMPORT:-false}"
    local cities_file="$project_root/static-datas/${geo_country}_cities.json"

    local cities_count
    cities_count=$(get_cities_count "$app_container")

    echo ""
    echo "============================================================================="
    echo "  IMPORT DES VILLES (${geo_country})"
    echo "============================================================================="
    echo ""

    echo "  Configuration: pays=${geo_country}, source=${geo_source}, auto=${geo_auto}"
    echo ""

    if [[ "$cities_count" -gt 0 ]]; then
        echo -e "  Statut: ${GREEN}${cities_count} villes en base${NC}"
    else
        echo "  Statut: Aucune ville en base"
    fi

    if [[ -f "$cities_file" ]]; then
        local local_count
        local_count=$(grep -c '"name"' "$cities_file" 2>/dev/null || echo "?")
        echo "  Fichier local: ${geo_country}_cities.json (${local_count} villes)"
    else
        echo -e "  Fichier local: ${YELLOW}Non trouve${NC}"
    fi
    echo ""

    # Mode AUTO-IMPORT
    if [[ "$geo_auto" == "true" ]]; then
        if [[ "$cities_count" -eq 0 ]]; then
            log_info "Auto-import active (GEO_AUTO_IMPORT=true)"

            if [[ "$geo_source" == "file" && -f "$cities_file" ]]; then
                log_info "Import automatique depuis fichier local..."
                if import_cities_stream "$app_container" "$app_port" "$admin_token" "file"; then
                    RECAP_CITIES_STATUS="Auto-import depuis fichier"
                else
                    RECAP_CITIES_STATUS="Erreur auto-import"
                fi
            elif [[ "$geo_source" == "api" ]] || [[ ! -f "$cities_file" ]]; then
                log_info "Import automatique depuis API..."
                if import_cities_stream "$app_container" "$app_port" "$admin_token" "api"; then
                    RECAP_CITIES_STATUS="Auto-import depuis API"
                else
                    RECAP_CITIES_STATUS="Erreur auto-import"
                fi
            fi
        else
            log_info "Villes deja presentes, auto-import ignore"
            RECAP_CITIES_STATUS="${cities_count} villes (existantes)"
        fi
        return
    fi

    # Mode INTERACTIF
    if [[ "$cities_count" -gt 0 ]]; then
        echo "  Options disponibles:"
        if [[ -f "$cities_file" ]]; then
            echo "    [1] Reimporter depuis fichier local (rapide)"
            echo "    [2] Retelecharger depuis API (lent)"
            echo "    [3] Conserver les donnees actuelles"
            echo ""
            printf "  Votre choix [1/2/3]: "
            read -r choice < /dev/tty

            case "$choice" in
                1)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "file"; then
                        RECAP_CITIES_STATUS="Reimportees depuis fichier"
                    else
                        RECAP_CITIES_STATUS="Erreur reimport"
                    fi
                    ;;
                2)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "api"; then
                        RECAP_CITIES_STATUS="Retelecharges depuis API"
                    else
                        RECAP_CITIES_STATUS="Erreur telechargement"
                    fi
                    ;;
                3|*)
                    log_info "Donnees conservees (${cities_count} villes)"
                    RECAP_CITIES_STATUS="${cities_count} villes (conservees)"
                    ;;
            esac
        else
            echo "    [1] Telecharger depuis API"
            echo "    [2] Conserver les donnees actuelles"
            echo ""
            printf "  Votre choix [1/2]: "
            read -r choice < /dev/tty

            case "$choice" in
                1)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "api"; then
                        RECAP_CITIES_STATUS="Telecharges depuis API"
                    else
                        RECAP_CITIES_STATUS="Erreur telechargement"
                    fi
                    ;;
                2|*)
                    log_info "Donnees conservees (${cities_count} villes)"
                    RECAP_CITIES_STATUS="${cities_count} villes (conservees)"
                    ;;
            esac
        fi
    else
        # Aucune ville en base
        echo "  Options disponibles:"
        if [[ -f "$cities_file" ]]; then
            if [[ "$geo_source" == "file" ]]; then
                echo "    [1] Importer depuis fichier local (recommande)"
                echo "    [2] Telecharger depuis API"
            else
                echo "    [1] Importer depuis fichier local"
                echo "    [2] Telecharger depuis API (recommande)"
            fi
            echo "    [3] Ignorer l'import"
            echo ""
            printf "  Votre choix [1/2/3]: "
            read -r choice < /dev/tty

            case "$choice" in
                1)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "file"; then
                        RECAP_CITIES_STATUS="Importees depuis fichier"
                    else
                        RECAP_CITIES_STATUS="Erreur import"
                    fi
                    ;;
                2)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "api"; then
                        RECAP_CITIES_STATUS="Telecharges depuis API"
                    else
                        RECAP_CITIES_STATUS="Erreur telechargement"
                    fi
                    ;;
                3|*)
                    log_info "Import ignore"
                    RECAP_CITIES_STATUS="Import ignore"
                    ;;
            esac
        else
            echo "    [1] Telecharger depuis API"
            echo "    [2] Ignorer l'import"
            echo ""
            printf "  Votre choix [1/2]: "
            read -r choice < /dev/tty

            case "$choice" in
                1)
                    if import_cities_stream "$app_container" "$app_port" "$admin_token" "api"; then
                        RECAP_CITIES_STATUS="Telecharges depuis API"
                    else
                        RECAP_CITIES_STATUS="Erreur telechargement"
                    fi
                    ;;
                2|*)
                    log_info "Import ignore"
                    RECAP_CITIES_STATUS="Import ignore"
                    ;;
            esac
        fi
    fi
}

# =============================================================================
# MENU DES UTILISATEURS DE TEST
# =============================================================================
# Affiche le menu des utilisateurs de test.
#
# Usage:
#   show_test_users_menu "$app_container"
# =============================================================================

show_test_users_menu() {
    local app_container="$1"

    echo ""
    echo "============================================================================="
    echo "  UTILISATEURS DE TEST"
    echo "============================================================================="
    echo ""

    if [[ "${DEBUG:-false}" == "true" ]]; then
        local test_users_exist
        test_users_exist=$(check_test_users_exist "$app_container")

        if [[ "$test_users_exist" == "true" ]]; then
            echo -e "  Mode: ${GREEN}DEBUG=true${NC}"
            echo -e "  Statut: ${GREEN}Utilisateurs de test presents${NC}"
            echo ""
            echo "  Comptes disponibles:"
            echo "    - Admin:       ${TEST_ADMIN_EMAIL:-admin@test.local}"
            echo "    - User:        ${TEST_USER_EMAIL:-user@test.local}"
            echo "    - Contributor: ${TEST_CONTRIBUTOR_EMAIL:-contributor@test.local}"
            echo "    - Validator:   ${TEST_VALIDATOR_EMAIL:-validator@test.local}"
            RECAP_TEST_USERS_STATUS="4 utilisateurs (existants)"
        else
            echo -e "  Mode: ${GREEN}DEBUG=true${NC}"
            echo -e "  Statut: ${YELLOW}Utilisateurs non trouves${NC}"
            echo ""
            echo "  Les utilisateurs de test sont crees automatiquement au demarrage"
            echo "  du container si DEBUG=true. Verifiez les logs du container."
            RECAP_TEST_USERS_STATUS="Non trouves (verifier logs)"
        fi
    else
        echo -e "  Mode: ${YELLOW}DEBUG=false (production)${NC}"
        echo "  Statut: Utilisateurs de test non crees en mode production"
        RECAP_TEST_USERS_STATUS="Mode production"
    fi
    echo ""
}

# =============================================================================
# GESTION COMPLETE DES IMPORTS
# =============================================================================
# Gere tous les imports de donnees.
#
# Usage:
#   handle_data_imports "$project_root"
#
# Parametres:
#   $1 - Chemin du projet
# =============================================================================

handle_data_imports() {
    local project_root="$1"
    # Le nom du container utilise SANITIZED_PREFIX (voir docker-compose.yml)
    local app_container="${SANITIZED_PREFIX}_app"
    local app_port="${APP_PORT:-8080}"

    log_step "Verification de l'etat de l'application..."
    sleep 5

    # Verifier si le container app est demarre
    if ! docker ps --format "{{.Names}}" | grep -q "^${app_container}$"; then
        log_warn "Container app non trouve: $app_container"
        log_warn "Les imports devront etre faits manuellement"
        RECAP_COUNTRIES_STATUS="Container non trouve"
        RECAP_CITIES_STATUS="Container non trouve"
        RECAP_TEST_USERS_STATUS="Container non trouve"
        return 1
    fi

    # Generation du token admin
    log_info "Generation du token admin..."
    local admin_token
    admin_token=$(generate_admin_token "$app_container")

    if [[ -z "$admin_token" ]]; then
        log_error "Impossible de generer le token admin"
        log_warn "Les imports devront etre faits manuellement via l'interface admin"
        RECAP_COUNTRIES_STATUS="Token non genere"
        RECAP_CITIES_STATUS="Token non genere"
    else
        # Menu import pays
        show_countries_menu "$app_container" "$app_port" "$admin_token" "$project_root"

        # Menu import villes
        show_cities_menu "$app_container" "$app_port" "$admin_token" "$project_root"
    fi

    # Menu utilisateurs de test
    show_test_users_menu "$app_container"
}

# =============================================================================
# AFFICHAGE DU RECAPITULATIF DES IMPORTS
# =============================================================================
# Affiche le recapitulatif des actions d'import effectuees.
#
# Usage:
#   show_data_recap
# =============================================================================

show_data_recap() {
    echo ""
    echo "============================================================================="
    echo "  ACTIONS EFFECTUEES"
    echo "============================================================================="
    echo ""
    echo "    Pays:             ${RECAP_COUNTRIES_STATUS:-Non traite}"
    echo "    Villes:           ${RECAP_CITIES_STATUS:-Non traite}"
    echo "    Users de test:    ${RECAP_TEST_USERS_STATUS:-Non traite}"
}
