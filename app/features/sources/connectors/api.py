"""
Connecteur API - Appels a des APIs REST tierces
"""
import logging
import json
from typing import List, Dict, Any

import httpx

from app.features.sources.connectors.base import BaseConnector
from app.features.sources.schemas import ContextResult, SourceType

logger = logging.getLogger(__name__)


class ApiConnector(BaseConnector):
    """
    Connecteur pour APIs REST externes.

    Config attendue:
    {
        "base_url": "https://api.example.com",
        "endpoint": "/search",
        "method": "GET" | "POST",
        "headers": {"Authorization": "Bearer xxx"},
        "query_param": "q",              # Pour GET: nom du parametre de recherche
        "body_template": {"query": "{query}"},  # Pour POST: template du body
        "response_path": "results",      # Chemin JSON vers les resultats
        "content_field": "text",         # Champ contenant le contenu
        "metadata_fields": ["title", "url"]  # Champs de metadata
    }
    """

    def validate_config(self) -> bool:
        if not self.config.get('base_url'):
            return False
        if not self.config.get('endpoint'):
            return False
        method = self.config.get('method', 'GET').upper()
        if method not in ['GET', 'POST']:
            return False
        return True

    async def search(self, query: str, progress_callback=None) -> List[ContextResult]:
        """Appelle l'API et parse les resultats"""
        try:
            base_url = self.config.get('base_url', '').rstrip('/')
            endpoint = self.config.get('endpoint', '')
            method = self.config.get('method', 'GET').upper()
            headers = self.config.get('headers', {})
            response_path = self.config.get('response_path', '')
            content_field = self.config.get('content_field', 'content')
            metadata_fields = self.config.get('metadata_fields', [])

            url = f"{base_url}{endpoint}"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method == 'GET':
                    query_param = self.config.get('query_param', 'q')
                    params = {query_param: query}
                    # Ajouter des params supplementaires si configures
                    extra_params = self.config.get('extra_params', {})
                    params.update(extra_params)

                    response = await client.get(url, params=params, headers=headers)
                else:  # POST
                    body_template = self.config.get('body_template', {})
                    # Remplacer {query} dans le template
                    body_str = json.dumps(body_template).replace('{query}', query)
                    body = json.loads(body_str)

                    response = await client.post(url, json=body, headers=headers)

                response.raise_for_status()
                data = response.json()

            # Naviguer vers le chemin des resultats
            results_data = data
            if response_path:
                for key in response_path.split('.'):
                    if isinstance(results_data, dict):
                        results_data = results_data.get(key, [])
                    elif isinstance(results_data, list) and key.isdigit():
                        results_data = results_data[int(key)]

            # Parser les resultats
            results = []
            if not isinstance(results_data, list):
                results_data = [results_data]

            for item in results_data[:self.max_results]:
                if isinstance(item, dict):
                    content = str(item.get(content_field, ''))
                    metadata = {field: item.get(field) for field in metadata_fields if field in item}
                    source_url = item.get('url') or item.get('link') or item.get('href')
                else:
                    content = str(item)
                    metadata = {}
                    source_url = None

                if content:
                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.API,
                        content=content,
                        source_url=source_url,
                        metadata=metadata
                    ))

            return results

        except httpx.TimeoutException:
            logger.warning(f"API timeout: {self.config.get('base_url')}")
            return []
        except Exception as e:
            logger.error(f"API search error: {e}")
            return []

    async def health_check(self) -> Dict[str, Any]:
        """Verifie que l'API est accessible"""
        try:
            base_url = self.config.get('base_url', '').rstrip('/')
            health_endpoint = self.config.get('health_endpoint', '')
            headers = self.config.get('headers', {})

            # Essayer un endpoint de health ou la racine
            url = f"{base_url}{health_endpoint}" if health_endpoint else base_url

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=headers)

                # Accepter 200-299 et 401/403 (l'API repond mais auth requise)
                if response.status_code < 500:
                    return {"status": "healthy"}
                else:
                    return {"status": "unhealthy", "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
