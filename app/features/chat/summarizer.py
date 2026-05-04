"""
Résumé automatique des conversations longues

Génère un résumé condensé des messages anciens (hors fenêtre de contexte)
pour maintenir le contexte global dans les conversations longues sans
dépasser la limite de tokens du modèle LLM.
"""
import logging
from typing import List, Dict

from app.common.utils.ollama import generate_response

logger = logging.getLogger(__name__)

# Prompt de résumé en français
SUMMARY_PROMPT_FR = """Résume la conversation suivante en un paragraphe concis.
Conserve les points clés, les décisions prises et les informations importantes.
Ne perds aucun détail factuel utile pour la suite de la conversation.

Conversation :
{conversation}

Résumé :"""

# Prompt de résumé en anglais
SUMMARY_PROMPT_EN = """Summarize the following conversation in a concise paragraph.
Keep key points, decisions made, and important information.
Do not lose any factual detail useful for the rest of the conversation.

Conversation:
{conversation}

Summary:"""

SUMMARY_PROMPTS = {
    "fr": SUMMARY_PROMPT_FR,
    "en": SUMMARY_PROMPT_EN,
}


class ConversationSummarizer:
    """
    Génère des résumés condensés de conversations longues.

    Quand une conversation dépasse le seuil de messages configuré,
    les messages anciens (hors fenêtre) sont résumés en un paragraphe
    qui sera injecté dans le prompt LLM.
    """

    @staticmethod
    def _format_messages_for_summary(messages: List[Dict[str, str]]) -> str:
        """
        Formate les messages pour le prompt de résumé.

        Args:
            messages: Liste de messages [{"role": "user"|"assistant", "content": "..."}]

        Returns:
            Texte formaté pour le résumé
        """
        lines = []
        for msg in messages:
            role = "Utilisateur" if msg["role"] == "user" else "Assistant"
            # Tronquer les messages très longs pour le résumé
            content = msg["content"][:800]
            if len(msg["content"]) > 800:
                content += "..."
            lines.append(f"- {role} : {content}")
        return "\n".join(lines)

    @staticmethod
    async def summarize(
        messages: List[Dict[str, str]],
        model: str = "mistral",
        language: str = "fr"
    ) -> str:
        """
        Génère un résumé condensé d'une liste de messages.

        Args:
            messages: Messages à résumer [{"role": "user"|"assistant", "content": "..."}]
            model: Modèle LLM à utiliser
            language: Langue du résumé (fr/en)

        Returns:
            Résumé condensé en texte (~200 tokens)
        """
        if not messages:
            return ""

        try:
            formatted = ConversationSummarizer._format_messages_for_summary(messages)

            # Sélectionner le prompt dans la bonne langue
            lang = language.lower() if language and language.lower() in SUMMARY_PROMPTS else "fr"
            prompt_template = SUMMARY_PROMPTS[lang]
            prompt = prompt_template.format(conversation=formatted)

            summary = await generate_response(
                query=prompt,
                system_prompt="Tu résumes des conversations de manière concise et factuelle.",
                context=None,
                stream=False,
                temperature=0.1,  # Basse pour être précis et factuel
                model=model
            )

            # Nettoyer le résumé
            summary = summary.strip()

            logger.info(
                f"Conversation summary generated: {len(messages)} messages → "
                f"{len(summary)} chars (~{len(summary) // 4} tokens)"
            )
            return summary

        except Exception as e:
            logger.warning(f"Error generating conversation summary: {e}")
            return ""
