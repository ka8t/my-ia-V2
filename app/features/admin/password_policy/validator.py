"""
Validateur de mot de passe.

Valide les mots de passe selon les politiques configurees.
Peut etre utilise independamment des endpoints admin.
"""
import re
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_users.password import PasswordHelper

from app.models import PasswordPolicy, PasswordHistory
from app.features.admin.password_policy.repository import (
    PasswordPolicyRepository,
    PasswordHistoryRepository
)
from app.common.i18n import t

logger = logging.getLogger(__name__)

# Password hasher (meme instance que FastAPI Users : pwdlib/argon2id)
password_helper = PasswordHelper()


@dataclass
class ValidationResult:
    """Resultat de la validation d'un mot de passe."""
    is_valid: bool
    errors: List[str]
    strength_score: int
    suggestions: List[str]


class PasswordValidator:
    """
    Validateur de mot de passe selon une politique configurable.

    Peut etre utilise:
    - A l'inscription (validate_password)
    - Au changement de mot de passe (validate_password_change)
    - Pour afficher les exigences au frontend (get_requirements)
    """

    @staticmethod
    async def get_policy(db: AsyncSession, policy_name: str = "default") -> Optional[PasswordPolicy]:
        """
        Recupere une politique par son nom.

        Args:
            db: Session de base de donnees
            policy_name: Nom de la politique (defaut: "default")

        Returns:
            Politique ou None si non trouvee
        """
        policy = await PasswordPolicyRepository.get_by_name(db, policy_name)
        if not policy and policy_name != "default":
            # Fallback sur default
            policy = await PasswordPolicyRepository.get_default(db)
        return policy

    @staticmethod
    def validate_against_policy(
        password: str, policy: PasswordPolicy, lang: str = "fr"
    ) -> Tuple[bool, List[str]]:
        """
        Valide un mot de passe contre une politique.

        Args:
            password: Mot de passe en clair
            policy: Politique a appliquer
            lang: Langue pour les messages d'erreur

        Returns:
            Tuple (is_valid, errors)
        """
        errors: List[str] = []

        # Longueur minimale
        if len(password) < policy.min_length:
            errors.append(t("password_min_length", lang, min_length=policy.min_length))

        # Longueur maximale
        if len(password) > policy.max_length:
            errors.append(t("password_max_length", lang, max_length=policy.max_length))

        # Majuscule
        if policy.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append(t("password_require_uppercase", lang))

        # Minuscule
        if policy.require_lowercase and not re.search(r'[a-z]', password):
            errors.append(t("password_require_lowercase", lang))

        # Chiffre
        if policy.require_digit and not re.search(r'\d', password):
            errors.append(t("password_require_digit", lang))

        # Caractere special
        if policy.require_special:
            special_chars = policy.special_characters
            # Echapper les caracteres speciaux pour regex
            escaped = re.escape(special_chars)
            if not re.search(f'[{escaped}]', password):
                errors.append(t("password_require_special", lang, special_chars=special_chars))

        return len(errors) == 0, errors

    @staticmethod
    def calculate_strength(password: str, policy: PasswordPolicy) -> int:
        """
        Calcule un score de robustesse (0-100).

        Args:
            password: Mot de passe en clair
            policy: Politique de reference

        Returns:
            Score de 0 a 100
        """
        score = 0
        max_score = 100

        # Longueur (0-30 points)
        length_score = min(30, len(password) * 2)
        score += length_score

        # Majuscules (0-15 points)
        uppercase_count = len(re.findall(r'[A-Z]', password))
        score += min(15, uppercase_count * 5)

        # Minuscules (0-15 points)
        lowercase_count = len(re.findall(r'[a-z]', password))
        score += min(15, lowercase_count * 3)

        # Chiffres (0-15 points)
        digit_count = len(re.findall(r'\d', password))
        score += min(15, digit_count * 5)

        # Caracteres speciaux (0-25 points)
        special_chars = policy.special_characters
        escaped = re.escape(special_chars)
        special_count = len(re.findall(f'[{escaped}]', password))
        score += min(25, special_count * 8)

        # Bonus pour variete (mixte de types)
        has_upper = bool(re.search(r'[A-Z]', password))
        has_lower = bool(re.search(r'[a-z]', password))
        has_digit = bool(re.search(r'\d', password))
        has_special = bool(re.search(f'[{escaped}]', password))
        variety = sum([has_upper, has_lower, has_digit, has_special])

        # Penalite si pas assez de variete
        if variety < 3:
            score = int(score * 0.7)
        elif variety == 4:
            score = min(100, int(score * 1.1))

        return min(max_score, score)

    @staticmethod
    def get_suggestions(
        password: str, policy: PasswordPolicy, errors: List[str], lang: str = "fr"
    ) -> List[str]:
        """
        Genere des suggestions pour ameliorer le mot de passe.

        Args:
            password: Mot de passe en clair
            policy: Politique de reference
            errors: Erreurs deja detectees
            lang: Langue pour les messages

        Returns:
            Liste de suggestions
        """
        suggestions: List[str] = []

        # Si trop court
        if len(password) < policy.min_length:
            diff = policy.min_length - len(password)
            suggestions.append(t("password_suggest_add_chars", lang, diff=diff))

        # Si pas assez de variete
        has_upper = bool(re.search(r'[A-Z]', password))
        has_lower = bool(re.search(r'[a-z]', password))
        has_digit = bool(re.search(r'\d', password))
        special_chars = policy.special_characters
        escaped = re.escape(special_chars)
        has_special = bool(re.search(f'[{escaped}]', password))

        if not has_upper and policy.require_uppercase:
            suggestions.append(t("password_suggest_uppercase", lang))
        if not has_lower and policy.require_lowercase:
            suggestions.append(t("password_suggest_lowercase", lang))
        if not has_digit and policy.require_digit:
            suggestions.append(t("password_suggest_digit", lang))
        if not has_special and policy.require_special:
            suggestions.append(t("password_suggest_special", lang, special_chars=special_chars[:10] + "..."))

        # Suggestions de securite generale
        if len(password) < 12:
            suggestions.append(t("password_suggest_length", lang))

        # Detecter les patterns faibles
        if re.search(r'(.)\1{2,}', password):
            suggestions.append(t("password_suggest_no_repeat", lang))
        if re.search(r'(012|123|234|345|456|567|678|789|890)', password):
            suggestions.append(t("password_suggest_no_sequence_digits", lang))
        if re.search(r'(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)', password.lower()):
            suggestions.append(t("password_suggest_no_sequence_letters", lang))

        return suggestions

    @classmethod
    async def validate_password(
        cls,
        db: AsyncSession,
        password: str,
        policy_name: str = "default",
        lang: str = "fr"
    ) -> ValidationResult:
        """
        Valide un mot de passe contre une politique.

        Args:
            db: Session de base de donnees
            password: Mot de passe en clair
            policy_name: Nom de la politique a utiliser
            lang: Langue pour les messages

        Returns:
            ValidationResult avec is_valid, errors, strength_score, suggestions
        """
        policy = await cls.get_policy(db, policy_name)

        if not policy:
            # Politique par defaut en memoire si rien en DB
            logger.warning(t("password_no_policy_found", lang))
            policy = PasswordPolicy(
                name="default",
                min_length=8,
                max_length=128,
                require_uppercase=True,
                require_lowercase=True,
                require_digit=True,
                require_special=True,
                special_characters="!@#$%^&*()_+-=[]{}|;:,.<>?"
            )

        is_valid, errors = cls.validate_against_policy(password, policy, lang)
        strength = cls.calculate_strength(password, policy)
        suggestions = cls.get_suggestions(password, policy, errors, lang)

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            strength_score=strength,
            suggestions=suggestions
        )

    @classmethod
    async def validate_password_change(
        cls,
        db: AsyncSession,
        user_id,
        new_password: str,
        policy_name: str = "default",
        lang: str = "fr"
    ) -> ValidationResult:
        """
        Valide un changement de mot de passe (inclut verification historique).

        Args:
            db: Session de base de donnees
            user_id: UUID de l'utilisateur
            new_password: Nouveau mot de passe en clair
            policy_name: Nom de la politique a utiliser
            lang: Langue pour les messages

        Returns:
            ValidationResult
        """
        # D'abord valider contre la politique
        result = await cls.validate_password(db, new_password, policy_name, lang)

        if not result.is_valid:
            return result

        # Ensuite verifier l'historique
        policy = await cls.get_policy(db, policy_name)
        if policy and policy.history_count > 0:
            history = await PasswordHistoryRepository.get_user_history(
                db, user_id, limit=policy.history_count
            )

            for entry in history:
                verified, _ = password_helper.verify_and_update(new_password, entry.hashed_password)
                if verified:
                    result.is_valid = False
                    result.errors.append(
                        t("password_history_check", lang, history_count=policy.history_count)
                    )
                    break

        return result

    @classmethod
    async def get_requirements(cls, db: AsyncSession, policy_name: str = "default") -> dict:
        """
        Retourne les exigences de la politique pour le frontend.

        Args:
            db: Session de base de donnees
            policy_name: Nom de la politique

        Returns:
            Dictionnaire des exigences
        """
        policy = await cls.get_policy(db, policy_name)

        if not policy:
            # Valeurs par defaut
            return {
                "min_length": 8,
                "max_length": 128,
                "require_uppercase": True,
                "require_lowercase": True,
                "require_digit": True,
                "require_special": True,
                "special_characters": "!@#$%^&*()_+-=[]{}|;:,.<>?",
                "expire_days": 0,
                "history_count": 0
            }

        return {
            "min_length": policy.min_length,
            "max_length": policy.max_length,
            "require_uppercase": policy.require_uppercase,
            "require_lowercase": policy.require_lowercase,
            "require_digit": policy.require_digit,
            "require_special": policy.require_special,
            "special_characters": policy.special_characters,
            "expire_days": policy.expire_days,
            "history_count": policy.history_count
        }
