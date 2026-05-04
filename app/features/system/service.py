"""
Service SystemConfig - Gestion de la configuration systeme dynamique.

Ce service permet de lire et modifier les parametres de configuration
stockes en base de donnees.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemConfig

logger = logging.getLogger(__name__)


class SystemConfigService:
    """Service de gestion de la configuration systeme."""

    # Cache en memoire pour eviter les requetes repetees
    _cache: Dict[str, Any] = {}
    _cache_loaded: bool = False

    def __init__(self, session: AsyncSession):
        self.session = session

    # === Lecture ===

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Recupere une valeur de configuration.

        Args:
            key: Cle de configuration (ex: 'storage.allowed_mime_types')
            default: Valeur par defaut si la cle n'existe pas

        Returns:
            Valeur convertie selon son type
        """
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if not config:
            return default

        return self._convert_value(config.value, config.value_type)

    async def get_by_category(self, category: str) -> Dict[str, Any]:
        """
        Recupere toutes les configurations d'une categorie.

        Args:
            category: Categorie (storage, security, rag, general)

        Returns:
            Dict avec les cles et valeurs converties
        """
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.category == category)
        )
        configs = result.scalars().all()

        return {
            config.key: self._convert_value(config.value, config.value_type)
            for config in configs
        }

    async def get_all(self) -> List[Dict[str, Any]]:
        """
        Recupere toutes les configurations.

        Returns:
            Liste de dicts avec toutes les infos
        """
        result = await self.session.execute(
            select(SystemConfig).order_by(SystemConfig.category, SystemConfig.key)
        )
        configs = result.scalars().all()

        return [
            {
                "id": config.id,
                "key": config.key,
                "value": self._convert_value(config.value, config.value_type),
                "raw_value": config.value,
                "value_type": config.value_type,
                "category": config.category,
                "description": config.description,
                "is_sensitive": config.is_sensitive,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None,
            }
            for config in configs
        ]

    async def get_categories(self) -> List[str]:
        """Retourne la liste des categories distinctes."""
        result = await self.session.execute(
            select(SystemConfig.category).distinct().order_by(SystemConfig.category)
        )
        return [row[0] for row in result.all()]

    async def get_by_prefix(self, prefix: str) -> Dict[str, Any]:
        """
        Charge toutes les configs d'un préfixe en UNE requête SQL.

        Optimisation pour éviter N requêtes individuelles.
        Ex: get_by_prefix("rag.") retourne toutes les clés commençant par "rag."

        Args:
            prefix: Préfixe des clés (ex: "rag.", "perf.", "llm.ollama.")

        Returns:
            Dict {key: converted_value}
        """
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.key.like(f"{prefix}%"))
        )
        configs = result.scalars().all()

        return {
            config.key: self._convert_value(config.value, config.value_type)
            for config in configs
        }

    # === Ecriture ===

    async def set(
        self,
        key: str,
        value: Any,
        updated_by: Optional[UUID] = None,
        value_type: Optional[str] = None,
        category: Optional[str] = None,
        is_sensitive: bool = False,
    ) -> bool:
        """
        Met a jour une valeur de configuration (upsert).

        Si la cle n'existe pas, elle est creee automatiquement.

        Args:
            key: Cle de configuration
            value: Nouvelle valeur
            updated_by: UUID de l'utilisateur qui fait la modification
            value_type: Type de valeur (pour creation, defaut: deduit automatiquement)
            category: Categorie (pour creation, defaut: deduit du prefix de la cle)
            is_sensitive: Marquer comme sensible (pour creation)

        Returns:
            True si mise a jour/creation reussie
        """
        # Recuperer la config existante pour connaitre le type
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if not config:
            # Creer la cle si elle n'existe pas
            inferred_type = value_type or self._infer_type(value)
            inferred_category = category or key.split(".")[0] if "." in key else "general"

            config = SystemConfig(
                key=key,
                value=self._to_string(value, inferred_type),
                value_type=inferred_type,
                category=inferred_category,
                is_sensitive=is_sensitive,
                updated_by=updated_by,
            )
            self.session.add(config)
            await self.session.commit()
            logger.info(f"Config created: {key} = {str(value)[:50]}...")
            return True

        # Convertir la valeur en string pour stockage
        str_value = self._to_string(value, config.value_type)

        # Mettre a jour
        await self.session.execute(
            update(SystemConfig)
            .where(SystemConfig.key == key)
            .values(value=str_value, updated_by=updated_by)
        )
        await self.session.commit()

        # Invalider le cache
        self._cache.pop(key, None)

        logger.info(f"Config updated: {key} = {str_value[:50]}...")
        return True

    def _infer_type(self, value: Any) -> str:
        """Deduit le type de valeur pour le stockage."""
        if isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, (list, dict)):
            return "json"
        return "string"

    async def create(
        self,
        key: str,
        value: Any,
        value_type: str = "string",
        category: str = "general",
        description: Optional[str] = None,
        is_sensitive: bool = False,
        updated_by: Optional[UUID] = None,
    ) -> SystemConfig:
        """
        Cree une nouvelle configuration.

        Args:
            key: Cle unique
            value: Valeur
            value_type: Type (string, int, float, bool, json, list)
            category: Categorie
            description: Description
            is_sensitive: Masquer dans les logs
            updated_by: UUID de l'utilisateur

        Returns:
            SystemConfig cree
        """
        str_value = self._to_string(value, value_type)

        config = SystemConfig(
            key=key,
            value=str_value,
            value_type=value_type,
            category=category,
            description=description,
            is_sensitive=is_sensitive,
            updated_by=updated_by,
        )

        self.session.add(config)
        await self.session.commit()
        await self.session.refresh(config)

        logger.info(f"Config created: {key}")
        return config

    async def delete(self, key: str) -> bool:
        """
        Supprime une configuration.

        Args:
            key: Cle a supprimer

        Returns:
            True si supprimee
        """
        result = await self.session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if not config:
            return False

        await self.session.delete(config)
        await self.session.commit()

        self._cache.pop(key, None)
        logger.info(f"Config deleted: {key}")
        return True

    # === Helpers specifiques ===

    async def get_allowed_mime_types(self) -> List[str]:
        """Retourne la liste des types MIME autorises."""
        value = await self.get("storage.allowed_mime_types", "")
        return self._parse_list_value(value)

    async def get_blocked_extensions(self) -> List[str]:
        """Retourne la liste des extensions bloquees."""
        value = await self.get("storage.blocked_extensions", "")
        return self._parse_list_value(value)

    def _parse_list_value(self, value: Any) -> List[str]:
        """Parse une valeur qui peut être une liste, JSON, ou CSV."""
        if isinstance(value, list):
            return value
        if not value:
            return []
        str_value = str(value).strip()
        # Tenter de parser comme JSON si ça ressemble à une liste
        if str_value.startswith("["):
            import json
            try:
                parsed = json.loads(str_value)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed]
            except json.JSONDecodeError:
                # Format Python list repr: ['a', 'b'] - parser manuellement
                import ast
                try:
                    parsed = ast.literal_eval(str_value)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed]
                except (ValueError, SyntaxError):
                    pass
        # Fallback: split par virgule
        return [t.strip() for t in str_value.split(",") if t.strip()]

    async def get_max_file_size_bytes(self) -> int:
        """Retourne la taille max de fichier en bytes."""
        mb = await self.get("storage.max_file_size_mb", 50)
        return int(mb) * 1024 * 1024

    async def get_default_quota_bytes(self) -> int:
        """Retourne le quota par defaut en bytes."""
        mb = await self.get("storage.default_quota_mb", 100)
        return int(mb) * 1024 * 1024

    # === Conversion de types ===

    def _convert_value(self, value: str, value_type: str) -> Any:
        """Convertit une valeur string vers son type."""
        if value_type in ("int", "integer"):
            return int(value)
        elif value_type == "float":
            return float(value)
        elif value_type in ("bool", "boolean"):
            return value.lower() in ("true", "1", "yes", "on")
        elif value_type == "json":
            return json.loads(value)
        elif value_type == "list":
            return [item.strip() for item in value.split(",") if item.strip()]
        else:
            return value

    def _to_string(self, value: Any, value_type: str) -> str:
        """Convertit une valeur vers string pour stockage."""
        if value_type in ("bool", "boolean"):
            return "true" if value else "false"
        elif value_type == "json":
            return json.dumps(value)
        elif value_type == "list":
            if isinstance(value, list):
                return ",".join(str(v) for v in value)
            return str(value)
        else:
            return str(value)
