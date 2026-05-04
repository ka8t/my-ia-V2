"""
Middleware Access Log

Émet un log structuré de catégorie ACCESS pour chaque requête HTTP entrante.
Collecte les métriques Prometheus (REQUEST_COUNT, REQUEST_LATENCY) définies
dans app/common/metrics.py.

Routes exclues du logging : /health, /metrics (trop de bruit).
"""
import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_category_logger, LogCategory, request_id_var, username_var
from app.common.metrics import REQUEST_COUNT, REQUEST_LATENCY

# Logger dédié aux access logs
access_logger = get_category_logger("app.access", LogCategory.ACCESS)

# Routes exclues du logging (bruit)
EXCLUDED_PATHS = frozenset({"/health", "/metrics", "/favicon.ico"})


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware Starlette qui :
    1. Émet un log ACCESS structuré pour chaque requête HTTP
    2. Collecte REQUEST_COUNT et REQUEST_LATENCY (Prometheus)

    Les champs request_id et user_id sont automatiquement ajoutés
    par le StructuredJSONFormatter via les ContextVars (Phase 2).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Traite la requête, mesure la durée et émet le log ACCESS."""
        path = request.url.path

        # Exclure les routes bruyantes
        if path in EXCLUDED_PATHS:
            return await call_next(request)

        method = request.method
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("User-Agent", "")

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Normaliser le path pour les métriques (éviter la cardinalité infinie)
            # Ex: /api/admin/users/550e8400-... → /api/admin/users/{id}
            metric_path = self._normalize_path(path)

            # Collecter les métriques Prometheus
            REQUEST_COUNT.labels(
                endpoint=metric_path,
                method=method,
                status=str(status_code),
            ).inc()
            REQUEST_LATENCY.labels(endpoint=metric_path).observe(duration_ms / 1000)

            # Émettre le log ACCESS structuré
            log_level = logging.WARNING if status_code >= 400 else logging.INFO
            access_logger.log(
                log_level,
                "%s %s → %s (%.1fms)",
                method,
                path,
                status_code,
                duration_ms,
                extra={
                    "context": {
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": round(duration_ms, 1),
                        "ip_address": client_ip,
                        "user_agent": user_agent[:200],
                        "request_id": request_id_var.get(),
                        "username": username_var.get(),
                    }
                },
            )

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """
        Normalise le path pour les labels Prometheus.

        Remplace les segments UUID ou numériques par {id}
        pour éviter une cardinalité infinie sur les métriques.

        Exemples :
            /api/admin/users/550e8400-... → /api/admin/users/{id}
            /api/conversations/123       → /api/conversations/{id}
        """
        parts = path.strip("/").split("/")
        normalized = []
        for part in parts:
            # Détecter les UUID (32 hex + tirets) ou les nombres
            if len(part) >= 32 and "-" in part:
                normalized.append("{id}")
            elif part.isdigit():
                normalized.append("{id}")
            else:
                normalized.append(part)
        return "/" + "/".join(normalized)
