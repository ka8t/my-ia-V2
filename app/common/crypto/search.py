"""
Service d'indexation pour la recherche sur données chiffrées.

Fournit:
- Blind Index (HMAC-SHA256) pour la recherche exacte
- Trigrammes hashés pour la recherche partielle (LIKE)
"""
import hashlib
import hmac
import logging
import re
import unicodedata
from typing import Optional, Set, List

from app.common.crypto.key_manager import get_key_manager

logger = logging.getLogger(__name__)


class SearchIndexService:
    """
    Service de création d'index de recherche pour données chiffrées.

    Deux types d'index sont supportés:

    1. Blind Index (HMAC-SHA256):
       - Pour la recherche EXACTE (WHERE blind_index = ?)
       - Déterministe: même valeur → même hash
       - Impossible de retrouver la valeur originale

    2. Trigrammes hashés:
       - Pour la recherche PARTIELLE (LIKE %valeur%)
       - Découpe en fragments de 3 caractères
       - Chaque trigramme est hashé individuellement
       - Stocké comme JSON array de hashes
    """

    TRIGRAM_SIZE = 3
    # Préfixe pour distinguer les types d'index
    BLIND_INDEX_PREFIX = "bi:"
    TRIGRAM_PREFIX = "tg:"

    def __init__(self, hmac_key: Optional[bytes] = None):
        """
        Initialise le service d'indexation.

        Args:
            hmac_key: Clé HMAC de 32 bytes. Si None, utilise KeyManager.
        """
        if hmac_key is None:
            hmac_key = get_key_manager().hmac_key

        self._hmac_key = hmac_key

    def _normalize(self, value: str) -> str:
        """
        Normalise une valeur pour l'indexation.

        - Convertit en minuscules
        - Supprime les accents
        - Supprime les espaces multiples
        - Supprime la ponctuation

        Args:
            value: Valeur à normaliser

        Returns:
            Valeur normalisée
        """
        if not value:
            return ""

        # Minuscules
        normalized = value.lower()

        # Supprime les accents (NFD décompose, on filtre les diacritiques)
        normalized = unicodedata.normalize('NFD', normalized)
        normalized = ''.join(
            char for char in normalized
            if unicodedata.category(char) != 'Mn'
        )

        # Supprime la ponctuation et caractères spéciaux
        normalized = re.sub(r'[^\w\s]', '', normalized)

        # Normalise les espaces
        normalized = ' '.join(normalized.split())

        return normalized

    def _hmac_hash(self, value: str) -> str:
        """
        Calcule le HMAC-SHA256 d'une valeur.

        Args:
            value: Valeur à hasher

        Returns:
            Hash hexadécimal de 64 caractères
        """
        return hmac.new(
            self._hmac_key,
            value.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def create_blind_index(self, value: str) -> str:
        """
        Crée un blind index pour la recherche exacte.

        Le blind index permet de chercher une valeur exacte sans
        pouvoir la retrouver. Utile pour: email, téléphone, etc.

        Args:
            value: Valeur à indexer

        Returns:
            Hash HMAC-SHA256 hexadécimal (64 caractères)
        """
        if not value:
            return ""

        normalized = self._normalize(value)
        return self._hmac_hash(normalized)

    def create_trigrams(self, value: str) -> Set[str]:
        """
        Génère les trigrammes d'une valeur.

        Un trigramme est une séquence de 3 caractères consécutifs.
        Exemple: "paris" → {"par", "ari", "ris"}

        Args:
            value: Valeur à découper

        Returns:
            Ensemble de trigrammes
        """
        if not value or len(value) < self.TRIGRAM_SIZE:
            return set()

        normalized = self._normalize(value)

        if len(normalized) < self.TRIGRAM_SIZE:
            return set()

        trigrams = set()
        for i in range(len(normalized) - self.TRIGRAM_SIZE + 1):
            trigram = normalized[i:i + self.TRIGRAM_SIZE]
            # Ignore les trigrammes avec espaces
            if ' ' not in trigram:
                trigrams.add(trigram)

        return trigrams

    def create_trigram_index(self, value: str) -> List[str]:
        """
        Cree un index de trigrammes hashes pour la recherche partielle.

        Chaque trigramme est hashe individuellement. Retourne une liste
        pour stockage en ARRAY PostgreSQL avec index GIN.

        Args:
            value: Valeur a indexer

        Returns:
            Liste de trigrammes hashes (16 caracteres chacun)
        """
        if not value:
            return []

        trigrams = self.create_trigrams(value)

        if not trigrams:
            return []

        # Hash chaque trigramme (16 premiers caracteres suffisent)
        hashed_trigrams = sorted([
            self._hmac_hash(tg)[:16]
            for tg in trigrams
        ])

        return hashed_trigrams

    def match_trigrams(self, query: str, stored_index: List[str]) -> bool:
        """
        Verifie si une requete correspond a un index de trigrammes.

        Tous les trigrammes de la requete doivent etre presents
        dans l'index stocke pour que la correspondance soit validee.

        Args:
            query: Terme de recherche
            stored_index: Liste de trigrammes hashes stockes

        Returns:
            True si tous les trigrammes de la requete sont trouves
        """
        if not query or not stored_index:
            return False

        # Genere les trigrammes hashes de la requete
        query_trigrams = self.create_trigrams(query)

        if not query_trigrams:
            # Requete trop courte, pas de trigrammes
            return False

        query_hashes = {
            self._hmac_hash(tg)[:16]
            for tg in query_trigrams
        }

        # Convertir en set pour la comparaison
        stored_hashes = set(stored_index)

        # Verifie que TOUS les trigrammes de la requete sont presents
        return query_hashes.issubset(stored_hashes)

    def search_score(self, query: str, stored_index: List[str]) -> float:
        """
        Calcule un score de pertinence pour une recherche.

        Le score est le ratio de trigrammes de la requete trouves
        dans l'index stocke.

        Args:
            query: Terme de recherche
            stored_index: Liste de trigrammes hashes stockes

        Returns:
            Score entre 0.0 (aucune correspondance) et 1.0 (correspondance parfaite)
        """
        if not query or not stored_index:
            return 0.0

        query_trigrams = self.create_trigrams(query)

        if not query_trigrams:
            return 0.0

        query_hashes = {
            self._hmac_hash(tg)[:16]
            for tg in query_trigrams
        }

        stored_hashes = set(stored_index)

        # Calcule le ratio de correspondance
        matches = len(query_hashes.intersection(stored_hashes))
        return matches / len(query_hashes)


# Instance singleton pour usage courant
_search_index_service: Optional[SearchIndexService] = None


def get_search_index_service() -> SearchIndexService:
    """
    Retourne l'instance singleton du service d'indexation.

    Returns:
        Instance de SearchIndexService
    """
    global _search_index_service
    if _search_index_service is None:
        _search_index_service = SearchIndexService()
    return _search_index_service


def update_user_search_indexes(
    user,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None
) -> None:
    """
    Met a jour les index de recherche pour un utilisateur.

    Cree les index necessaires pour permettre la recherche sur les
    donnees chiffrees (PII). Appeler cette fonction lors de:
    - L'inscription d'un nouvel utilisateur
    - La mise a jour du profil utilisateur

    Args:
        user: Instance User SQLAlchemy a modifier
        first_name: Prenom en clair (optionnel)
        last_name: Nom en clair (optionnel)
        phone: Telephone en clair (optionnel)
    """
    search_service = get_search_index_service()

    if first_name:
        user.first_name_search = search_service.create_trigram_index(first_name)
        logger.debug(f"Index trigramme first_name cree pour user {user.id}")

    if last_name:
        user.last_name_search = search_service.create_trigram_index(last_name)
        logger.debug(f"Index trigramme last_name cree pour user {user.id}")

    if phone:
        user.phone_blind_index = search_service.create_blind_index(phone)
        logger.debug(f"Blind index phone cree pour user {user.id}")
