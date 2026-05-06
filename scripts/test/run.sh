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

# Si l'on cible des tests E2E, s'assurer que (1) les system libs Linux dont
# Chromium dépend sont présentes, et (2) les binaires Chromium sont en cache.
# Le volume nommé playwright_browsers (docker-compose.yml) persiste les
# binaires entre recreate. Les libs apt sont reinstallées si le container
# est recréé from scratch (apt n'est pas dans un volume).
if [[ "$TARGET" == *"e2e"* ]] || [[ "$TARGET" == "tests/" ]] || [[ "$TARGET" == "/code/tests" ]]; then
  # (1) System deps — détectées via ldconfig (libdbus présente ⇒ toutes le sont)
  if ! docker exec "${CONTAINER}" sh -c 'ldconfig -p | grep -q libdbus-1.so.3'; then
    echo "→ Installation system deps Chromium (libnss, libdbus, libatspi, ...)"
    docker exec -u root "${CONTAINER}" sh -c "apt-get update -qq && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxcomposite1 \
      libxdamage1 libxfixes3 libxrandr2 libgbm1 libxkbcommon0 libpango-1.0-0 \
      libcairo2 libasound2 libatspi2.0-0 libdbus-1-3 libdrm2 libxext6 libx11-6 \
      libxcb1 libfontconfig1 fonts-liberation > /dev/null"
  fi
  # (2) Binaires Chromium — détectés via présence du dossier versionné
  if ! docker exec "${CONTAINER}" test -d /opt/ms-playwright/chromium_headless_shell-1148; then
    echo "→ Téléchargement Chromium dans /opt/ms-playwright (~100 MB, persistant via volume)"
    docker exec -u root -e PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
      "${CONTAINER}" playwright install chromium
    docker exec -u root "${CONTAINER}" chmod -R a+rx /opt/ms-playwright
  fi
fi

echo "→ Exécution : pytest ${TARGET}"
# PLAYWRIGHT_BROWSERS_PATH pointe vers le volume nommé playwright_browsers
# monté sur /opt/ms-playwright (cf docker-compose.yml).
docker exec -e PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
  -w /code "${CONTAINER}" python -m pytest "${TARGET}" --no-cov "$@"
