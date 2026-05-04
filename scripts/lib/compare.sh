#!/bin/bash
# =============================================================================
# MY-IA - Comparaison de configuration
# =============================================================================
# Compare la configuration .env avec l'état actuel des containers/volumes
# pour déterminer les actions nécessaires (restart, suppression volumes, etc.)
#
# Compatible Bash 3.x (macOS) - n'utilise pas de tableaux associatifs
# =============================================================================

# Fichiers temporaires pour stocker les changements
CHANGES_FILE_POSTGRES=""
CHANGES_FILE_PGADMIN=""
CHANGES_FILE_ALL=""
CHANGES_FILE_RESTART=""

# =============================================================================
# CLASSIFICATION DES VARIABLES
# =============================================================================

# Variables nécessitant suppression du volume PostgreSQL
VARS_VOLUME_POSTGRES="POSTGRES_USER POSTGRES_PASSWORD APP_DB_USER APP_DB_PASSWORD APP_DB_NAME"

# Variables nécessitant suppression du volume pgAdmin
VARS_VOLUME_PGADMIN="PGADMIN_EMAIL PGADMIN_PASSWORD"

# Variables affectant tous les volumes (changement de préfixe)
VARS_VOLUME_ALL="APP_NAME_PREFIX"

# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

# Initialise les fichiers temporaires pour les changements
init_changes_files() {
    CHANGES_FILE_POSTGRES=$(mktemp)
    CHANGES_FILE_PGADMIN=$(mktemp)
    CHANGES_FILE_ALL=$(mktemp)
    CHANGES_FILE_RESTART=$(mktemp)
}

# Nettoie les fichiers temporaires
cleanup_changes_files() {
    [[ -f "$CHANGES_FILE_POSTGRES" ]] && rm -f "$CHANGES_FILE_POSTGRES"
    [[ -f "$CHANGES_FILE_PGADMIN" ]] && rm -f "$CHANGES_FILE_PGADMIN"
    [[ -f "$CHANGES_FILE_ALL" ]] && rm -f "$CHANGES_FILE_ALL"
    [[ -f "$CHANGES_FILE_RESTART" ]] && rm -f "$CHANGES_FILE_RESTART"
}

# Vérifie si une variable est dans une liste
# Usage: is_in_list "var" "list"
is_in_list() {
    local var="$1"
    local list="$2"
    echo "$list" | grep -qw "$var"
}

# =============================================================================
# FONCTIONS DE COLLECTE
# =============================================================================

# Récupère les variables d'environnement d'un container
# Usage: get_container_env <container_name>
get_container_env() {
    local container="$1"
    if docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
        docker exec "$container" env 2>/dev/null
    fi
}

# Récupère une variable spécifique d'un container
# Usage: get_container_var <container_name> <var_name>
get_container_var() {
    local container="$1"
    local var_name="$2"
    get_container_env "$container" | grep "^${var_name}=" | cut -d'=' -f2-
}

# Vérifie si un volume existe
# Usage: volume_exists <volume_name>
volume_exists() {
    local volume="$1"
    docker volume ls --format "{{.Name}}" 2>/dev/null | grep -q "^${volume}$"
}

# Liste les volumes du projet
# Usage: get_project_volumes <prefix>
get_project_volumes() {
    local prefix="$1"
    docker volume ls --format "{{.Name}}" 2>/dev/null | grep "^${prefix}_"
}

# =============================================================================
# FONCTIONS DE CLASSIFICATION
# =============================================================================

# Détermine la catégorie d'une variable
# Usage: classify_variable <var_name>
# Retourne: VOLUME_POSTGRES, VOLUME_PGADMIN, VOLUME_ALL, RESTART
classify_variable() {
    local var_name="$1"

    if is_in_list "$var_name" "$VARS_VOLUME_POSTGRES"; then
        echo "VOLUME_POSTGRES"
    elif is_in_list "$var_name" "$VARS_VOLUME_PGADMIN"; then
        echo "VOLUME_PGADMIN"
    elif is_in_list "$var_name" "$VARS_VOLUME_ALL"; then
        echo "VOLUME_ALL"
    else
        echo "RESTART"
    fi
}

# =============================================================================
# FONCTIONS DE COMPARAISON
# =============================================================================

# Compare deux valeurs et enregistre le changement si différent
# Usage: compare_and_record <var_name> <old_value> <new_value>
compare_and_record() {
    local var_name="$1"
    local old_value="$2"
    local new_value="$3"

    # Ignorer si pas de changement
    [[ "$old_value" == "$new_value" ]] && return

    # Ignorer si ancienne valeur vide (première config)
    [[ -z "$old_value" ]] && return

    local category=$(classify_variable "$var_name")

    case "$category" in
        VOLUME_POSTGRES)
            echo "${var_name}|${old_value}|${new_value}" >> "$CHANGES_FILE_POSTGRES"
            ;;
        VOLUME_PGADMIN)
            echo "${var_name}|${old_value}|${new_value}" >> "$CHANGES_FILE_PGADMIN"
            ;;
        VOLUME_ALL)
            echo "${var_name}|${old_value}|${new_value}" >> "$CHANGES_FILE_ALL"
            ;;
        RESTART)
            echo "${var_name}|${old_value}|${new_value}" >> "$CHANGES_FILE_RESTART"
            ;;
    esac
}

