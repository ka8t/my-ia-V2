"""Module geo - Endpoints publics pour pays et villes."""
from app.features.geo.router import router
from app.features.geo.service import GeoService

__all__ = ["router", "GeoService"]
