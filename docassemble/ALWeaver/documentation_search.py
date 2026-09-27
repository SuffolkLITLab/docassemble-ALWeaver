"""Bounded search of the public AssemblyLine documentation index.

The documentation site uses Algolia DocSearch. Its search-only credentials are
already shipped to every browser in the Docusaurus configuration, so Weaver can
reuse the same public index without introducing a server secret or a new search
service.

Only the fixed AssemblyLine documentation index is reachable here. Query text is
the only caller-controlled input, result counts and excerpts are bounded, and
links outside the official documentation hosts are discarded before results are
returned to the editing agent.
"""

from __future__ import annotations

from html import unescape
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

ALGOLIA_APP_ID = "883YGW898U"
ALGOLIA_SEARCH_KEY = "b1e22430da6c3e88d00976160b2f3216"
ALGOLIA_INDEX = "AssemblyLine_Documentation"
ALGOLIA_QUERY_URL = (
    f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/"
    f"{ALGOLIA_INDEX}/query"
)

DEFAULT_RESULT_LIMIT = 5
MAX_QUERY_CHARS = 300
MAX_EXCERPT_CHARS = 1600
REQUEST_TIMEOUT_SECONDS = 5

_OFFICIAL_HOSTS = frozenset(
    {
        "assemblyline.suffolklitlab.org",
        "suffolklitlab.org",
    }
)


class DocumentationSearchError(RuntimeError):
    """Raised when the fixed documentation search cannot return usable data."""


def _compact_text(value: Any, *, limit: int = MAX_EXCERPT_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(unescape(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _official_url(value: Any) -> str:
    """Return a canonical official documentation URL, or an empty string."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _OFFICIAL_HOSTS:
        return ""

    path = parsed.path or "/"
    if host == "suffolklitlab.org" and not path.startswith(
        "/docassemble-AssemblyLine-documentation/"
    ):
        return ""
    if host == "assemblyline.suffolklitlab.org":
        # Mirror the current Docusaurus DocSearch pathname rewrite.
        if path == "/docs":
            path = "/"
        elif path.startswith("/docs/"):
            path = path[len("/docs") :]

    return urlunsplit(("https", host, path, parsed.query, parsed.fragment))


def _breadcrumbs(hit: Dict[str, Any]) -> List[str]:
    hierarchy = hit.get("hierarchy")
    if not isinstance(hierarchy, dict):
        return []
    rows: List[str] = []
    for level in range(7):
        value = _compact_text(hierarchy.get(f"lvl{level}"), limit=300)
        if value and (not rows or rows[-1] != value):
            rows.append(value)
    return rows


def _normalize_hit(hit: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(hit, dict):
        return None
    url = _official_url(hit.get("url") or hit.get("url_without_anchor"))
    if not url:
        return None
    breadcrumbs = _breadcrumbs(hit)
    title = breadcrumbs[-1] if breadcrumbs else _compact_text(hit.get("content"), limit=300)
    excerpt = _compact_text(hit.get("content"))
    return {
        "title": title,
        "breadcrumbs": breadcrumbs,
        "excerpt": excerpt,
        "url": url,
    }


def search_documentation(
    query: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> List[Dict[str, Any]]:
    """Search the public AssemblyLine DocSearch index.

    The response is deliberately much smaller than Algolia's raw hit structure:
    enough text for the model to answer or choose a safe edit, without replaying
    highlighting metadata or unbounded page content into the agent transcript.
    """
    query = str(query or "").strip()
    if not query:
        return []
    query = query[:MAX_QUERY_CHARS]

    request = Request(
        ALGOLIA_QUERY_URL,
        data=json.dumps(
            {
                "query": query,
                "hitsPerPage": DEFAULT_RESULT_LIMIT,
                "attributesToRetrieve": [
                    "hierarchy",
                    "content",
                    "url",
                    "url_without_anchor",
                ],
                "attributesToHighlight": [],
                "attributesToSnippet": [],
            }
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
        },
        method="POST",
    )

    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise DocumentationSearchError("Documentation search is unavailable") from exc

    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        raise DocumentationSearchError("Documentation search returned an invalid response")

    results: List[Dict[str, Any]] = []
    for hit in hits:
        normalized = _normalize_hit(hit)
        if normalized is not None:
            results.append(normalized)
        if len(results) >= DEFAULT_RESULT_LIMIT:
            break
    return results
