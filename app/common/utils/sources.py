"""
Utilitaires pour la gestion des sources RAG.
"""
from typing import List, Dict, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def enrich_context_with_display_names(
    context: List[Dict[str, Any]],
    db: AsyncSession
) -> List[Dict[str, Any]]:
    """
    Enrichit le contexte avec les display_name des sources depuis la BDD.

    Pour les chunks indexés sans display_name dans le metadata,
    cette fonction fait un lookup en BDD pour récupérer le display_name
    à partir du source_name technique.

    Args:
        context: Liste des contextes RAG avec metadata
        db: Session de base de données

    Returns:
        Contexte enrichi avec display_name dans le metadata
    """
    if not context:
        return context

    # Importer ici pour éviter les imports circulaires
    from app.models import ContextSource

    # Collecter les source_name techniques qui n'ont pas de display_name
    source_names_to_lookup = set()
    for ctx in context:
        metadata = ctx.get("metadata", {})
        # Si pas de display_name et qu'on a un source_name (source externe)
        if not metadata.get("display_name") and not metadata.get("filename"):
            source_name = metadata.get("source_name")
            if source_name:
                source_names_to_lookup.add(source_name)

    if not source_names_to_lookup:
        return context

    # Lookup en BDD pour récupérer les display_name
    result = await db.execute(
        select(ContextSource.name, ContextSource.display_name)
        .where(ContextSource.name.in_(source_names_to_lookup))
    )
    name_to_display = {row[0]: row[1] for row in result.fetchall()}

    # Enrichir le contexte avec les display_name
    for ctx in context:
        metadata = ctx.get("metadata", {})
        if not metadata.get("display_name") and not metadata.get("filename"):
            source_name = metadata.get("source_name")
            if source_name and source_name in name_to_display:
                metadata["display_name"] = name_to_display[source_name]

    return context


def deduplicate_sources(context: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Deduplique les sources en ne gardant qu'une occurrence par fichier.

    Args:
        context: Liste des contextes RAG avec metadata

    Returns:
        Liste des sources uniques avec leur nom d'affichage et type
    """
    if not context:
        return []

    seen = set()
    sources = []

    for ctx in context:
        metadata = ctx.get("metadata", {})

        # Clé de déduplication (nom technique)
        dedup_key = (
            metadata.get("filename")
            or metadata.get("source_name")
            or metadata.get("source", "Unknown")
        )

        # Déterminer le type de source
        # - "document" si filename présent (fichier uploadé)
        # - "source" si source_name présent (source externe)
        if metadata.get("filename"):
            source_type = "document"
            display_name = metadata.get("filename")
            technical_name = metadata.get("filename")
        elif metadata.get("source_name"):
            source_type = "source"
            technical_name = metadata.get("source_name")
            display_name = (
                metadata.get("display_name")
                or technical_name
            )
        else:
            source_type = "unknown"
            display_name = metadata.get("source", "Unknown")
            technical_name = display_name

        if dedup_key not in seen:
            seen.add(dedup_key)
            sources.append({
                "source": display_name,
                "source_name": technical_name,  # Nom technique pour la réinjection
                "type": source_type
            })

    return sources
