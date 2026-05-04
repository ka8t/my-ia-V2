"""
Classe de base pour les connecteurs de sources externes
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Awaitable

from app.features.sources.schemas import ContextResult

logger = logging.getLogger(__name__)

# Type pour le callback de progression : (current, total, message) -> None
ProgressCallback = Optional[Callable[[int, int, str], Awaitable[None]]]


class BaseConnector(ABC):
    """
    Interface de base pour tous les connecteurs de sources.

    Chaque connecteur doit implementer :
    - search() : recherche de contexte
    - health_check() : verification de la connexion
    """

    def __init__(
        self,
        config: Dict[str, Any],
        timeout: int = 30,
        max_results: int = 5,
        source_name: str = "unknown",
        display_name: Optional[str] = None
    ):
        """
        Args:
            config: Configuration specifique au connecteur
            timeout: Timeout en secondes
            max_results: Nombre max de resultats
            source_name: Nom technique de la source (pour l'indexation)
            display_name: Nom d'affichage pour l'UI (si différent de source_name)
        """
        self.config = config
        self.timeout = timeout
        self.max_results = max_results
        self.source_name = source_name
        self.display_name = display_name or source_name

    @abstractmethod
    async def search(
        self,
        query: str,
        progress_callback: ProgressCallback = None
    ) -> List[ContextResult]:
        """
        Recherche du contexte pertinent pour la query.

        Args:
            query: Question de l'utilisateur
            progress_callback: Callback optionnel (current, total, message) pour le suivi

        Returns:
            Liste de resultats de contexte
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Verifie la connexion a la source.

        Returns:
            Dict avec 'status' ('healthy'|'unhealthy') et optionnellement 'error'
        """
        pass

    def validate_config(self) -> bool:
        """
        Valide la configuration du connecteur.

        Returns:
            True si la config est valide
        """
        return True
