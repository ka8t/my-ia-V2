"""
Connecteur Web - Recherche sur le web

Supporte :
- DuckDuckGo (gratuit, pas de clé API)
- Google Custom Search (avec clé API)
- Wikipedia
- Fixed URL (URLs fixes)
- Crawl (crawling récursif multi-niveaux)
"""
import re
import logging
import asyncio
from typing import List, Dict, Any, Optional, Set, Callable, Awaitable
from urllib.parse import urljoin, urlparse, urlunparse
from collections import deque

import httpx
from bs4 import BeautifulSoup

from app.features.sources.connectors.base import BaseConnector
from app.features.sources.schemas import ContextResult, SourceType

logger = logging.getLogger(__name__)

# User-Agent requis par Wikipedia et recommandé pour les APIs publiques
DEFAULT_USER_AGENT = "MY-IA/1.0 (RAG Assistant; Contact: admin@localhost)"


class WebConnector(BaseConnector):
    """
    Connecteur pour recherche web.

    Config attendue:
    {
        "provider": "duckduckgo" | "google" | "wikipedia" | "custom",
        "api_key": "...",           # Pour Google uniquement
        "search_engine_id": "...",  # Pour Google uniquement
        "language": "fr",           # Optionnel
        # Pour custom uniquement:
        "url": "https://...",       # URL de l'API
        "method": "GET" | "POST",   # Methode HTTP
        "query_param": "q",         # Parametre pour la requete
        "response_path": "results", # Chemin JSON vers les resultats
        "content_field": "text",    # Champ contenant le texte
        "headers": {}               # Headers additionnels
    }
    """

    PROVIDERS = ['duckduckgo', 'google', 'wikipedia', 'custom', 'fixed_url', 'crawl']

    # Extensions de fichiers binaires à exclure du crawling
    EXCLUDED_EXTENSIONS = {
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.zip', '.rar', '.tar', '.gz', '.7z',
        '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico', '.bmp',
        '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.wav', '.flac',
        '.css', '.js', '.xml', '.json', '.rss', '.atom',
        '.woff', '.woff2', '.ttf', '.eot',
    }

    def validate_config(self) -> bool:
        provider = self.config.get('provider', 'duckduckgo')
        if provider not in self.PROVIDERS:
            return False
        if provider == 'google':
            if not self.config.get('api_key') or not self.config.get('search_engine_id'):
                return False
        if provider == 'custom':
            if not self.config.get('url'):
                return False
        if provider == 'fixed_url':
            # Supporter url (string) ou urls (array)
            if not self.config.get('url') and not self.config.get('urls'):
                return False
        if provider == 'crawl':
            # URL de départ obligatoire
            if not self.config.get('url') and not self.config.get('urls'):
                return False
            # max_depth >= 0 (0 = illimité)
            max_depth = self.config.get('max_depth', 0)
            if not isinstance(max_depth, int) or max_depth < 0:
                return False
            # max_pages entre 1 et 500
            max_pages = self.config.get('max_pages', 50)
            if not isinstance(max_pages, int) or max_pages < 1 or max_pages > 500:
                return False
        return True

    async def search(
        self,
        query: str,
        progress_callback: Optional[Callable[[int, int, str], Awaitable[None]]] = None
    ) -> List[ContextResult]:
        """
        Recherche sur le web selon le provider configuré.

        Args:
            query: Requête de recherche
            progress_callback: Callback optionnel (current, total, message) pour le suivi de progression

        Returns:
            Liste de résultats
        """
        provider = self.config.get('provider', 'duckduckgo')

        try:
            if provider == 'duckduckgo':
                return await self._search_duckduckgo(query)
            elif provider == 'google':
                return await self._search_google(query)
            elif provider == 'wikipedia':
                return await self._search_wikipedia(query)
            elif provider == 'custom':
                return await self._search_custom(query)
            elif provider == 'fixed_url':
                return await self._fetch_fixed_urls()
            elif provider == 'crawl':
                return await self._crawl_urls(progress_callback)
            else:
                logger.error(f"Provider inconnu: {provider}")
                return []
        except asyncio.TimeoutError:
            logger.warning(f"Web search timeout for query: {query[:50]}...")
            return []
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []

    async def _search_duckduckgo(self, query: str) -> List[ContextResult]:
        """Recherche via DuckDuckGo Instant Answer API"""
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": 1,
                    "skip_disambig": 1
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []

            # Abstract (reponse principale)
            if data.get("Abstract"):
                results.append(ContextResult(
                    source_name=self.source_name,
                    display_name=self.display_name,
                    source_type=SourceType.WEB,
                    content=data["Abstract"],
                    source_url=data.get("AbstractURL"),
                    metadata={"type": "abstract", "source": data.get("AbstractSource")}
                ))

            # Related topics
            for topic in data.get("RelatedTopics", [])[:self.max_results - len(results)]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.WEB,
                        content=topic["Text"],
                        source_url=topic.get("FirstURL"),
                        metadata={"type": "related"}
                    ))

            return results[:self.max_results]

    async def _search_google(self, query: str) -> List[ContextResult]:
        """Recherche via Google Custom Search API"""
        api_key = self.config.get('api_key')
        cx = self.config.get('search_engine_id')

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cx,
                    "q": query,
                    "num": min(self.max_results, 10)
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("items", []):
                results.append(ContextResult(
                    source_name=self.source_name,
                    display_name=self.display_name,
                    source_type=SourceType.WEB,
                    content=item.get("snippet", ""),
                    source_url=item.get("link"),
                    metadata={
                        "title": item.get("title"),
                        "displayLink": item.get("displayLink")
                    }
                ))

            return results

    async def _search_wikipedia(self, query: str) -> List[ContextResult]:
        """Recherche via Wikipedia API (optimisé avec requêtes parallèles)"""
        lang = self.config.get('language', 'fr')

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            # Recherche de pages
            search_response = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": self.max_results,
                    "format": "json"
                }
            )
            search_response.raise_for_status()
            search_data = search_response.json()

            search_items = search_data.get("query", {}).get("search", [])
            if not search_items:
                return []

            # Récupérer tous les extraits en une seule requête batch
            page_ids = [str(item["pageid"]) for item in search_items]
            page_response = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "pageids": "|".join(page_ids),
                    "format": "json"
                }
            )
            page_data = page_response.json()
            pages = page_data.get("query", {}).get("pages", {})

            # Mapper les résultats avec les titres de recherche
            title_map = {str(item["pageid"]): item["title"] for item in search_items}
            results = []

            for page_id, page in pages.items():
                if page.get("extract"):
                    title = title_map.get(page_id, page.get("title", ""))
                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.WEB,
                        content=page["extract"][:1000],
                        source_url=f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        metadata={"title": title, "pageid": int(page_id)}
                    ))

            return results

    async def _search_custom(self, query: str) -> List[ContextResult]:
        """Recherche via une URL personnalisee"""
        url = self.config.get('url')
        method = self.config.get('method', 'GET').upper()
        query_param = self.config.get('query_param', 'q')
        response_path = self.config.get('response_path', '')
        content_field = self.config.get('content_field', 'text')
        custom_headers = self.config.get('headers', {})

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        headers.update(custom_headers)

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            if method == 'GET':
                response = await client.get(url, params={query_param: query})
            else:
                response = await client.post(url, json={query_param: query})

            response.raise_for_status()
            data = response.json()

            # Naviguer vers le chemin des resultats si specifie
            if response_path:
                for key in response_path.split('.'):
                    if isinstance(data, dict) and key in data:
                        data = data[key]
                    else:
                        data = []
                        break

            # S'assurer que data est une liste
            if not isinstance(data, list):
                data = [data] if data else []

            results = []
            for item in data[:self.max_results]:
                if isinstance(item, dict):
                    content = item.get(content_field, str(item))
                    source_url = item.get('url') or item.get('link') or item.get('href')
                    title = item.get('title') or item.get('name')
                else:
                    content = str(item)
                    source_url = None
                    title = None

                if content:
                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.WEB,
                        content=content[:1000],
                        source_url=source_url,
                        metadata={"title": title, "custom_url": url}
                    ))

            return results

    # ── Méthodes utilitaires partagées (DRY) ──────────────────────────

    @staticmethod
    def _extract_page_content(html_content: str) -> str:
        """Extrait le texte principal d'une page HTML avec BeautifulSoup.

        Supprime navigation, scripts, styles, footer, sidebar, widgets,
        éléments sociaux, articles-cartes. Cherche le contenu principal
        via des sélecteurs courants (Elementor, main, article, etc.).
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Supprimer les éléments non-contenu
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer',
                                   'aside', 'noscript', 'iframe', 'form', 'button']):
            tag.decompose()

        # Supprimer les éléments avec des classes de menu/navigation/bannière
        for tag in soup.find_all(class_=re.compile(
            r'^(menu|nav|sidebar|widget|banner|popup|modal|cookie)', re.I
        )):
            tag.decompose()

        # Supprimer les liens "Retour", "Search", breadcrumbs
        for tag in soup.find_all(
            ['a', 'div', 'span'],
            string=re.compile(r'^(Retour|Search|Recherche|Accueil|Home)', re.I)
        ):
            tag.decompose()

        # Supprimer les éléments de partage social
        for tag in soup.find_all(class_=re.compile(
            r'share|social|newsletter|subscribe|cta', re.I
        )):
            tag.decompose()

        # Supprimer les articles-cartes (grilles d'articles recommandés)
        for tag in soup.find_all('article', class_=re.compile(
            r'elementor-post|elementor-grid-item', re.I
        )):
            tag.decompose()

        # Chercher le contenu principal
        main_content = (
            soup.find(class_=re.compile(r'elementor-location-single', re.I)) or
            soup.find('main') or
            soup.find('article') or
            soup.find(class_=re.compile(
                r'entry-content|post-content|article-body|article-content', re.I
            ))
        )

        if main_content:
            text = main_content.get_text(separator=' ', strip=True)
        else:
            text = soup.get_text(separator=' ', strip=True)

        # Nettoyer les espaces multiples
        text = re.sub(r'\s+', ' ', text)

        # Supprimer les patterns de bruit courants en début/fin
        text = re.sub(
            r'^.*?(Retour aux articles|Search for:)[^.]*\.?\s*',
            '', text, flags=re.I
        )
        text = re.sub(
            r'\s*(Poursuivre la lecture|Vous souhaitez être alerté|Newsletter|Laissez-nous votre e-mail).*$',
            '', text, flags=re.I
        )

        return text.strip()

    @staticmethod
    def _extract_title(html_content: str, fallback: str) -> str:
        """Extrait le <title> d'une page HTML, avec fallback."""
        title_match = re.search(
            r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE
        )
        return title_match.group(1).strip() if title_match else fallback

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalise une URL pour la déduplication (lowercase, sans fragment)."""
        parsed = urlparse(url)
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip('/') or '/',
            parsed.params,
            parsed.query,
            '',  # Pas de fragment
        ))

    @classmethod
    def _extract_links(
        cls,
        html_content: str,
        base_url: str,
        allowed_domains: Set[str],
        url_regex: Optional[re.Pattern] = None,
    ) -> List[str]:
        """Extrait les liens <a href> d'une page HTML.

        Filtre par :
        - Même domaine / sous-domaines (si allowed_domains non vide)
        - Pattern URL regex (si fourni)
        - Exclut ancres, mailto, javascript, fichiers binaires
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        links: List[str] = []

        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()

            # Ignorer ancres, mailto, javascript, tel
            if href.startswith(('#', 'mailto:', 'javascript:', 'tel:')):
                continue

            # Résoudre l'URL relative en absolue
            absolute_url = urljoin(base_url, href)
            parsed = urlparse(absolute_url)

            # Schéma http/https uniquement
            if parsed.scheme not in ('http', 'https'):
                continue

            # Exclure les fichiers binaires
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in cls.EXCLUDED_EXTENSIONS):
                continue

            # Filtrer par domaine si restriction activée
            if allowed_domains:
                link_domain = parsed.netloc.lower()
                parts = link_domain.split('.')
                base_domain = '.'.join(parts[-2:]) if len(parts) >= 2 else link_domain
                if base_domain not in allowed_domains:
                    continue

            # Filtrer par pattern URL si fourni
            if url_regex and not url_regex.search(absolute_url):
                continue

            links.append(absolute_url)

        return links

    @staticmethod
    def _parse_start_urls(config: Dict[str, Any]) -> List[str]:
        """Construit la liste d'URLs de départ depuis la config."""
        url_single = config.get('url')
        urls = config.get('urls', [])

        if url_single:
            return [url_single]
        elif isinstance(urls, str):
            return [u.strip() for u in re.split(r'[,\n]', urls) if u.strip()]
        else:
            return list(urls)

    # ── Providers ────────────────────────────────────────────────────

    async def _fetch_fixed_urls(self) -> List[ContextResult]:
        """Récupère le contenu de URLs fixes configurées."""
        urls = self._parse_start_urls(self.config)
        if not urls:
            return []

        results: List[ContextResult] = []
        headers = {"User-Agent": DEFAULT_USER_AGENT}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            for url in urls[:self.max_results]:
                try:
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()

                    content = self._extract_page_content(response.text)
                    title = self._extract_title(response.text, url)

                    if content:
                        results.append(ContextResult(
                            source_name=self.source_name,
                            source_type=SourceType.WEB,
                            content=content[:2000],
                            source_url=url,
                            metadata={"title": title}
                        ))
                        logger.info(f"Fetched fixed URL: {url} ({len(content)} chars)")

                except Exception as e:
                    logger.warning(f"Failed to fetch fixed URL {url}: {e}")

        return results

    async def _crawl_urls(
        self,
        progress_callback: Optional[Callable[[int, int, str], Awaitable[None]]] = None
    ) -> List[ContextResult]:
        """Crawle récursivement des URLs avec algorithme BFS.

        Config attendue :
        - url / urls : URL(s) de départ
        - max_depth : profondeur maximale (0 = illimité, seul max_pages contrôle)
        - max_pages : nombre maximal de pages (1-500, défaut 50)
        - url_pattern : regex pour filtrer les URLs à suivre (optionnel)
        - same_domain : rester sur le même domaine + sous-domaines (défaut True)
        - request_delay_ms : délai entre les requêtes en ms (défaut 500)

        Args:
            progress_callback: Callback optionnel (current, total, message) pour le suivi
        """
        # Configuration
        start_urls = self._parse_start_urls(self.config)
        max_depth = self.config.get('max_depth', 0)
        max_pages = self.config.get('max_pages', 50)

        logger.info(
            f"Crawl config for '{self.source_name}': max_depth={max_depth}, "
            f"max_pages={max_pages}, start_urls={start_urls}, full_config={self.config}"
        )
        url_pattern_str = self.config.get('url_pattern', '')
        same_domain = self.config.get('same_domain', True)
        request_delay_ms = self.config.get('request_delay_ms', 500)

        if not start_urls:
            return []

        # Domaines autorisés (même domaine + sous-domaines)
        allowed_domains: Set[str] = set()
        if same_domain:
            for url in start_urls:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                parts = domain.split('.')
                base_domain = '.'.join(parts[-2:]) if len(parts) >= 2 else domain
                allowed_domains.add(base_domain)

        # Compiler le pattern URL regex si fourni
        url_regex: Optional[re.Pattern] = None
        if url_pattern_str:
            try:
                url_regex = re.compile(url_pattern_str)
            except re.error:
                logger.warning(f"Pattern URL regex invalide : {url_pattern_str}")

        # BFS : file d'attente (url, depth)
        queue: deque = deque()
        for url in start_urls:
            queue.append((url, 0))

        visited: Set[str] = set()
        results: List[ContextResult] = []

        headers = {"User-Agent": DEFAULT_USER_AGENT}
        delay_seconds = request_delay_ms / 1000.0

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while queue and len(results) < max_pages:
                current_url, depth = queue.popleft()

                # Normaliser pour déduplication
                normalized = self._normalize_url(current_url)
                if normalized in visited:
                    continue
                visited.add(normalized)

                # Rate limiting (sauf première requête)
                if len(visited) > 1 and delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)

                try:
                    response = await client.get(current_url)
                    response.raise_for_status()

                    # Vérifier que c'est du HTML
                    content_type = response.headers.get('content-type', '')
                    if 'text/html' not in content_type.lower():
                        logger.debug(
                            f"Crawl skip non-HTML : {current_url} ({content_type})"
                        )
                        continue

                    html_content = response.text

                    # Extraire le contenu texte
                    page_content = self._extract_page_content(html_content)
                    if not page_content:
                        continue

                    title = self._extract_title(html_content, current_url)

                    results.append(ContextResult(
                        source_name=self.source_name,
                        display_name=self.display_name,
                        source_type=SourceType.WEB,
                        content=page_content[:5000],
                        source_url=current_url,
                        metadata={
                            "title": title,
                            "crawl_depth": depth,
                        }
                    ))
                    logger.info(
                        f"Crawled [{depth}]: {current_url} "
                        f"({len(page_content)} chars, {len(results)}/{max_pages} pages)"
                    )

                    # Notifier la progression
                    if progress_callback:
                        await progress_callback(
                            len(results),
                            max_pages,
                            f"crawling:{len(results)}/{max_pages}"
                        )

                    # Extraire et enqueue les liens si profondeur non atteinte
                    # max_depth == 0 → illimité, sinon respecter la limite
                    if max_depth == 0 or depth < max_depth:
                        links = self._extract_links(
                            html_content, current_url,
                            allowed_domains, url_regex,
                        )
                        for link in links:
                            if self._normalize_url(link) not in visited:
                                queue.append((link, depth + 1))

                except Exception as e:
                    logger.warning(f"Crawl échec {current_url} : {e}")
                    continue

        logger.info(
            f"Crawl terminé : {len(results)} pages, "
            f"{len(visited)} URLs visitées, max_depth={max_depth}"
        )
        return results

    async def health_check(self) -> Dict[str, Any]:
        """Verifie la connexion au provider web"""
        provider = self.config.get('provider', 'duckduckgo')

        try:
            headers = {"User-Agent": DEFAULT_USER_AGENT}
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                if provider == 'duckduckgo':
                    response = await client.get("https://api.duckduckgo.com/?q=test&format=json")
                elif provider == 'google':
                    # Juste verifier que l'API repond
                    response = await client.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params={"key": self.config.get('api_key'), "cx": self.config.get('search_engine_id'), "q": "test"}
                    )
                elif provider == 'wikipedia':
                    response = await client.get("https://fr.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json")
                elif provider == 'custom':
                    url = self.config.get('url')
                    response = await client.get(url)
                elif provider in ('fixed_url', 'crawl'):
                    urls = self._parse_start_urls(self.config)
                    if urls:
                        response = await client.get(urls[0], follow_redirects=True)
                    else:
                        return {"status": "unhealthy", "error": "Aucune URL configurée"}
                else:
                    return {"status": "unhealthy", "error": f"Provider inconnu: {provider}"}

                if response.status_code == 200:
                    return {"status": "healthy"}
                else:
                    return {"status": "unhealthy", "error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
