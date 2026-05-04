#!/usr/bin/env python3
"""
Script de seeding des donnees geographiques pour MY-IA
======================================================
Ce script importe les pays depuis le fichier countries.json.
Il est appele automatiquement par entrypoint.sh apres seed.py.

Execution: python scripts/docker/seed_geo.py

Le script est idempotent: il peut etre execute plusieurs fois sans creer de doublons.
"""
import json
import os
import re
import sys
import asyncio
from pathlib import Path

# Ajouter le chemin du code pour les imports
sys.path.insert(0, "/code")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


def normalize_database_url(url: str) -> str:
    """
    Normalise l'URL PostgreSQL en convertissant les identifiants en minuscules.
    PostgreSQL convertit automatiquement les identifiants non-quotes en minuscules.
    """
    pattern = r'^(postgresql\+asyncpg://)([^:]+):([^@]+)@([^:]+):(\d+)/(.+)$'
    match = re.match(pattern, url)
    if not match:
        return url
    prefix, user, password, host, port, database = match.groups()
    return f"{prefix}{user.lower()}:{password}@{host}:{port}/{database.lower()}"


# Configuration depuis variables d'environnement
_raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://my_ia_user:my_ia_db_pass@postgres:5432/my_ia_db")
DATABASE_URL = normalize_database_url(_raw_url)
STATIC_DATA_DIR = os.getenv("STATIC_DATA_DIR", "/code/static-datas")


def get_countries_json_path() -> Path:
    """Retourne le chemin du fichier countries.json."""
    return Path(STATIC_DATA_DIR) / "countries.json"


def load_countries_from_json() -> list:
    """Charge les pays depuis le fichier JSON."""
    filepath = get_countries_json_path()

    if not filepath.exists():
        print(f"  [!] Fichier non trouve: {filepath}")
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"  [i] {len(data)} pays charges depuis {filepath}")
            return data
    except json.JSONDecodeError as e:
        print(f"  [!] Erreur lecture JSON: {e}")
        return []
    except Exception as e:
        print(f"  [!] Erreur: {e}")
        return []


# =============================================================================
# FONCTIONS DE SEEDING
# =============================================================================

async def check_countries_count(session: AsyncSession) -> int:
    """Retourne le nombre de pays en base."""
    result = await session.execute(text("SELECT COUNT(*) FROM countries"))
    return result.scalar() or 0


async def seed_countries(session: AsyncSession, countries_data: list) -> int:
    """Insere les pays s'ils n'existent pas."""
    count = 0

    for country in countries_data:
        code = country.get("code")
        name = country.get("name")
        flag = country.get("flag")
        phone_prefix = country.get("phone_prefix")
        display_order = country.get("display_order", 999)

        # Verifier si le pays existe deja
        result = await session.execute(
            text("SELECT code FROM countries WHERE code = :code"),
            {"code": code}
        )
        if result.fetchone() is not None:
            continue

        # Inserer le pays
        await session.execute(
            text("""
                INSERT INTO countries (code, name, flag, phone_prefix, is_active, display_order)
                VALUES (:code, :name, :flag, :phone_prefix, true, :display_order)
            """),
            {
                "code": code,
                "name": name,
                "flag": flag,
                "phone_prefix": phone_prefix,
                "display_order": display_order
            }
        )
        count += 1
        print(f"  [+] Pays: {flag} {name} ({code})")

    return count


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Fonction principale de seeding des donnees geographiques."""
    print("\n" + "=" * 60)
    print("        MY-IA - Seeding des donnees geographiques")
    print("=" * 60)
    print()

    # Charger les pays depuis le fichier JSON
    countries_data = load_countries_from_json()

    if not countries_data:
        print("  [!] Aucun pays a importer (fichier absent ou vide)")
        print()
        print("=" * 60)
        print("  Seeding geo termine: aucune donnee disponible")
        print("=" * 60)
        print()
        return

    # Creer le moteur de base de donnees
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as session:
            # Verifier le nombre de pays existants
            existing_count = await check_countries_count(session)

            if existing_count >= len(countries_data):
                print(f"  [=] {existing_count} pays deja presents (liste complete)")
                print()
                print("=" * 60)
                print("  Seeding geo termine: base de donnees deja a jour")
                print("=" * 60)
                print()
                return

            print(f"[1/1] Import des pays ({len(countries_data)} pays disponibles)...")

            if existing_count > 0:
                print(f"  [i] {existing_count} pays deja presents, import des manquants...")

            # Importer les pays
            inserted_count = await seed_countries(session, countries_data)

            # Commit
            await session.commit()

            print()
            print("=" * 60)
            if inserted_count > 0:
                print(f"  Seeding geo termine: {inserted_count} pays importes")
            else:
                print("  Seeding geo termine: aucun nouveau pays a importer")
            print("=" * 60)
            print()

    except Exception as e:
        print(f"\n[ERREUR] Echec du seeding geo: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