# Compare la configuration actuelle avec la nouvelle
# Usage: compare_configs
# Prérequis: OLD_* et NEW_* variables doivent être définies
compare_configs() {
    # Initialiser les fichiers temporaires
    init_changes_files

    # Liste des variables à comparer
    local all_vars="APP_NAME_PREFIX POSTGRES_USER POSTGRES_PASSWORD APP_DB_USER APP_DB_PASSWORD APP_DB_NAME PGADMIN_EMAIL PGADMIN_PASSWORD PGADMIN_PORT FRONTEND_PORT ADMIN_PORT APP_PORT POSTGRES_PORT CHROMA_PORT OLLAMA_PORT LLM_MODEL EMBED_MODEL DEBUG CORS_ORIGINS API_KEY JWT_SECRET_KEY SECRET_KEY ENCRYPTION_KEY TEST_ADMIN_EMAIL TEST_ADMIN_PASSWORD TEST_USER_EMAIL TEST_USER_PASSWORD TEST_CONTRIBUTOR_EMAIL TEST_CONTRIBUTOR_PASSWORD TEST_VALIDATOR_EMAIL TEST_VALIDATOR_PASSWORD"

    for var in $all_vars; do
        local old_var="OLD_${var}"
        local new_var="NEW_${var}"
        # Utiliser eval pour obtenir la valeur des variables dynamiques
        eval "local old_val=\"\${$old_var}\""
        eval "local new_val=\"\${$new_var}\""
        compare_and_record "$var" "$old_val" "$new_val"
    done
}

# =============================================================================
# FONCTIONS D'AFFICHAGE
# =============================================================================

# Compte le nombre de lignes dans un fichier
count_changes() {
    local file="$1"
    if [[ -f "$file" ]] && [[ -s "$file" ]]; then
        wc -l < "$file" | tr -d ' '
    else
        echo "0"
    fi
}

# Affiche un changement avec sa conséquence
# Usage: display_change <var_name> <old_value> <new_value> <consequence>
display_change() {
    local var_name="$1"
    local old_value="$2"
    local new_value="$3"
    local consequence="$4"

    # Masquer les mots de passe
    if echo "$var_name" | grep -qE "(PASSWORD|SECRET|KEY)"; then
        old_value="********"
        new_value="********"
    fi

    echo "  ${var_name}: \"${old_value}\" -> \"${new_value}\""
    echo "    ${consequence}"
    echo ""
}

# Affiche les changements d'un fichier
# Usage: display_changes_from_file <file> <consequence>
display_changes_from_file() {
    local file="$1"
    local consequence="$2"

    if [[ -f "$file" ]] && [[ -s "$file" ]]; then
        while IFS='|' read -r var_name old_val new_val; do
            display_change "$var_name" "$old_val" "$new_val" "$consequence"
        done < "$file"
    fi
}

# Affiche le résumé des changements détectés
# Usage: display_changes_summary
# Retourne: 0 si changements, 1 sinon
display_changes_summary() {
    local count_postgres=$(count_changes "$CHANGES_FILE_POSTGRES")
    local count_pgadmin=$(count_changes "$CHANGES_FILE_PGADMIN")
    local count_all=$(count_changes "$CHANGES_FILE_ALL")
    local count_restart=$(count_changes "$CHANGES_FILE_RESTART")

    local total=$((count_postgres + count_pgadmin + count_all + count_restart))

    echo ""
    echo "============================================================================="
    echo "  CHANGEMENTS DÉTECTÉS"
    echo "============================================================================="
    echo ""

    if [[ $total -eq 0 ]]; then
        log_success "Aucun changement détecté"
        echo ""
        return 1
    fi

    # Changements affectant tous les volumes (APP_NAME_PREFIX)
    if [[ $count_all -gt 0 ]]; then
        log_warn "CHANGEMENT CRITIQUE - Affecte tous les volumes:"
        echo ""
        display_changes_from_file "$CHANGES_FILE_ALL" \
            "⚠️  Les anciens volumes seront orphelins. Nouveaux volumes seront créés."
    fi

    # Changements volume PostgreSQL
    if [[ $count_postgres -gt 0 ]]; then
        log_warn "VOLUME postgres_data - Ces modifications nécessitent une action:"
        echo ""
        display_changes_from_file "$CHANGES_FILE_POSTGRES" \
            "⚠️  Volume contient l'ancienne valeur. → Supprimer volume OU ALTER USER/DB manuellement"
    fi

    # Changements volume pgAdmin
    if [[ $count_pgadmin -gt 0 ]]; then
        log_warn "VOLUME pgadmin_data - Ces modifications nécessitent une action:"
        echo ""
        display_changes_from_file "$CHANGES_FILE_PGADMIN" \
            "⚠️  Volume contient l'ancienne config. → Supprimer volume pgadmin_data"
    fi

    # Changements restart simple
    if [[ $count_restart -gt 0 ]]; then
        log_info "RESTART - Ces modifications seront appliquées au redémarrage:"
        echo ""
        display_changes_from_file "$CHANGES_FILE_RESTART" \
            "✓ Sera appliqué au redémarrage des containers"
    fi

    return 0
}

