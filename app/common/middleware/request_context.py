"""
Middleware de contexte de requête

Enrichit chaque requête HTTP avec un request_id (UUID v4) et extrait
le user_id depuis le JWT si présent. Ces valeurs sont stockées dans
les ContextVars de app.core.logging et automatiquement incluses dans
tous les logs JSON émis pendant le traitement de la requête.

Le header X-Request-Id est ajouté à la réponse pour la corrélation.
"""
import uuid

import jwt
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import (
    request_id_var, user_id_var, username_var, session_id_var,
    ip_address_var, user_agent_var,
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware Starlette qui injecte le contexte de requête dans les ContextVars.

    Fonctionnement :
    1. Génère un request_id unique (UUID v4) pour chaque requête
    2. Extrait le user_id du JWT (header Authorization: Bearer xxx)
    3. Stocke request_id et user_id dans les ContextVars
    4. Ajoute X-Request-Id dans les headers de réponse

    Le StructuredJSONFormatter lit ces ContextVars automatiquement,
    ce qui enrichit tous les logs émis pendant la requête.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Traite la requête en injectant le contexte dans les ContextVars."""
        # Générer un request_id unique
        request_id = str(uuid.uuid4())
        request_id_token = request_id_var.set(request_id)

        # Extraire user_id du JWT si présent
        user_id_token = None
        user_id = self._extract_user_id(request)
        if user_id:
            user_id_token = user_id_var.set(user_id)

        # Extraire session_id du header ou cookie si présent
        session_id_token = None
        session_id = request.headers.get("X-Session-Id")
        if session_id:
            session_id_token = session_id_var.set(session_id)

        # Extraire l'adresse IP du client
        ip_address_token = None
        client_ip = request.client.host if request.client else None
        if client_ip:
            ip_address_token = ip_address_var.set(client_ip)

        # Extraire le User-Agent du header
        user_agent_token = None
        user_agent = request.headers.get("User-Agent")
        if user_agent:
            user_agent_token = user_agent_var.set(user_agent)

        # Initialiser username_var à None pour pouvoir le reset en fin de requête.
        # La valeur sera définie par les deps auth (get_current_admin_user, etc.)
        username_token = username_var.set(None)

        try:
            response = await call_next(request)

            # Ajouter X-Request-Id dans les headers de réponse
            response.headers["X-Request-Id"] = request_id

            return response
        finally:
            # Restaurer les ContextVars (nettoyage)
            request_id_var.reset(request_id_token)
            if user_id_token is not None:
                user_id_var.reset(user_id_token)
            username_var.reset(username_token)
            if session_id_token is not None:
                session_id_var.reset(session_id_token)
            if ip_address_token is not None:
                ip_address_var.reset(ip_address_token)
            if user_agent_token is not None:
                user_agent_var.reset(user_agent_token)

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        """
        Extrait le user_id depuis le token JWT dans le header Authorization.

        Décode le JWT sans vérifier la signature (seul le sub est lu).
        La validation complète est faite par FastAPI Users en aval.

        Returns:
            user_id (str) ou None si pas de token ou token invalide.
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Retirer "Bearer "

        try:
            # Décoder sans vérification de signature pour extraire le sub
            # La validation complète est faite par le système d'auth FastAPI Users
            payload = jwt.decode(
                token,
                options={"verify_signature": False},
                algorithms=["HS256"],
            )
            return payload.get("sub")
        except (jwt.InvalidTokenError, jwt.DecodeError):
            return None
