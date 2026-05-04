"""
Service Chat

Logique métier pour le chat conversationnel avec RAG.
"""
import logging
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_chroma_client
from app.common.utils.chroma import search_context, search_corpus_context
from app.common.llm import get_provider, get_embeddings, generate_response
from app.common.utils.rag_config import get_rag_config, get_effective_rag_mode
from app.common.rag import TokenCompactor
from app.common.rag.compactor import CompactionConfig
from app.common.utils.sources import deduplicate_sources, enrich_context_with_display_names
from app.features.sources.context import SourceContextService
from app.features.chat.contextualizer import QueryContextualizer
from app.features.chat.topic_detector import TopicDetector
from app.features.chat.summarizer import ConversationSummarizer
from app.features.conversations.repository import ConversationRepository, MessageRepository
from app.features.system.service import SystemConfigService
from app.common.utils.timing_stats import timing_stats
from app.models import ConversationMode

logger = logging.getLogger(__name__)


def _build_system_content(
    system_prompt: str,
    context: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Construit le contenu du message system (prompt + contexte RAG).

    Args:
        system_prompt: Prompt système
        context: Contexte RAG optionnel

    Returns:
        Contenu formaté pour le message system
    """
    content = system_prompt

    if context:
        content += "\n\n**Contexte disponible :**\n\n"
        for i, ctx in enumerate(context, 1):
            source = ctx.get("metadata", {}).get("source", "Unknown")
            content += f"[Source {i}: {source}]\n{ctx['content']}\n\n"

    return content


def _generate_suggestions(
    diagnostics: Dict[str, Any],
    collection_name: str,
    collection_display_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Génère des suggestions basées sur les diagnostics RAG

    Args:
        diagnostics: Diagnostics retournés par search_context()
        collection_name: Nom technique de la collection ChromaDB
        collection_display_name: Nom d'affichage de la collection (optionnel)

    Returns:
        Liste de suggestions avec type, message et action optionnelle
    """
    suggestions = []
    # Utiliser le nom d'affichage si disponible, sinon le nom technique
    display_name = collection_display_name or collection_name

    # Cas 0: Erreur de recherche (ex: dimension mismatch)
    if diagnostics.get("error"):
        error_type = diagnostics.get("error_type", "search_error")
        error_msg = diagnostics.get("error", "Unknown error")

        if error_type == "dimension_mismatch":
            suggestions.append({
                "suggestion_type": "dimension_mismatch",
                "message": f"Incompatibilité de dimension d'embedding. Les documents de la collection '{display_name}' doivent être réindexés avec le modèle d'embedding actuel.",
                "action": None
            })
        else:
            suggestions.append({
                "suggestion_type": "search_error",
                "message": f"Erreur lors de la recherche : {error_msg}",
                "action": None
            })
        return suggestions

    # Cas 1: Collection vide
    if not diagnostics.get("has_documents"):
        suggestions.append({
            "suggestion_type": "add_documents",
            "message": f"La collection '{display_name}' ne contient aucun document. Ajoutez des documents pour enrichir les réponses.",
            "action": "open_upload"
        })
        return suggestions

    # Cas 2: Résultats filtrés par seuil de similarité
    if diagnostics.get("filtered_by_threshold", 0) > 0 and diagnostics.get("final_count", 0) == 0:
        threshold = diagnostics.get("similarity_threshold", 0.7)
        filtered_count = diagnostics.get("filtered_by_threshold", 0)
        suggestions.append({
            "suggestion_type": "lower_threshold",
            "message": f"{filtered_count} extrait(s) trouvé(s) mais filtré(s) car leur similarité est inférieure à {threshold}. Un administrateur peut ajuster le seuil dans les paramètres RAG.",
            "action": None
        })
        suggestions.append({
            "suggestion_type": "rephrase",
            "message": "Essayez de reformuler votre question avec des termes plus proches de vos documents.",
            "action": None
        })
        return suggestions

    # Cas 3: Pas de résultats du tout
    if diagnostics.get("total_found", 0) == 0:
        suggestions.append({
            "suggestion_type": "rephrase",
            "message": "Aucun document ne correspond à votre question. Essayez de reformuler avec d'autres termes.",
            "action": None
        })
        suggestions.append({
            "suggestion_type": "add_documents",
            "message": "Ajoutez des documents sur ce sujet à la collection.",
            "action": "open_upload"
        })

    return suggestions


def _determine_context_status(diagnostics: Dict[str, Any]) -> str:
    """
    Détermine le statut du contexte RAG

    Returns:
        "error", "ok", "empty", "filtered", ou "no_documents"
    """
    if diagnostics.get("error"):
        return "error"
    if not diagnostics.get("has_documents"):
        return "no_documents"
    if diagnostics.get("final_count", 0) == 0:
        if diagnostics.get("filtered_by_threshold", 0) > 0:
            return "filtered"
        return "empty"
    return "ok"


async def _get_collection_corpus_id(db: AsyncSession, collection_name: str):
    """
    Recupere le corpus_id d'une collection par son nom.

    Utilise la table pivot corpus_collections pour la relation N-to-N.
    Si la collection est dans plusieurs corpus, retourne le premier par priorite.

    Args:
        db: Session DB
        collection_name: Nom de la collection ChromaDB

    Returns:
        UUID du corpus ou None
    """
    from sqlalchemy import select
    from app.models import Collection, CorpusCollection

    try:
        # Chercher via la table pivot corpus_collections
        result = await db.execute(
            select(CorpusCollection.corpus_id)
            .join(Collection, Collection.id == CorpusCollection.collection_id)
            .where(Collection.name == collection_name)
            .order_by(CorpusCollection.priority)
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row
    except Exception as e:
        logger.error(f"Error fetching corpus_id for collection {collection_name}: {e}")
        return None


async def _search_with_corpus_fallback(
    query: str,
    user_id: Optional[str],
    db: AsyncSession,
    collection_name: str,
    top_k: Optional[int] = None
) -> Dict[str, Any]:
    """
    Recherche automatique: si la collection a un corpus, recherche multi-collection.

    Args:
        query: Requete utilisateur
        user_id: UUID user pour filtrage
        db: Session DB
        collection_name: Nom de la collection cible
        top_k: Nombre de résultats (optionnel, défaut depuis config RAG)

    Returns:
        SearchResult avec context et diagnostics
    """
    # Verifier si la collection a un corpus assigne
    if collection_name and db:
        corpus_id = await _get_collection_corpus_id(db, collection_name)
        if corpus_id:
            logger.info(f"Corpus search: collection {collection_name} -> corpus {corpus_id}")
            return await search_corpus_context(
                query=query,
                corpus_id=corpus_id,
                user_id=user_id,
                db_session=db,
                top_k=top_k
            )

    # Pas de corpus: recherche simple dans la collection
    return await search_context(
        query=query,
        user_id=user_id,
        db_session=db,
        collection_name=collection_name,
        top_k=top_k
    )


# Répertoire des prompts et langues supportées
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
SUPPORTED_LANGUAGES = ["fr", "en"]
DEFAULT_LANGUAGE = "fr"

# Labels de prompt selon la langue
PROMPT_LABELS = {
    "fr": {
        "context": "**Contexte disponible :**",
        "question": "**Question de l'utilisateur :**",
        "response": "**Réponse :**"
    },
    "en": {
        "context": "**Available context:**",
        "question": "**User question:**",
        "response": "**Response:**"
    }
}

# Rappel de langue pour forcer les petits modèles à répondre dans la bonne langue
LANGUAGE_REMINDER = {
    "fr": "\n\n[Rappel: Réponds en français.]",
    "en": "\n\n[Reminder: Reply in English.]"
}


def _add_language_reminder(query: str, language: str) -> str:
    """
    Ajoute un rappel de langue à la fin de la query utilisateur.

    Les petits modèles (ex: llama3.2:1b, gemma2:2b) ignorent souvent
    les instructions du system prompt. Ce rappel inline force la réponse
    dans la bonne langue.

    Args:
        query: Question de l'utilisateur
        language: Code langue (fr/en)

    Returns:
        Query avec rappel de langue ajouté
    """
    lang = language.lower() if language and language.lower() in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    reminder = LANGUAGE_REMINDER.get(lang, LANGUAGE_REMINDER[DEFAULT_LANGUAGE])
    return query + reminder

# Cache des prompts chargés
_prompt_cache: Dict[str, str] = {}


def load_prompt(prompt_type: str, language: str = DEFAULT_LANGUAGE) -> str:
    """
    Charge un prompt système selon le type et la langue.

    Args:
        prompt_type: Type de prompt ("chatbot_system" ou "assistant_system")
        language: Code langue (fr/en), défaut: fr

    Returns:
        Contenu du prompt
    """
    # Normaliser la langue (fallback sur français si non supportée)
    lang = language.lower() if language and language.lower() in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    cache_key = f"{prompt_type}_{lang}"

    # Retourner depuis le cache si disponible
    if cache_key in _prompt_cache:
        return _prompt_cache[cache_key]

    filename = f"{prompt_type}_{lang}.md"
    filepath = PROMPTS_DIR / filename

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            _prompt_cache[cache_key] = content
            return content
    except FileNotFoundError:
        logger.warning(f"{filename} not found, trying fallback to {DEFAULT_LANGUAGE}")
        # Fallback sur anglais
        fallback_path = PROMPTS_DIR / f"{prompt_type}_{DEFAULT_LANGUAGE}.md"
        try:
            with open(fallback_path, "r", encoding="utf-8") as f:
                content = f.read()
                _prompt_cache[cache_key] = content
                return content
        except FileNotFoundError:
            logger.error(f"No prompt found for {prompt_type}")
            default = "You are a helpful AI assistant." if lang == "en" else "Tu es un assistant IA serviable."
            return default


async def load_prompt_from_mode(
    db: AsyncSession,
    mode_id: Optional[int],
    language: str = DEFAULT_LANGUAGE
) -> str:
    """
    Charge le system_prompt depuis la BDD pour un mode de conversation.

    Args:
        db: Session database
        mode_id: ID du mode de conversation (conversation_modes.id)
        language: Code langue (fr/en), défaut: fr

    Returns:
        Contenu du prompt (depuis BDD ou fallback fichier)
    """
    if not mode_id or not db:
        # Fallback sur le prompt chatbot par défaut
        return load_prompt("chatbot_system", language)

    try:
        mode = await db.get(ConversationMode, mode_id)
        if mode and mode.system_prompt:
            logger.debug(f"Using system_prompt from mode '{mode.name}' (id={mode_id})")
            return mode.system_prompt

        # Fallback : charger depuis fichier selon le nom du mode
        if mode:
            prompt_type = f"{mode.name}_system"
            logger.debug(f"Mode '{mode.name}' has no system_prompt, loading from file: {prompt_type}")
            return load_prompt(prompt_type, language)

        # Mode non trouvé, fallback chatbot
        logger.warning(f"Mode id={mode_id} not found, using chatbot_system")
        return load_prompt("chatbot_system", language)

    except Exception as e:
        logger.error(f"Error loading prompt from mode {mode_id}: {e}")
        return load_prompt("chatbot_system", language)


# Valeurs par défaut pour l'historique conversationnel
# (utilisées si les clés SystemConfig ne sont pas en BDD)
DEFAULT_HISTORY_MAX_TURNS = 5
DEFAULT_HISTORY_MAX_TOKENS = 4096

# Approximation : 1 token ≈ 4 caractères en français
CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens d'un texte (~4 caractères par token en français)."""
    return len(text) // CHARS_PER_TOKEN


def build_conversation_window(
    history: List[Dict[str, str]],
    max_turns: int = DEFAULT_HISTORY_MAX_TURNS,
    max_tokens: int = DEFAULT_HISTORY_MAX_TOKENS
) -> List[Dict[str, str]]:
    """
    Applique une fenêtre glissante sur l'historique conversationnel.

    Limite par nombre de tours (paires user/assistant), puis vérifie
    le budget tokens. Si le budget est dépassé, réduit le nombre de tours
    en gardant toujours au minimum le dernier échange.

    Args:
        history: Liste de messages [{"role": "user"|"assistant", "content": "..."}]
        max_turns: Nombre maximum de tours (1 tour = 1 user + 1 assistant)
        max_tokens: Budget tokens maximum pour l'historique

    Returns:
        Historique tronqué respectant les limites
    """
    if not history:
        return []

    # Étape 1 : Limiter par nombre de tours (max_turns * 2 messages)
    max_messages = max_turns * 2
    windowed = history[-max_messages:] if len(history) > max_messages else list(history)

    # Étape 2 : Vérifier le budget tokens et réduire si nécessaire
    while len(windowed) >= 2:
        total_tokens = sum(_estimate_tokens(msg["content"]) for msg in windowed)
        if total_tokens <= max_tokens:
            break
        # Retirer les 2 messages les plus anciens (1 tour)
        windowed = windowed[2:]

    # Garantir au minimum les 2 derniers messages (dernier échange)
    if not windowed and history:
        windowed = history[-2:] if len(history) >= 2 else list(history)

    return windowed


async def _reinject_previous_sources(
    db: AsyncSession,
    conversation_id: str,
    current_context: List[Dict[str, Any]],
    query: str,
    user_id: Optional[str] = None,
    collection_name: Optional[str] = None,
    max_additional: int = 3
) -> List[Dict[str, Any]]:
    """
    Réinjecte les sources RAG du dernier message assistant pour les questions de suivi.

    Quand l'utilisateur pose une question vague ("détaille le point 3"),
    la recherche RAG seule peut ne pas retrouver les bons documents.
    Cette fonction complète le contexte avec les sources déjà utilisées.

    Args:
        db: Session de base de données
        conversation_id: ID de la conversation
        current_context: Contexte RAG déjà trouvé par search_context()
        query: Requête utilisateur (pour l'embedding de recherche ciblée)
        user_id: UUID de l'utilisateur (filtrage visibilité)
        collection_name: Nom de la collection ChromaDB
        max_additional: Nombre max de chunks supplémentaires à ajouter

    Returns:
        Contexte enrichi avec les sources précédentes manquantes
    """
    try:
        import uuid as uuid_mod
        conv_uuid = uuid_mod.UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id

        # 1. Récupérer les sources du dernier message assistant
        previous_sources = await MessageRepository.get_last_assistant_sources(db, conv_uuid)
        if not previous_sources:
            return current_context

        # Séparer les sources par type pour chercher dans les bonnes collections
        # - type="document" → collection de la conversation
        # - type="source" → collection external_sources_{provider}
        doc_sources = set()  # Documents (chercher dans collection conversation)
        ext_sources = set()  # Sources externes (chercher dans external_sources_*)

        for item in previous_sources.get("items", []):
            name = item.get("source_name") or item.get("source", "")
            if not name:
                continue
            source_type = item.get("type", "unknown")
            if source_type == "source":
                ext_sources.add(name)
            else:
                doc_sources.add(name)

        if not doc_sources and not ext_sources:
            return current_context

        # 2. Vérifier quelles sources précédentes manquent dans le contexte actuel
        current_names = set()
        for ctx in current_context:
            metadata = ctx.get("metadata", {})
            name = (
                metadata.get("filename")
                or metadata.get("source_name")
                or metadata.get("source", "")
            )
            current_names.add(name)

        missing_docs = doc_sources - current_names
        missing_ext = ext_sources - current_names

        if not missing_docs and not missing_ext:
            return current_context

        # 3. Préparation commune
        chroma_client = get_chroma_client()
        if chroma_client is None:
            return current_context

        from app.common.utils.rag_config import get_rag_config
        rag_config = await get_rag_config(db)
        query_embedding = await get_embeddings(query, model=rag_config.embedding_model)

        seen_contents = {ctx["content"][:200] for ctx in current_context}
        total_added = 0

        # Helper pour chercher dans une collection
        async def search_in_collection(coll_name: str, missing_list: List[str], max_results: int) -> int:
            nonlocal current_context, seen_contents
            try:
                collection = chroma_client.get_collection(name=coll_name)
            except Exception:
                logger.debug(f"Collection {coll_name} not found for reinjection")
                return 0

            # Filtre : sources manquantes + visibilité
            source_filter = {"$or": [
                {"source_name": {"$in": missing_list}},
                {"source": {"$in": missing_list}}
            ]}
            if user_id:
                where_filter = {
                    "$and": [
                        source_filter,
                        {"$or": [
                            {"visibility": "public"},
                            {"$and": [
                                {"visibility": "private"},
                                {"user_id": user_id}
                            ]}
                        ]}
                    ]
                }
            else:
                where_filter = {"$and": [source_filter, {"visibility": "public"}]}

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=max_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )

            added = 0
            if results.get("documents") and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    if doc[:200] in seen_contents:
                        continue
                    metadata = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                    current_context.append({"content": doc, "metadata": metadata})
                    seen_contents.add(doc[:200])
                    added += 1

            return added

        # 4a. Chercher les documents manquants dans la collection conversation
        if missing_docs:
            target = collection_name or settings.collection_name
            added = await search_in_collection(target, list(missing_docs), max_additional)
            total_added += added
            if added > 0:
                logger.info(
                    f"RAG reinjection: +{added} doc chunks from {list(missing_docs)} "
                    f"(collection: {target})"
                )

        # 4b. Chercher les sources externes manquantes dans external_sources_{provider}
        if missing_ext:
            from app.common.utils.chroma import get_provider_collection_name
            ext_collection = await get_provider_collection_name("external_sources", db)
            added = await search_in_collection(ext_collection, list(missing_ext), max_additional)
            total_added += added
            if added > 0:
                logger.info(
                    f"RAG reinjection: +{added} external source chunks from {list(missing_ext)} "
                    f"(collection: {ext_collection})"
                )

        if total_added > 0:
            logger.info(
                f"RAG reinjection total: +{total_added} chunks for conversation {conversation_id}"
            )

        return current_context

    except Exception as e:
        logger.warning(f"Error reinjecting previous sources: {e}")
        return current_context


async def _get_conversation_history(
    db: Optional[AsyncSession],
    conversation_id: Optional[str],
    user_id: Optional[str],
    current_query: Optional[str] = None,
    language: str = "fr",
) -> Tuple[Optional[List[Dict[str, str]]], bool, Optional[str]]:
    """
    Récupère l'historique conversationnel formaté pour le LLM.

    Charge la configuration depuis SystemConfig, applique la fenêtre
    de contexte glissante, détecte les changements de sujet, et
    génère un résumé pour les conversations longues.

    Args:
        db: Session de base de données
        conversation_id: UUID de la conversation (session_id)
        user_id: UUID de l'utilisateur
        current_query: Question courante (pour la détection de changement de sujet)
        language: Langue pour le résumé (fr/en)

    Returns:
        Tuple (history, topic_changed, summary):
        - history: Liste de messages formatés ou None
        - topic_changed: True si changement de sujet détecté
        - summary: Résumé des messages anciens ou None
    """
    if not db or not conversation_id or not user_id:
        return None, False, None

    try:
        # Charger la configuration depuis SystemConfig
        config_service = SystemConfigService(db)
        history_enabled = await config_service.get("chat.history_enabled", True)
        if not history_enabled:
            logger.debug("Chat history injection disabled via SystemConfig")
            return None, False, None

        max_turns = await config_service.get("chat.history_max_turns", DEFAULT_HISTORY_MAX_TURNS)
        max_tokens = await config_service.get("chat.history_max_tokens", DEFAULT_HISTORY_MAX_TOKENS)

        from uuid import UUID
        conv_uuid = UUID(conversation_id)

        # Charger la config résumé
        summary_enabled = await config_service.get("chat.summary_enabled", True)
        summary_trigger = await config_service.get("chat.summary_trigger_messages", 10)

        # Récupérer les messages : plus que la fenêtre pour détecter le besoin de résumé
        fetch_limit = max(max_turns * 2 + 4, summary_trigger + 4)
        messages = await MessageRepository.get_recent_messages(
            db, conv_uuid, limit=fetch_limit
        )

        if not messages or len(messages) < 2:
            return None, False, None

        # Formater en messages Ollama
        raw_history = []
        for msg in messages:
            role = "user" if msg.sender_type == "user" else "assistant"
            raw_history.append({"role": role, "content": msg.content})

        # Appliquer la fenêtre glissante
        history = build_conversation_window(raw_history, max_turns, max_tokens)

        if not history:
            return None, False, None

        # Détection de changement de sujet
        topic_changed = False
        if current_query:
            topic_enabled = await config_service.get("chat.topic_detection_enabled", True)
            if topic_enabled:
                threshold = await config_service.get("chat.topic_similarity_threshold", 0.3)
                topic_changed = await TopicDetector.is_topic_change(
                    current_query, history, threshold
                )
                if topic_changed:
                    logger.info(
                        f"Topic change detected for conversation {conversation_id[:8]}..., "
                        f"history will NOT be sent to LLM"
                    )
                    return None, True, None

        # Résumé automatique pour les conversations longues
        summary = None
        total_messages = len(raw_history)
        window_size = len(history)

        if summary_enabled and total_messages > summary_trigger and total_messages > window_size:
            # Messages hors fenêtre = candidats au résumé
            messages_before_window = raw_history[:total_messages - window_size]

            if messages_before_window:
                # Vérifier si un résumé existe déjà en BDD
                existing_summary = await ConversationRepository.get_summary(db, conv_uuid)

                if existing_summary:
                    summary = existing_summary
                    logger.info(
                        f"Reusing existing summary for conversation {conversation_id[:8]}... "
                        f"({len(summary)} chars)"
                    )
                else:
                    # Générer un nouveau résumé
                    from app.common.utils.rag_config import get_rag_config
                    rag_config = await get_rag_config(db)

                    summary = await ConversationSummarizer.summarize(
                        messages_before_window,
                        model=rag_config.llm_model,
                        language=language
                    )
                    if summary:
                        # Stocker en BDD pour réutilisation
                        await ConversationRepository.update_summary(db, conv_uuid, summary)
                        logger.info(
                            f"New summary generated for conversation {conversation_id[:8]}...: "
                            f"{len(messages_before_window)} messages → {len(summary)} chars"
                        )

        logger.info(
            f"History for conversation {conversation_id[:8]}...: "
            f"{total_messages} loaded, {window_size} after window "
            f"(max_turns={max_turns}, max_tokens={max_tokens})"
            f"{', with summary' if summary else ''}"
        )
        return history, False, summary

    except (ValueError, TypeError) as e:
        logger.debug(f"Invalid conversation_id for history: {e}")
        return None, False, None
    except Exception as e:
        logger.warning(f"Error loading conversation history: {e}")
        return None, False, None


class ChatService:
    """Service de chat conversationnel avec RAG"""

    @staticmethod
    async def chat_with_rag(
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        collection_name: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        language: str = DEFAULT_LANGUAGE,
        mode_id: Optional[int] = None,
        rag_mode: str = "auto"
    ) -> Dict[str, Any]:
        """
        Chat conversationnel avec RAG

        Args:
            query: Question de l'utilisateur
            session_id: ID de session (optionnel)
            user_id: UUID utilisateur pour filtrage visibilite
            db: Session DB pour verifier is_indexed et charger config RAG
            collection_name: Nom de la collection ChromaDB cible
            source_ids: IDs des sources externes a interroger
            language: Langue de réponse (fr/en), défaut: en
            rag_mode: Mode RAG (auto, fast, full), défaut: auto

        Returns:
            Dictionnaire contenant la reponse, les sources, context_status et suggestions
        """
        # Charger la config RAG depuis la BDD
        rag_config = await get_rag_config(db)

        # Charger le mode RAG effectif (auto-détection si "auto")
        effective_mode = None
        if db:
            effective_mode = await get_effective_rag_mode(rag_mode, query, db)
            logger.info(f"RAG mode: requested={rag_mode}, effective={effective_mode.name}")

        # Contextualiser la requête AVANT la recherche RAG (questions de suivi)
        contextualized_query = query
        if db and session_id and user_id:
            config_service = SystemConfigService(db)
            contextualization_enabled = await config_service.get("chat.contextualization_enabled", True)
            if contextualization_enabled:
                max_turns = await config_service.get("chat.history_max_turns", DEFAULT_HISTORY_MAX_TURNS)
                contextualized_query = await QueryContextualizer.contextualize(
                    db=db,
                    query=query,
                    conversation_id=session_id,
                    user_id=user_id,
                    max_turns=max_turns
                )

        # Recherche de contexte (corpus multi-collection si actif, sinon collection simple)
        # Utiliser top_k du mode RAG effectif si disponible
        mode_top_k = effective_mode.top_k if effective_mode else None
        search_result = await _search_with_corpus_fallback(
            query=contextualized_query,
            user_id=user_id,
            db=db,
            collection_name=collection_name,
            top_k=mode_top_k
        )
        chroma_context = search_result["context"]
        diagnostics = search_result["diagnostics"]

        # Déterminer le statut du contexte et générer les suggestions si nécessaire
        context_status = _determine_context_status(diagnostics)
        suggestions = None
        if context_status != "ok":
            target_collection = collection_name or settings.collection_name
            suggestions = _generate_suggestions(diagnostics, target_collection, None)

        # Enrichissement intelligent via sources externes (indexées + live si nécessaire)
        if db:
            context = await SourceContextService.get_smart_context(
                db, contextualized_query, chroma_context, user_id, source_ids,
                collection_name=collection_name
            )
            if len(context) > len(chroma_context):
                logger.info(f"Context enriched: {len(chroma_context)} ChromaDB + {len(context) - len(chroma_context)} external sources")
        else:
            context = chroma_context

        # Réinjection des sources du dernier assistant pour les questions de suivi
        if db and session_id:
            reinjection_enabled = await SystemConfigService(db).get(
                "chat.rag_reinjection_enabled", True
            )
            if reinjection_enabled:
                context = await _reinject_previous_sources(
                    db, session_id, context, contextualized_query,
                    user_id=user_id, collection_name=collection_name
                )

        # Si des sources externes ont enrichi le contexte, annuler les suggestions
        if context and context_status != "ok":
            context_status = "ok"
            suggestions = None

        # Charger le prompt depuis le mode de conversation (BDD) ou fallback fichier
        system_prompt = await load_prompt_from_mode(db, mode_id, language)

        # Récupérer l'historique conversationnel (avec détection de changement de sujet et résumé)
        history, topic_changed, summary = await _get_conversation_history(
            db, session_id, user_id, current_query=query, language=language
        )

        # Injecter le résumé dans le prompt système si disponible
        if summary:
            system_prompt = f"{system_prompt}\n\n**Résumé de la conversation précédente :**\n{summary}"

        # Ajouter le rappel de langue pour forcer les petits modèles
        query_with_lang = _add_language_reminder(query, language)

        # Utiliser la température du mode RAG effectif si disponible
        temperature = effective_mode.temperature if effective_mode else rag_config.temperature

        # Génération de réponse avec température, modèle et historique
        response_text = await generate_response(
            query_with_lang,
            system_prompt,
            context,
            stream=False,
            temperature=temperature,
            model=rag_config.llm_model,
            history=history
        )

        # Inclure le mode RAG utilisé dans la réponse
        effective_mode_name = effective_mode.name if effective_mode else "default"

        # Enrichir le contexte avec les display_name des sources (lookup BDD)
        if db:
            context = await enrich_context_with_display_names(context, db)
        sources = deduplicate_sources(context)
        return {
            "response": response_text,
            "sources": sources if sources else None,
            "session_id": session_id,
            "context_status": context_status,
            "suggestions": suggestions,
            "topic_changed": topic_changed,
            "rag_mode_used": effective_mode_name
        }

    @staticmethod
    async def assistant_with_rag(
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        collection_name: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        language: str = DEFAULT_LANGUAGE,
        mode_id: Optional[int] = None,
        rag_mode: str = "auto"
    ) -> Dict[str, Any]:
        """
        Assistant oriente taches avec RAG

        Args:
            query: Question de l'utilisateur
            session_id: ID de session (optionnel)
            user_id: UUID utilisateur pour filtrage visibilite
            db: Session DB pour verifier is_indexed et charger config RAG
            collection_name: Nom de la collection ChromaDB cible
            source_ids: IDs des sources externes a interroger
            language: Langue de réponse (fr/en), défaut: en
            rag_mode: Mode RAG (auto, fast, full), défaut: auto

        Returns:
            Dictionnaire contenant la reponse, les sources, context_status et suggestions
        """
        # Charger la config RAG depuis la BDD
        rag_config = await get_rag_config(db)

        # Charger le mode RAG effectif (auto-détection si "auto")
        effective_mode = None
        if db:
            effective_mode = await get_effective_rag_mode(rag_mode, query, db)
            logger.info(f"Assistant RAG mode: requested={rag_mode}, effective={effective_mode.name}")

        # Recherche de contexte (corpus multi-collection si actif, sinon collection simple)
        mode_top_k = effective_mode.top_k if effective_mode else None
        search_result = await _search_with_corpus_fallback(
            query=query,
            user_id=user_id,
            db=db,
            collection_name=collection_name,
            top_k=mode_top_k
        )
        chroma_context = search_result["context"]
        diagnostics = search_result["diagnostics"]

        # Déterminer le statut du contexte et générer les suggestions si nécessaire
        context_status = _determine_context_status(diagnostics)
        suggestions = None
        if context_status != "ok":
            target_collection = collection_name or settings.collection_name
            suggestions = _generate_suggestions(diagnostics, target_collection, None)

        # Contextualiser la requete pour les sources externes
        contextualized_query = query
        if db and await SourceContextService.is_sources_enabled(db):
            config_service = SystemConfigService(db)
            contextualization_enabled = await config_service.get("chat.contextualization_enabled", True)
            if contextualization_enabled:
                max_turns = await config_service.get("chat.history_max_turns", DEFAULT_HISTORY_MAX_TURNS)
                contextualized_query = await QueryContextualizer.contextualize(
                    db=db,
                    query=query,
                    conversation_id=session_id,
                    user_id=user_id,
                    max_turns=max_turns
                )

        # Enrichissement intelligent via sources externes (indexées + live si nécessaire)
        if db:
            context = await SourceContextService.get_smart_context(
                db, contextualized_query, chroma_context, user_id, source_ids,
                collection_name=collection_name
            )
            if len(context) > len(chroma_context):
                logger.info(f"Assistant context enriched: {len(chroma_context)} ChromaDB + {len(context) - len(chroma_context)} external sources")
        else:
            context = chroma_context

        # Si des sources externes ont enrichi le contexte, annuler les suggestions
        if context and context_status != "ok":
            context_status = "ok"
            suggestions = None

        # Charger le prompt depuis le mode de conversation (BDD) ou fallback fichier
        system_prompt = await load_prompt_from_mode(db, mode_id, language)

        # Ajouter le rappel de langue pour forcer les petits modèles
        query_with_lang = _add_language_reminder(query, language)

        # Utiliser la température du mode RAG effectif si disponible
        temperature = effective_mode.temperature if effective_mode else rag_config.temperature

        # Génération de réponse avec température et modèle depuis config
        response_text = await generate_response(
            query_with_lang,
            system_prompt,
            context,
            stream=False,
            temperature=temperature,
            model=rag_config.llm_model
        )

        # Inclure le mode RAG utilisé dans la réponse
        effective_mode_name = effective_mode.name if effective_mode else "default"

        # Enrichir le contexte avec les display_name des sources (lookup BDD)
        if db:
            context = await enrich_context_with_display_names(context, db)
        sources = deduplicate_sources(context)
        return {
            "response": response_text,
            "sources": sources if sources else None,
            "session_id": session_id,
            "context_status": context_status,
            "suggestions": suggestions,
            "rag_mode_used": effective_mode_name
        }

    @staticmethod
    async def test_ollama(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Test simple sans RAG - juste Ollama

        Args:
            query: Question de l'utilisateur
            session_id: ID de session (optionnel)

        Returns:
            Dictionnaire contenant la réponse
        """
        logger.info(f"Test request: {query}")

        # Génération directe sans contexte
        response_text = await generate_response(
            query,
            "Tu es un assistant IA serviable et concis.",
            context=None,  # Pas de RAG
            stream=False
        )

        return {
            "response": response_text,
            "sources": None,
            "session_id": session_id
        }

    @staticmethod
    async def chat_stream(
        query: str,
        user_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        collection_name: Optional[str] = None,
        collection_display_name: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        mode_id: Optional[int] = None,
        rag_mode: str = "auto"
    ):
        """
        Chat avec streaming - retourne un generateur asynchrone

        Args:
            query: Question de l'utilisateur
            user_id: UUID utilisateur pour filtrage visibilite
            db: Session DB pour verifier is_indexed et charger config RAG
            collection_name: Nom technique de la collection ChromaDB cible
            collection_display_name: Nom d'affichage de la collection
            source_ids: Liste des IDs de sources externes a interroger
            conversation_id: UUID de la conversation pour contextualisation
            language: Langue de réponse (fr/en), défaut: en
            rag_mode: Mode RAG (auto, fast, full), défaut: auto

        Yields:
            Lignes JSON de la reponse Ollama (premier message = sources, dernier = done avec suggestions)
        """
        import json

        total_start = time.time()
        timings = {}

        # Charger la config RAG depuis la BDD
        t0 = time.time()
        rag_config = await get_rag_config(db)
        timings["rag_config"] = int((time.time() - t0) * 1000)

        # Charger le mode RAG effectif (auto-détection si "auto")
        effective_mode = None
        if db:
            effective_mode = await get_effective_rag_mode(rag_mode, query, db)
            logger.info(f"Stream RAG mode: requested={rag_mode}, effective={effective_mode.name}")

        # Contextualiser la requête AVANT la recherche RAG (questions de suivi)
        contextualized_query = query
        timings["contextualization"] = 0
        if db and conversation_id and user_id:
            t0 = time.time()
            config_service = SystemConfigService(db)
            contextualization_enabled = await config_service.get("chat.contextualization_enabled", True)
            if contextualization_enabled:
                max_turns = await config_service.get("chat.history_max_turns", DEFAULT_HISTORY_MAX_TURNS)
                contextualized_query = await QueryContextualizer.contextualize(
                    db=db,
                    query=query,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    max_turns=max_turns
                )
            timings["contextualization"] = int((time.time() - t0) * 1000)
            if contextualized_query != query:
                logger.info(f"[TIMING] Contextualized in {timings['contextualization']}ms: '{query[:30]}...' -> '{contextualized_query[:50]}...'")

        # Recherche de contexte (corpus multi-collection si assigné, sinon collection simple)
        # Utiliser top_k du mode RAG effectif si disponible
        # Si compaction activé, récupérer plus de chunks (fetch_multiplier)
        t0 = time.time()
        mode_top_k = effective_mode.top_k if effective_mode else None
        if rag_config.compaction_enabled and mode_top_k:
            mode_top_k = mode_top_k * rag_config.compaction_fetch_multiplier
            logger.debug(f"Compaction enabled: fetching {mode_top_k} chunks (multiplier={rag_config.compaction_fetch_multiplier})")
        search_result = await _search_with_corpus_fallback(
            query=contextualized_query,
            user_id=user_id,
            db=db,
            collection_name=collection_name,
            top_k=mode_top_k
        )
        chroma_context = search_result["context"]
        diagnostics = search_result["diagnostics"]
        timings["chroma_search"] = int((time.time() - t0) * 1000)

        # Déterminer le statut du contexte et générer les suggestions si nécessaire
        context_status = _determine_context_status(diagnostics)
        suggestions = None
        if context_status != "ok":
            target_collection = collection_name or settings.collection_name
            target_display_name = collection_display_name or target_collection
            suggestions = _generate_suggestions(diagnostics, target_collection, target_display_name)

        # Enrichissement intelligent via sources externes (indexées + live si nécessaire)
        timings["external_sources"] = 0
        if db:
            t0 = time.time()
            context = await SourceContextService.get_smart_context(
                db, contextualized_query, chroma_context, user_id, source_ids,
                collection_name=collection_name
            )
            timings["external_sources"] = int((time.time() - t0) * 1000)
            if len(context) > len(chroma_context):
                logger.info(f"[TIMING] External sources in {timings['external_sources']}ms: +{len(context) - len(chroma_context)} results")
        else:
            context = chroma_context

        # Réinjection des sources du dernier assistant pour les questions de suivi
        timings["rag_reinjection"] = 0
        if db and conversation_id:
            reinjection_enabled = await SystemConfigService(db).get(
                "chat.rag_reinjection_enabled", True
            )
            if reinjection_enabled:
                t0 = time.time()
                pre_count = len(context)
                context = await _reinject_previous_sources(
                    db, conversation_id, context, contextualized_query,
                    user_id=user_id, collection_name=collection_name
                )
                timings["rag_reinjection"] = int((time.time() - t0) * 1000)
                if len(context) > pre_count:
                    logger.info(
                        f"[TIMING] RAG reinjection in {timings['rag_reinjection']}ms: "
                        f"+{len(context) - pre_count} chunks from previous sources"
                    )

        # Compaction : réduire la redondance des chunks pour accélérer le LLM
        timings["compaction"] = 0
        if rag_config.compaction_enabled and len(context) > 0:
            t0 = time.time()
            compactor = TokenCompactor(CompactionConfig(
                enabled=True,
                similarity_threshold=rag_config.compaction_similarity_threshold,
                extract_enabled=rag_config.compaction_extract_enabled,
                max_sentences=rag_config.compaction_max_sentences
            ))
            pre_compaction_count = len(context)
            context = await compactor.compact(context, contextualized_query)
            timings["compaction"] = int((time.time() - t0) * 1000)
            if compactor.stats:
                logger.info(
                    f"[TIMING] Compaction in {timings['compaction']}ms: "
                    f"{pre_compaction_count} -> {len(context)} chunks "
                    f"(~{compactor.stats.input_tokens_estimate} -> ~{compactor.stats.output_tokens_estimate} tokens)"
                )

        # Si des sources externes ont enrichi le contexte, annuler les suggestions
        # car l'utilisateur a du contenu pertinent même si sa collection ChromaDB est vide
        if context and context_status != "ok":
            context_status = "ok"
            suggestions = None

        # Si require_sources est activé et pas de contexte, refuser de répondre
        if rag_config.require_sources and context_status != "ok":
            no_source_msg = {
                "done": True,
                "context_status": context_status,
                "require_sources_refused": True,
                "provider": "none",
                "model": rag_config.llm_model
            }
            if suggestions:
                no_source_msg["suggestions"] = suggestions  # Déjà des dicts
            yield json.dumps(no_source_msg) + "\n"
            return

        # Log timing summary avant LLM
        pre_llm_time = int((time.time() - total_start) * 1000)
        timings["pre_llm"] = pre_llm_time
        logger.info(
            f"[TIMING] Pre-LLM: {pre_llm_time}ms "
            f"(config:{timings['rag_config']}ms, chroma:{timings['chroma_search']}ms, "
            f"context:{timings['contextualization']}ms, sources:{timings['external_sources']}ms, "
            f"reinjection:{timings['rag_reinjection']}ms, compaction:{timings['compaction']}ms)"
        )

        # Enregistrer les métriques pour le dashboard
        timing_stats.record_batch(timings, prefix="chat.")

        # Envoyer les sources en premier (message special) - dedupliquees
        # Enrichir le contexte avec les display_name des sources (lookup BDD)
        if db:
            context = await enrich_context_with_display_names(context, db)
        sources = deduplicate_sources(context)
        if sources:
            yield json.dumps({"sources": sources}) + "\n"

        # Charger le prompt depuis le mode de conversation (BDD) ou fallback fichier
        system_prompt = await load_prompt_from_mode(db, mode_id, language)

        # Récupérer l'historique conversationnel (avec détection de changement de sujet et résumé)
        t0 = time.time()
        history, topic_changed, summary = await _get_conversation_history(
            db, conversation_id, user_id, current_query=query, language=language
        )
        timings["history_load"] = int((time.time() - t0) * 1000)
        if history:
            logger.info(f"[TIMING] History loaded in {timings['history_load']}ms: {len(history)} messages")
        if topic_changed:
            logger.info(f"[TIMING] Topic change detected in {timings['history_load']}ms")
        if summary:
            logger.info(f"[TIMING] Summary available: {len(summary)} chars")

        # Injecter le résumé dans le prompt système si disponible
        if summary:
            system_prompt = f"{system_prompt}\n\n**Résumé de la conversation précédente :**\n{summary}"

        # Utiliser le provider LLM abstrait pour le streaming
        provider = get_provider()
        logger.info(
            f"Streaming with provider {provider.provider_name}: "
            f"model={rag_config.llm_model}, history={len(history) if history else 0} messages"
        )

        # Ajouter le rappel de langue pour forcer les petits modèles
        query_with_lang = _add_language_reminder(query, language)

        # Utiliser la température du mode RAG effectif si disponible
        temperature = effective_mode.temperature if effective_mode else rag_config.temperature
        effective_mode_name = effective_mode.name if effective_mode else "default"

        # Streaming via le provider (format unifié)
        # Collecter la réponse complète pour la sauvegarder ensuite
        full_response = ""
        stream_start = time.time()

        try:
            stream = provider.generate_stream(
                prompt=query_with_lang,
                system_prompt=system_prompt,
                context=context,
                temperature=temperature,
                model=rag_config.llm_model,
                history=history
            )

            async for chunk in stream:
                full_response += chunk
                # Formater chaque chunk au format attendu par le frontend
                yield json.dumps({"response": chunk}) + "\n"

            response_time = time.time() - stream_start

            # Sauvegarder les messages en BDD si conversation_id fourni
            user_message_id = None
            assistant_message_id = None
            if db and conversation_id:
                try:
                    conv_uuid = uuid.UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id
                    user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

                    # Sauvegarder le message utilisateur
                    user_msg = await MessageRepository.create(
                        db,
                        conversation_id=conv_uuid,
                        sender_type="user",
                        content=query
                    )
                    user_message_id = str(user_msg.id)

                    # Sauvegarder le message assistant avec sources
                    sources_dict = {"items": sources} if sources else None
                    assistant_msg = await MessageRepository.create(
                        db,
                        conversation_id=conv_uuid,
                        sender_type="assistant",
                        content=full_response,
                        sources=sources_dict,
                        response_time=response_time
                    )
                    assistant_message_id = str(assistant_msg.id)

                    logger.info(
                        f"Messages saved: user={user_message_id[:8]}..., "
                        f"assistant={assistant_message_id[:8]}... with {len(sources) if sources else 0} sources"
                    )
                except Exception as save_error:
                    logger.error(f"Error saving messages after stream: {save_error}")
                    # Ne pas bloquer le stream si la sauvegarde échoue

            # Message final "done" avec métadonnées
            done_message = {
                "done": True,
                "context_status": context_status,
                "topic_changed": topic_changed,
                "provider": provider.provider_name,
                "model": rag_config.llm_model,
                "rag_mode_used": effective_mode_name
            }
            if suggestions:
                done_message["suggestions"] = suggestions
            # Inclure les IDs des messages sauvegardés
            if user_message_id:
                done_message["user_message_id"] = user_message_id
            if assistant_message_id:
                done_message["assistant_message_id"] = assistant_message_id
            yield json.dumps(done_message) + "\n"

        except Exception as e:
            logger.error(f"Streaming error: {type(e).__name__}: {e}")
            error_message = {
                "done": True,
                "error": str(e),
                "context_status": "error"
            }
            yield json.dumps(error_message) + "\n"