# =============================================================================
# FONCTIONS D'ACTION
# =============================================================================

# Propose les actions à l'utilisateur et les exécute
# Usage: prompt_and_apply_actions <prefix>
prompt_and_apply_actions() {
    local prefix="$1"
    local count_postgres=$(count_changes "$CHANGES_FILE_POSTGRES")
    local count_pgadmin=$(count_changes "$CHANGES_FILE_PGADMIN")
    local count_all=$(count_changes "$CHANGES_FILE_ALL")

    local need_volume_postgres=false
    local need_volume_pgadmin=false
    local need_volume_all=false

    [[ $count_postgres -gt 0 ]] && need_volume_postgres=true
    [[ $count_pgadmin -gt 0 ]] && need_volume_pgadmin=true
    [[ $count_all -gt 0 ]] && need_volume_all=true

    # Si pas de changement de volume, juste restart
    if [[ "$need_volume_postgres" == false ]] && [[ "$need_volume_pgadmin" == false ]] && [[ "$need_volume_all" == false ]]; then
        log_info "Seul un redémarrage est nécessaire pour appliquer les changements."
        cleanup_changes_files
        return 0
    fi

    echo "============================================================================="
    echo "  ACTIONS PROPOSÉES"
    echo "============================================================================="
    echo ""

    if [[ "$need_volume_all" == true ]]; then
        log_warn "Le changement de APP_NAME_PREFIX crée de nouveaux volumes."
        echo "  Les anciens volumes resteront orphelins et devront être supprimés manuellement."
        echo ""
    fi

    echo "  ⚠️  ATTENTION: La suppression de volumes entraîne une PERTE DE DONNÉES"
    echo ""

    # Options
    echo "  Options disponibles:"
    echo ""

    if [[ "$need_volume_postgres" == true ]]; then
        echo "    [P] Supprimer volume postgres_data (PERTE: base de données)"
    fi

    if [[ "$need_volume_pgadmin" == true ]]; then
        echo "    [G] Supprimer volume pgadmin_data (PERTE: config pgAdmin)"
    fi

    if [[ "$need_volume_postgres" == true ]] || [[ "$need_volume_pgadmin" == true ]]; then
        echo "    [T] Supprimer TOUS les volumes concernés"
    fi

    echo "    [R] Restart uniquement (ignorer changements volumes - PEUT CAUSER DES ERREURS)"
    echo "    [Q] Quitter sans appliquer"
    echo ""

    local choice
    read -p "  Votre choix: " choice

    case "$(echo "$choice" | tr '[:lower:]' '[:upper:]')" in
        P)
            if [[ "$need_volume_postgres" == true ]]; then
                delete_volume "${prefix}_postgres_data"
            fi
            ;;
        G)
            if [[ "$need_volume_pgadmin" == true ]]; then
                delete_volume "${prefix}_pgadmin_data"
            fi
            ;;
        T)
            if [[ "$need_volume_postgres" == true ]]; then
                delete_volume "${prefix}_postgres_data"
            fi
            if [[ "$need_volume_pgadmin" == true ]]; then
                delete_volume "${prefix}_pgadmin_data"
            fi
            ;;
        R)
            log_warn "Les changements de volumes sont ignorés. Des erreurs peuvent survenir."
            ;;
        Q)
            log_info "Annulé. Aucune modification appliquée."
            cleanup_changes_files
            exit 0
            ;;
        *)
            log_error "Choix invalide"
            prompt_and_apply_actions "$prefix"
            ;;
    esac

    cleanup_changes_files
}

# Supprime un volume Docker
# Usage: delete_volume <volume_name>
delete_volume() {
    local volume="$1"

    if volume_exists "$volume"; then
        log_info "Suppression du volume $volume..."

        # Arrêter les containers qui utilisent ce volume
        local containers=$(docker ps -a --filter "volume=$volume" --format "{{.Names}}" 2>/dev/null)
        if [[ -n "$containers" ]]; then
            for container in $containers; do
                log_info "Arrêt du container $container..."
                docker stop "$container" >/dev/null 2>&1
                docker rm "$container" >/dev/null 2>&1
            done
        fi

        if docker volume rm "$volume" >/dev/null 2>&1; then
            log_success "Volume $volume supprimé"
        else
            log_error "Impossible de supprimer le volume $volume"
        fi
    else
        log_info "Volume $volume n'existe pas"
    fi
}

# =============================================================================
# FONCTION PRINCIPALE
# =============================================================================

# Exécute la comparaison complète et propose les actions
# Usage: run_config_comparison <prefix>
# Prérequis: OLD_* et NEW_* variables doivent être définies
run_config_comparison() {
    local prefix="$1"

    # Comparer les configurations
    compare_configs

    # Afficher le résumé
    if display_changes_summary; then
        # Des changements ont été détectés, proposer les actions
        prompt_and_apply_actions "$prefix"
    else
        cleanup_changes_files
    fi
}
