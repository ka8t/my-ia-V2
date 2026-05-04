"""
Connecteur Database - Requetes sur bases de donnees externes

Supporte :
- PostgreSQL
- MySQL
- SQLite (fichier)
"""
import logging
from typing import List, Dict, Any

from app.features.sources.connectors.base import BaseConnector
from app.features.sources.schemas import ContextResult, SourceType

logger = logging.getLogger(__name__)


class DatabaseConnector(BaseConnector):
    """
    Connecteur pour bases de donnees externes.

    Config attendue:
    {
        "db_type": "postgresql" | "mysql" | "sqlite",
        "host": "localhost",
        "port": 5432,
        "database": "mydb",
        "username": "user",
        "password": "pass",
        "query_template": "SELECT content FROM documents WHERE content ILIKE '%{query}%' LIMIT {limit}",
        "content_column": "content",
        "metadata_columns": ["title", "source"]  # Optionnel
    }
    """

    DB_TYPES = ['postgresql', 'mysql', 'sqlite']

    def validate_config(self) -> bool:
        db_type = self.config.get('db_type')
        if db_type not in self.DB_TYPES:
            return False
        if db_type != 'sqlite':
            required = ['host', 'database', 'username', 'password']
            if not all(self.config.get(k) for k in required):
                return False
        if not self.config.get('query_template'):
            return False
        return True

    def _get_connection_string(self) -> str:
        """Construit la chaine de connexion"""
        db_type = self.config.get('db_type')
        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 5432)
        database = self.config.get('database')
        username = self.config.get('username')
        password = self.config.get('password')

        if db_type == 'postgresql':
            return f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{database}"
        elif db_type == 'mysql':
            return f"mysql+aiomysql://{username}:{password}@{host}:{port}/{database}"
        elif db_type == 'sqlite':
            return f"sqlite+aiosqlite:///{database}"
        else:
            raise ValueError(f"Type de BDD non supporte: {db_type}")

    async def search(self, query: str, progress_callback=None) -> List[ContextResult]:
        """Execute une requete SQL et retourne les resultats"""
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text

            # Construire la requete
            query_template = self.config.get('query_template', '')
            # Echapper les caracteres dangereux pour eviter injection SQL
            safe_query = query.replace("'", "''").replace("%", "%%")
            sql = query_template.format(query=safe_query, limit=self.max_results)

            # Connexion et execution
            engine = create_async_engine(
                self._get_connection_string(),
                pool_pre_ping=True
            )

            results = []
            content_column = self.config.get('content_column', 'content')
            metadata_columns = self.config.get('metadata_columns', [])

            async with engine.connect() as conn:
                result = await conn.execute(text(sql))
                rows = result.fetchall()

                for row in rows[:self.max_results]:
                    row_dict = row._asdict() if hasattr(row, '_asdict') else dict(row)

                    content = str(row_dict.get(content_column, ''))
                    metadata = {col: row_dict.get(col) for col in metadata_columns if col in row_dict}

                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.DATABASE,
                        content=content,
                        metadata=metadata
                    ))

            await engine.dispose()
            return results

        except ImportError as e:
            logger.error(f"Driver de BDD manquant: {e}")
            return []
        except Exception as e:
            logger.error(f"Database search error: {e}")
            return []

    async def health_check(self) -> Dict[str, Any]:
        """Verifie la connexion a la base de donnees"""
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text

            engine = create_async_engine(
                self._get_connection_string(),
                pool_pre_ping=True
            )

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            await engine.dispose()
            return {"status": "healthy"}

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
