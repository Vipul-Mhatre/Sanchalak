"""
Live docs retrieval tool.
Fetches content from docs.flytbase.com and releases.flytbase.com at query time
using GitBook's site-index API for search, then fetching relevant pages.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class DocPassage:
    """A passage from a docs page with source attribution."""
    url: str
    title: str
    content: str
    source_site: str  # "docs" or "releases"
    breadcrumbs: str = ""


@dataclass
class CacheEntry:
    """Cache entry with TTL."""
    data: any
    timestamp: float
    ttl: float = 300.0  # 5 minutes

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------

_cache: dict[str, CacheEntry] = {}


def _get_cached(key: str) -> Optional[any]:
    """Get from cache if not expired."""
    entry = _cache.get(key)
    if entry and not entry.is_expired:
        return entry.data
    return None


def _set_cache(key: str, data: any, ttl: float = 300.0):
    """Set cache entry."""
    _cache[key] = CacheEntry(data=data, timestamp=time.time(), ttl=ttl)


# ---------------------------------------------------------------------------
# Site index
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "were", "have", "has", "its", "their", "them", "they", "you", "your",
    "how", "what", "which", "when", "where", "who", "why", "will", "can",
    "into", "about", "over", "under", "also", "then", "than", "there",
    "other", "only", "more", "most", "some", "such", "all", "any", "per",
    "not", "but", "may", "now", "out", "one", "two", "up", "get", "use",
    "used", "using", "via", "etc", "id", "ids",
}

SITES = {
    "docs": "https://docs.flytbase.com",
    "releases": "https://releases.flytbase.com",
}


async def fetch_site_index(site_key: str) -> list[dict]:
    """
    Fetch the GitBook site-index JSON for a site.
    Returns list of page objects with id, title, pathname, description, breadcrumbs.
    """
    base_url = SITES[site_key]
    cache_key = f"site_index_{site_key}"

    # Try cache first
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{base_url}/~gitbook/site-index"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("pages", [])
            _set_cache(cache_key, pages, ttl=300.0)
            return pages
    except Exception as e:
        # Fallback to cache even if expired
        entry = _cache.get(cache_key)
        if entry:
            return entry.data
        print(f"[docs_fetcher] Failed to fetch site index for {site_key}: {e}")
        return []


def _score_page(page: dict, query_terms: list[str]) -> float:
    """Score a page against query terms using simple keyword matching."""
    title = (page.get("title") or "").lower()
    description = (page.get("description") or "").lower()
    breadcrumbs_text = " ".join(
        [b.get("label", "") for b in page.get("breadcrumbs", [])]
    ).lower()
    searchable = f"{title} {description} {breadcrumbs_text}"

    score = 0.0
    for term in query_terms:
        term_lower = term.lower()
        if term_lower in title:
            score += 3.0  # Title match is strongest
        if term_lower in description:
            score += 2.0
        if term_lower in breadcrumbs_text:
            score += 1.0
    return score


async def search_pages(query: str, top_n: int = 5) -> list[dict]:
    """
    Search across both docs and releases sites.
    Returns top-N matching pages sorted by relevance.
    """
    query_terms = [t for t in query.lower().split() if len(t) > 2 and t not in STOPWORDS]
    query_terms = [t.rstrip(":") for t in query_terms]
    query_terms = [t for t in query_terms if not t.startswith("fr-") and not t.startswith("(")]

    all_results = []
    for site_key in SITES:
        pages = await fetch_site_index(site_key)
        for page in pages:
            score = _score_page(page, query_terms)
            if score > 0:
                base_url = SITES[site_key]
                pathname = page.get("pathname", "/")
                all_results.append({
                    "site": site_key,
                    "title": page.get("title", ""),
                    "url": f"{base_url}{pathname}",
                    "description": page.get("description", ""),
                    "breadcrumbs": " > ".join(
                        [b.get("label", "") for b in page.get("breadcrumbs", [])]
                    ),
                    "score": score,
                })

    # Sort by score descending
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_n]


async def fetch_page_content(url: str) -> str:
    """
    Fetch a page and extract text content.
    Uses cache with fallback.
    """
    cache_key = f"page_{url}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()

        # Try to find main content area
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            return ""

        text = main.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        # Truncate to reasonable size for LLM context
        if len(clean_text) > 4000:
            clean_text = clean_text[:4000] + "\n[... content truncated ...]"

        _set_cache(cache_key, clean_text, ttl=300.0)
        return clean_text

    except Exception as e:
        # Fallback to cache even if expired
        entry = _cache.get(cache_key)
        if entry:
            return entry.data
        print(f"[docs_fetcher] Failed to fetch page {url}: {e}")
        return ""


async def fetch_docs(query: str) -> list[DocPassage]:
    """
    Main entry point: search for relevant pages, fetch their content,
    return passages with source URLs.
    """
    # Search for matching pages
    matching_pages = await search_pages(query, top_n=3)

    passages = []
    for page in matching_pages:
        content = await fetch_page_content(page["url"])
        if content:
            passages.append(DocPassage(
                url=page["url"],
                title=page["title"],
                content=content,
                source_site=page["site"],
                breadcrumbs=page.get("breadcrumbs", ""),
            ))

    # If no keyword matches, try fetching a general page as fallback
    if not passages:
        # Try fetching the main docs page for general questions
        for site_key in SITES:
            pages = await fetch_site_index(site_key)
            if pages:
                # Take first 2 pages as general context
                for page in pages[:2]:
                    base_url = SITES[site_key]
                    pathname = page.get("pathname", "/")
                    url = f"{base_url}{pathname}"
                    content = await fetch_page_content(url)
                    if content:
                        passages.append(DocPassage(
                            url=url,
                            title=page.get("title", ""),
                            content=content[:2000],
                            source_site=site_key,
                            breadcrumbs=" > ".join(
                                [b.get("label", "") for b in page.get("breadcrumbs", [])]
                            ),
                        ))

    return passages


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def test():
        print("=== Testing docs fetcher ===\n")

        # Test 1: Search for mission scheduling
        print("--- Query: 'mission scheduler scheduling' ---")
        results = await search_pages("mission scheduler scheduling")
        for r in results[:3]:
            print(f"  [{r['site']}] {r['title']} (score={r['score']:.1f})")
            print(f"    URL: {r['url']}")

        # Test 2: Search for SSO / enterprise features
        print("\n--- Query: 'SSO single sign-on enterprise' ---")
        results = await search_pages("SSO single sign-on enterprise")
        for r in results[:3]:
            print(f"  [{r['site']}] {r['title']} (score={r['score']:.1f})")
            print(f"    URL: {r['url']}")

        # Test 3: Full fetch_docs
        print("\n--- Full fetch_docs('webhook mission events') ---")
        passages = await fetch_docs("webhook mission events")
        for p in passages:
            print(f"  [{p.source_site}] {p.title}")
            print(f"    URL: {p.url}")
            print(f"    Content preview: {p.content[:150]}...")

    asyncio.run(test())
