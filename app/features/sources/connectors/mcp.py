"""
Connecteur MCP - Model Context Protocol servers
Support des serveurs MCP pour enrichir le contexte RAG
"""
import json
import logging
import base64
from typing import List, Dict, Any, Optional

import httpx

from app.features.sources.connectors.base import BaseConnector
from app.features.sources.schemas import ContextResult, SourceType

logger = logging.getLogger(__name__)


class MCPConnector(BaseConnector):
    """
    Connecteur pour serveurs MCP (Model Context Protocol).

    Config attendue:
    {
        "server_url": "http://localhost:3000",
        "transport": "http",              # http | sse (stdio non supporte pour remote)
        "auth_type": "none",              # none | api_key | bearer | basic
        "api_key": "...",                 # si auth_type = api_key
        "bearer_token": "...",            # si auth_type = bearer
        "username": "...",                # si auth_type = basic
        "password": "...",                # si auth_type = basic
        "tool_name": "search",            # nom de l'outil MCP a appeler
        "query_param": "query",           # parametre pour la requete
        "response_path": "content",       # chemin vers les resultats dans la reponse
        "content_field": "text"           # champ contenant le texte
    }
    """

    def validate_config(self) -> bool:
        """Valide la configuration du connecteur MCP"""
        if not self.config.get('server_url'):
            logger.error("MCP config: server_url requis")
            return False

        auth_type = self.config.get('auth_type', 'none')
        if auth_type == 'api_key' and not self.config.get('api_key'):
            logger.error("MCP config: api_key requis pour auth_type=api_key")
            return False
        if auth_type == 'bearer' and not self.config.get('bearer_token'):
            logger.error("MCP config: bearer_token requis pour auth_type=bearer")
            return False
        if auth_type == 'basic':
            if not self.config.get('username') or not self.config.get('password'):
                logger.error("MCP config: username et password requis pour auth_type=basic")
                return False

        return True

    def _get_headers(self) -> Dict[str, str]:
        """Construit les headers d'authentification"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        auth_type = self.config.get('auth_type', 'none')

        if auth_type == 'api_key':
            api_key = self.config.get('api_key', '')
            header_name = self.config.get('api_key_header', 'X-API-Key')
            headers[header_name] = api_key

        elif auth_type == 'bearer':
            token = self.config.get('bearer_token', '')
            headers['Authorization'] = f"Bearer {token}"

        elif auth_type == 'basic':
            username = self.config.get('username', '')
            password = self.config.get('password', '')
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers['Authorization'] = f"Basic {credentials}"

        return headers

    async def search(self, query: str, progress_callback=None) -> List[ContextResult]:
        """
        Appelle un outil MCP pour rechercher du contexte.

        Le protocole MCP utilise JSON-RPC 2.0 sur HTTP.
        """
        try:
            server_url = self.config.get('server_url', '').rstrip('/')
            tool_name = self.config.get('tool_name', 'search')
            query_param = self.config.get('query_param')  # None si non défini
            response_path = self.config.get('response_path', 'content')
            content_field = self.config.get('content_field', 'text')

            headers = self._get_headers()

            # Construire les arguments de l'outil
            arguments = {}
            if query_param:
                # Outil avec paramètre de requête (ex: search_nodes)
                arguments[query_param] = query

            # Ajouter des arguments supplementaires si configures
            extra_args = self.config.get('extra_arguments', {})
            if extra_args:
                arguments.update(extra_args)

            # Construire la requete JSON-RPC pour appeler l'outil
            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{server_url}/rpc",
                    json=rpc_request,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

            # Verifier les erreurs JSON-RPC
            if "error" in data:
                error_msg = data["error"].get("message", "Erreur MCP inconnue")
                logger.error(f"MCP error: {error_msg}")
                return []

            # Extraire les resultats
            result_data = data.get("result", {})

            # Naviguer vers le chemin des resultats
            if response_path:
                for key in response_path.split('.'):
                    if isinstance(result_data, dict):
                        result_data = result_data.get(key, [])
                    elif isinstance(result_data, list) and key.isdigit():
                        result_data = result_data[int(key)]

            # Gérer le cas MCP standard: content[0].text contient du JSON stringifié
            result_data = self._parse_mcp_content(result_data, content_field)

            # Parser les resultats
            results = []
            if not isinstance(result_data, list):
                result_data = [result_data] if result_data else []

            for item in result_data[:self.max_results]:
                content = self._extract_content(item, content_field)
                if content:
                    metadata = self._extract_metadata(item)
                    source_url = self._extract_url(item)

                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.MCP,
                        content=content,
                        source_url=source_url,
                        metadata=metadata
                    ))

            logger.info(f"MCP search: {len(results)} resultats pour '{query[:50]}'")
            return results

        except httpx.TimeoutException:
            logger.warning(f"MCP timeout: {self.config.get('server_url')}")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP HTTP error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"MCP search error: {e}")
            return []

    def _parse_mcp_content(self, result_data: Any, content_field: str) -> Any:
        """
        Parse le contenu MCP qui peut contenir du JSON stringifié.

        Les serveurs MCP retournent souvent: content[0].text = "{json stringifié}"
        Cette méthode détecte et parse ces cas.
        """
        # Cas: liste avec un élément ayant un champ text contenant du JSON
        if isinstance(result_data, list) and len(result_data) > 0:
            first_item = result_data[0]
            if isinstance(first_item, dict):
                text_content = first_item.get('text') or first_item.get(content_field)
                if isinstance(text_content, str) and text_content.startswith('{'):
                    try:
                        parsed = json.loads(text_content)
                        # Si c'est une liste de données (ex: workflows), retourner la liste
                        if isinstance(parsed, dict) and 'data' in parsed:
                            return parsed['data']
                        return [parsed] if not isinstance(parsed, list) else parsed
                    except json.JSONDecodeError:
                        pass

        return result_data

    def _extract_content(self, item: Any, content_field: str) -> Optional[str]:
        """Extrait le contenu d'un item de resultat et le formate lisiblement"""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            # Cas spécial: workflow N8N - formater lisiblement
            if 'name' in item and ('nodes' in item or 'active' in item):
                return self._format_workflow(item)

            # Essayer le champ configure
            if content_field in item:
                value = item[content_field]
                if isinstance(value, str):
                    return value
                return self._format_dict(value) if isinstance(value, dict) else str(value)

            # Essayer des champs courants
            for field in ['text', 'content', 'body', 'description', 'result']:
                if field in item:
                    value = item[field]
                    if isinstance(value, str):
                        return value
                    return self._format_dict(value) if isinstance(value, dict) else str(value)

            # Formater le dict entier de manière lisible
            return self._format_dict(item)
        return str(item) if item else None

    def _format_workflow(self, workflow: Dict[str, Any]) -> str:
        """Formate un workflow N8N de manière lisible"""
        name = workflow.get('name', 'Sans nom')
        wf_id = workflow.get('id', '')
        active = "Actif" if workflow.get('active') else "Inactif"
        nodes = workflow.get('nodes', [])
        node_count = len(nodes) if isinstance(nodes, list) else 0
        tags = workflow.get('tags', [])
        tag_names = [t.get('name', t) if isinstance(t, dict) else str(t) for t in tags]

        lines = [
            f"Workflow: {name}",
            f"ID: {wf_id}",
            f"Statut: {active}",
            f"Nombre de nodes: {node_count}",
        ]
        if tag_names:
            lines.append(f"Tags: {', '.join(tag_names)}")

        return "\n".join(lines)

    def _format_dict(self, data: Dict[str, Any]) -> str:
        """Formate un dictionnaire de manière lisible"""
        if not data:
            return ""

        # Sélectionner les champs pertinents
        relevant_fields = ['name', 'title', 'description', 'id', 'type', 'status', 'active']
        lines = []

        for field in relevant_fields:
            if field in data:
                value = data[field]
                if value is not None and value != '':
                    lines.append(f"{field.capitalize()}: {value}")

        # Si aucun champ pertinent, utiliser les premiers champs disponibles
        if not lines:
            for key, value in list(data.items())[:5]:
                if value is not None and value != '' and not isinstance(value, (dict, list)):
                    lines.append(f"{key}: {value}")

        return "\n".join(lines) if lines else str(data)

    def _extract_metadata(self, item: Any) -> Dict[str, Any]:
        """Extrait les metadonnees d'un item"""
        if not isinstance(item, dict):
            return {}

        metadata = {}
        metadata_fields = ['title', 'name', 'source', 'type', 'score', 'timestamp']
        for field in metadata_fields:
            if field in item:
                metadata[field] = item[field]
        return metadata

    def _extract_url(self, item: Any) -> Optional[str]:
        """Extrait l'URL source d'un item"""
        if not isinstance(item, dict):
            return None
        for field in ['url', 'link', 'href', 'source_url', 'uri']:
            if field in item and item[field]:
                return str(item[field])
        return None

    async def health_check(self) -> Dict[str, Any]:
        """
        Verifie que le serveur MCP est accessible.

        Essaie d'appeler la methode 'initialize' ou verifie simplement
        que le serveur repond.
        """
        try:
            server_url = self.config.get('server_url', '').rstrip('/')
            headers = self._get_headers()

            # Essayer d'initialiser la connexion MCP
            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "my-ia",
                        "version": "1.0.0"
                    }
                }
            }

            async with httpx.AsyncClient(timeout=10) as client:
                # Essayer l'endpoint RPC
                try:
                    response = await client.post(
                        f"{server_url}/rpc",
                        json=rpc_request,
                        headers=headers
                    )

                    if response.status_code < 500:
                        data = response.json()
                        if "error" not in data:
                            return {"status": "healthy"}
                        # Erreur JSON-RPC mais serveur accessible
                        return {"status": "healthy"}

                except httpx.HTTPStatusError:
                    pass

                # Fallback: verifier que le serveur repond
                response = await client.get(server_url, headers=headers)
                if response.status_code < 500:
                    return {"status": "healthy"}

                return {"status": "unhealthy", "error": f"HTTP {response.status_code}"}

        except httpx.TimeoutException:
            return {"status": "unhealthy", "error": "Timeout"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Liste les outils disponibles sur le serveur MCP.

        Utile pour la configuration et le debug.
        """
        try:
            server_url = self.config.get('server_url', '').rstrip('/')
            headers = self._get_headers()

            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{server_url}/rpc",
                    json=rpc_request,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

            if "error" in data:
                logger.error(f"MCP tools/list error: {data['error']}")
                return []

            return data.get("result", {}).get("tools", [])

        except Exception as e:
            logger.error(f"MCP list_tools error: {e}")
            return []
