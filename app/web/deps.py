"""FastAPI dependencies for HTML routes (Phase 3.1.c).

- ``AuthRedirect`` — exception raised by ``require_web_auth`` when a route
  needs an authenticated session. ``main.py`` registers a handler that turns
  it into a 303 redirect to ``/web/login``.
- ``require_web_auth`` — dependency returning the session user dict.
"""
from __future__ import annotations

from fastapi import Request


class AuthRedirect(Exception):
    """Raised from a dependency when an HTML route needs auth.

    The corresponding handler in ``main.py`` returns a 303 redirect.
    """

    def __init__(self, location: str = "/web/login") -> None:
        self.location = location


def require_web_auth(request: Request) -> dict:
    """Return the session user dict; raise ``AuthRedirect`` if anonymous.

    Use as a FastAPI dependency::

        @app.get("/protected", response_class=HTMLResponse)
        async def page(user: dict = Depends(require_web_auth)):
            ...
    """
    user = request.session.get("user")
    if not user:
        raise AuthRedirect()
    return user
