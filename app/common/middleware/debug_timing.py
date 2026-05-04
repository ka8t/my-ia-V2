"""
Middleware Debug Timing

Injecte des headers X-Debug-* sur chaque réponse API quand activé.
Activé/désactivé à chaud via _runtime_overrides['debug_timing_headers'].
"""
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class DebugTimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware Starlette qui ajoute des headers de debug sur les réponses.

    Headers injectés :
    - X-Debug-Total-Ms : temps total de traitement en millisecondes
    - X-Debug-Path : chemin de la requête
    - X-Debug-Method : méthode HTTP

    Zéro overhead quand désactivé (vérification rapide du flag runtime).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Traite la requête et ajoute les headers debug si activé."""
        # Import dans dispatch() pour éviter les imports circulaires au démarrage
        from app.features.admin.config.service import _runtime_overrides

        if not _runtime_overrides.get('debug_timing_headers', False):
            return await call_next(request)

        start_time = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        response.headers["X-Debug-Total-Ms"] = f"{elapsed_ms:.2f}"
        response.headers["X-Debug-Path"] = request.url.path
        response.headers["X-Debug-Method"] = request.method

        return response
