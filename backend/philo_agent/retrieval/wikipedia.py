import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

try:
    import requests
except Exception:  # pragma: no cover - requests may be missing in some envs
    requests = None

logger = logging.getLogger(__name__)

WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"


def fetch_wikipedia_summary(title: str) -> Optional[Dict[str, Any]]:
    """Fetch the Wikipedia summary for a page title. Returns dict with 'title','summary','url' or None."""
    if not requests:
        logger.warning("requests package is not installed; cannot fetch Wikipedia summaries")
        return None
    if not title:
        return None
    try:
        url = WIKI_SUMMARY_URL.format(quote(title))
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # The summary endpoint returns 'extract' and 'content_urls'
        extract = data.get("extract") or data.get("description")
        page_url = None
        content_urls = data.get("content_urls")
        if content_urls and isinstance(content_urls, dict):
            page_url = content_urls.get("desktop", {}).get("page")
        if not page_url:
            page_url = data.get("canonical_url") or data.get("url")
        return {"title": data.get("title", title), "summary": extract, "url": page_url}
    except Exception as e:
        logger.debug("Wikipedia fetch failed for %s: %s", title, e)
        return None


def enrich_tavily_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Given a list of tavily search result dicts, attempt to attach a Wikipedia summary.

    Each result will get an additional key `wikipedia` with a dict or None.
    This function makes a best-effort to find a suitable title from keys like 'title', 'query', or 'text'.
    """
    enriched: List[Dict[str, Any]] = []
    for res in results:
        # copy so we don't mutate input
        item = dict(res)
        title_candidate = None
        for k in ("title", "query", "heading"):
            if k in res and isinstance(res[k], str) and res[k].strip():
                title_candidate = res[k].strip()
                break
        if not title_candidate:
            text = res.get("text") or res.get("snippet") or ""
            if isinstance(text, str) and text.strip():
                # fallback: take first sentence
                title_candidate = text.strip().split(".")[0][:200]
        wiki = None
        if title_candidate:
            wiki = fetch_wikipedia_summary(title_candidate)
        item["wikipedia"] = wiki
        enriched.append(item)
    return enriched
