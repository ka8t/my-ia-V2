#!/usr/bin/env bash
# =============================================================================
# scripts/test/run.sh — Lance la suite de tests dans le container app
# =============================================================================
# Usage :
#   ./scripts/test/run.sh                    # tout (unit + integration)
#   ./scripts/test/run.sh integration        # un sous-dossier
#   ./scripts/test/run.sh integration/test_admin_corpus.py
#
# Le script installe (idempotent) les deps de test puis exécute pytest.
# Les deps ne sont PAS dans l'image prod pour rester légère ; à la première
# exécution il y a un coût d'installation pip.
# =============================================================================
set -euo pipefail

CONTAINER="${MY_IA_V2_APP_CONTAINER:-my_ia_v2_app}"
TARGET="${1:-tests/}"
[[ $# -ge 1 ]] && shift  # le reste passe en args pytest extra

# tests/ est le mount par défaut ; si l'utilisateur passe un chemin relatif
# dans tests/, on le préfixe.
if [[ ! "$TARGET" =~ ^tests/ ]] && [[ ! "$TARGET" =~ ^/ ]]; then
  TARGET="tests/${TARGET}"
fi

echo "→ Vérification du container : ${CONTAINER}"
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "✗ Container ${CONTAINER} introuvable. Lancer ./scripts/start.sh d'abord." >&2
  exit 1
fi

echo "→ Installation deps de test (idempotent)"
docker exec -u root "${CONTAINER}" pip install --quiet --root-user-action=ignore \
  -r /code/requirements-test.txt

echo "→ Exécution : pytest ${TARGET}"
docker exec -w /code "${CONTAINER}" python -m pytest "${TARGET}" --no-cov "$@"
