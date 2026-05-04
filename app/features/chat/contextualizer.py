"""
Service de contextualisation des requetes pour sources externes

Reformule les questions de suivi en questions autonomes en utilisant
l'historique de la conversation.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.conversations.repository import ConversationRepository
from app.common.utils.ollama import generate_response
from app.common.utils.rag_config import get_rag_config

logger = logging.getLogger(__name__)

CONTEXTUALIZE_PROMPT = """Tu es un assistant qui reformule les questions de suivi en questions autonomes.

Historique de la conversation :
{history}

Question actuelle de l'utilisateur : "{query}"

Si la question fait reference a des elements mentionnes dans l'historique (pronoms comme "il", "elle", "l'", "ca", etc.), reformule-la pour qu'elle soit comprehensible sans contexte.

Si la question est deja autonome et claire, retourne-la telle quelle.

Retourne UNIQUEMENT la question reformulee, sans explication."""


class QueryContextualizer:
    """Service pour contextualiser les requetes avec l'historique conversationnel"""

    @staticmethod
    def _needs_contextualization(query: str) -> bool:
        """
        Detecte si la requete a besoin de contexte (question de suivi).

        Args:
            query: Requete de l'utilisateur

        Returns:
            True si la requete semble etre une question de suivi
        """
        query_lower = query.lower().strip()
        words = query_lower.split()

        # Requetes courtes (< 12 mots) sont candidates a la contextualisation
        short_query = len(words) < 12

        # Pronoms et articles qui referencent un element precedent
        referencing_patterns = [
            " l'", " le ", " la ", " les ", " il ", " elle ", " ca ",
            " celui", " celle", " ceux", " cet ", " cette ", " ces ",
            "qui l'", "qui l ", "qu'il", "qu'elle", " y ", " en ",
            " son ", " sa ", " ses ", " leur ", " leurs ",
            "l'epoque", "l epoque", "l'histoire", "l'auteur", "l'architecte",
            "du projet", "de l'", "de l ", "des intervenants"
        ]
        has_reference = any(p in query_lower for p in referencing_patterns)

        # Requetes qui commencent par des mots de continuation
        continuation_starters = ["et ", "mais ", "donc ", "or ", "car ", "puis "]
        starts_with_continuation = any(query_lower.startswith(s) for s in continuation_starters)

        # Requetes vagues sans sujet specifie
        vague_requests = [
            "donne-moi", "donne moi", "dis-moi", "dis moi",
            "explique-moi", "explique moi", "parle-moi", "parle moi",
            "plus de details", "plus d'info", "continue", "developpe",
            "détaille", "précise", "approfondi", "approfondir",
            "résume", "simplifie", "clarifie",
            "je te parle", "je parle de"
        ]
        is_vague = any(v in query_lower for v in vague_requests)

        # Si la requete contient un nom propre (majuscule), elle est autonome
        # Sauf si c'est le premier mot (debut de phrase)
        has_proper_noun = any(w[0].isupper() for w in query.split()[1:] if len(w) > 1)

        # Une requete est autonome si elle a un nom propre (sujet explicite)
        is_autonomous = has_proper_noun

        # Besoin de contexte si :
        # - Reference pronominale/contextuelle OU
        # - Commence par mot de continuation OU
        # - Requete vague (sans nom propre)
        # ET n'est pas autonome ET est courte
        needs_context = (has_reference or starts_with_continuation or (is_vague and not has_proper_noun)) and short_query
        return needs_context and not is_autonomous

    @staticmethod
    async def contextualize(
        db: AsyncSession,
        query: str,
        conversation_id: Optional[str],
        user_id: Optional[str],
        max_turns: int = 5
    ) -> str:
        """
        Contextualise une requete avec l'historique de conversation.

        Args:
            db: Session DB
            query: Requete originale
            conversation_id: ID de la conversation (session_id)
            user_id: ID de l'utilisateur
            max_turns: Nombre max d'echanges a inclure (x2 pour user+assistant)

        Returns:
            Requete contextualisee (ou originale si pas besoin)
        """
        # Verifier si contextualisation necessaire
        if not QueryContextualizer._needs_contextualization(query):
            logger.debug(f"Query doesn't need contextualization: {query[:50]}...")
            return query

        # Pas de conversation = pas de contexte
        if not conversation_id or not user_id:
            return query

        try:
            # Charger la conversation avec ses messages
            conversation = await ConversationRepository.get_by_id(
                db, UUID(conversation_id), UUID(user_id)
            )

            if not conversation or not conversation.messages:
                return query

            # Prendre les N derniers messages (avant le message actuel)
            # x2 car on compte user+assistant comme 1 echange
            recent_messages = conversation.messages[-(max_turns * 2):]

            if len(recent_messages) < 2:
                return query

            # Construire l'historique formate
            history_lines = []
            for msg in recent_messages:
                role = "User" if msg.sender_type == "user" else "Assistant"
                # Tronquer les messages longs
                content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                history_lines.append(f"- {role}: {content}")

            history_text = "\n".join(history_lines)

            # Reformuler via Ollama
            prompt = CONTEXTUALIZE_PROMPT.format(
                history=history_text,
                query=query
            )

            rag_config = await get_rag_config(db)

            contextualized = await generate_response(
                prompt,
                system_prompt="Tu reformules des questions de maniere concise.",
                context=None,
                stream=False,
                temperature=0.1,  # Basse pour etre precis
                model=rag_config.llm_model
            )

            # Nettoyer la reponse
            contextualized = contextualized.strip().strip('"').strip()

            # Verifier que la reformulation est valide
            if contextualized and len(contextualized) > len(query) * 0.5:
                logger.info(f"Query contextualized: '{query}' -> '{contextualized}'")
                return contextualized

            return query

        except Exception as e:
            logger.warning(f"Error contextualizing query: {e}")
            return query
