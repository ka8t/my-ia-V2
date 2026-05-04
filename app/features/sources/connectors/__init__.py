"""
Connecteurs de sources externes

Chaque connecteur implemente l'interface BaseConnector.
"""
from app.features.sources.connectors.base import BaseConnector
from app.features.sources.connectors.mcp import MCPConnector
from app.features.sources.connectors.web import WebConnector
from app.features.sources.connectors.database import DatabaseConnector
from app.features.sources.connectors.api import ApiConnector

__all__ = ['BaseConnector', 'MCPConnector', 'WebConnector', 'DatabaseConnector', 'ApiConnector']
