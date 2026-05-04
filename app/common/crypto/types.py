"""
Types SQLAlchemy personnalisés pour le chiffrement.

Fournit un type EncryptedString qui chiffre/déchiffre automatiquement
les données lors de la lecture/écriture en base.
"""
from typing import Any, Optional

from sqlalchemy import Text, TypeDecorator

from app.common.crypto.encryption import get_encryption_service


class EncryptedString(TypeDecorator):
    """
    Type SQLAlchemy qui chiffre automatiquement les chaînes.

    Utilise AES-256-GCM pour le chiffrement/déchiffrement transparent.
    Les données sont stockées en base sous forme chiffrée (base64).

    Usage dans un modèle:
        class User(Base):
            first_name = Column(EncryptedString(), nullable=True)
            phone = Column(EncryptedString(), nullable=True)

    Le chiffrement/déchiffrement est automatique:
        user.first_name = "Jean"  # Stocké chiffré
        print(user.first_name)    # Affiché "Jean" (déchiffré)
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """
        Chiffre la valeur avant insertion en base.

        Args:
            value: Valeur en clair à stocker
            dialect: Dialecte SQL (non utilisé)

        Returns:
            Valeur chiffrée en base64 ou None
        """
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        if not value:
            return ""

        service = get_encryption_service()
        return service.encrypt(value)

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """
        Déchiffre la valeur lue depuis la base.

        Args:
            value: Valeur chiffrée depuis la base
            dialect: Dialecte SQL (non utilisé)

        Returns:
            Valeur déchiffrée ou None
        """
        if value is None:
            return None

        if not value:
            return ""

        service = get_encryption_service()
        return service.decrypt(value)


class EncryptedStringSearchable(TypeDecorator):
    """
    Type pour les champs chiffrés avec index de recherche.

    Ce type est identique à EncryptedString mais sert de marqueur
    pour indiquer qu'un champ doit avoir un index de recherche associé.

    Les colonnes d'index (*_blind_index, *_search) doivent être
    gérées manuellement dans le repository/service.

    Usage:
        class User(Base):
            # Champ chiffré avec recherche exacte (blind index)
            phone = Column(EncryptedStringSearchable(), nullable=True)
            phone_blind_index = Column(String(64), index=True)

            # Champ chiffré avec recherche partielle (trigrammes)
            first_name = Column(EncryptedStringSearchable(), nullable=True)
            first_name_search = Column(Text())  # Index trigrammes
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """Chiffre la valeur avant insertion en base."""
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        if not value:
            return ""

        service = get_encryption_service()
        return service.encrypt(value)

    def process_result_value(self, value: Optional[str], dialect: Any) -> Optional[str]:
        """Déchiffre la valeur lue depuis la base."""
        if value is None:
            return None

        if not value:
            return ""

        service = get_encryption_service()
        return service.decrypt(value)
