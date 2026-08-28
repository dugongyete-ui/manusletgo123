"""Bing RSS search engine — web + news results via Bing's RSS endpoints.

Why: Bing's HTML results page now serves severely degraded/bot-flagged markup
to datacenter IPs (unrelated homepages such as WhatsApp/VnExpress for an AI
query), while the ``format=rss`` endpoints keep returning genuine results:
  * ``/search?q=…&format=rss``            → strong for English/general queries
  * ``/news/search?q=…&format=rss``       → real articles, supports any language
This engine fans out to BOTH endpoints in parallel, extracts the real
destination URL from the ``apiclick.aspx?url=…`` redirect wrapper, merges and
de-duplicates the items (interleaved for diversity), and applies light
client-side date filtering on news items (the only ones carrying ``pubDate``).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

from curl_cffi.requests import AsyncSession

from app.domain.external.search import SearchEngine
from app.domain.models.search import SearchResultItem, SearchResults
from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)

_MAX_RESULTS = 10
_CANDIDATE_POOL = 24
_REQUEST_TIMEOUT = 25

# Freshness filter for the /search endpoint (same values the HTML UI uses).
_WEB_FRESHNESS_FILTERS = {
    "past_hour": 'ex1:"ez1"',
    "past_day": 'ex1:"ez2"',
    "past_week": 'ex1:"ez3"',
    "past_month": 'ex1:"ez4"',
    "past_year": 'ex1:"ez5"',
}

# Client-side window for /news items (they carry pubDate).
_NEWS_WINDOW = {
    "past_hour": timedelta(hours=1),
    "past_day": timedelta(days=1),
    "past_week": timedelta(days=7),
    "past_month": timedelta(days=31),
    "past_year": timedelta(days=365),
}


def _real_url(link: str) -> str:
    """Unwrap Bing's ``apiclick.aspx?...&url=<encoded>`` redirect links."""
    try:
        parsed = urlparse(link)
        if "apiclick.aspx" in (parsed.path or "") or "bing.com" in (parsed.netloc or ""):
            values = parse_qs(parsed.query).get("url", [])
            if values:
                return unquote(values[0])
    except Exception:
        pass
    return link


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


_TOKEN_STOPWORDS = frozenset(
    "the a an of for and or to in on with latest new news terbaru terkini "
    "berita cara dan yang di ke dari untuk apa itu ini adalah dengan tentang "
    "berapa bagaimanan ini how what best top".split()
)


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens (ascii + unicode letters), no stopwords."""
    tokens = re.findall(r"[\w']+", (text or "").lower(), re.UNICODE)
    return {t for t in tokens if len(t) > 1 and t not in _TOKEN_STOPWORDS}


def _parse_pub_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # RFC 822: 'Wed, 23 Oct 2024 06:54:00 GMT'
        return datetime.strptime(raw.strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


class BingRssSearchEngine(SearchEngine):
    """Bing search via the public RSS endpoints (no API key required)."""

    def __init__(self):
        self.web_url = "https://www.bing.com/search"
        self.news_url = "https://www.bing.com/news/search"

    async def _fetch_rss_items(self, session: AsyncSession, url: str, params: dict) -> list:
        response = None
        try:
            response = await session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
        except Exception as exc:
            status = getattr(response, "status_code", "?")
            body = ""
            try:
                body = (response.text or "")[:200] if response is not None else ""
            except Exception:
                pass
            logger.warning(
                "Bing RSS fetch failed (%s %s): %s [status=%s body=%r]",
                url, params, exc, status, body,
            )
            return []

        items = []
        for element in root.iter("item"):
            title = _strip_html(element.findtext("title") or "")
            link = (element.findtext("link") or "").strip()
            description = _strip_html(element.findtext("description") or "")
            pub_date = _parse_pub_date(element.findtext("pubDate"))
            if not title or not link:
                continue
            items.append(
                (
                    SearchResultItem(
                        title=title,
                        link=_real_url(link),
                        snippet=description,
                    ),
                    pub_date,
                )
            )
        return items

    async def search(
        self,
        query: str,
        date_range: Optional[str] = None,
    ) -> ToolResult[SearchResults]:
        web_params: dict[str, str] = {
            "q": query,
            "count": "15",
            "format": "rss",
        }
        if date_range and date_range != "all":
            freshness = _WEB_FRESHNESS_FILTERS.get(date_range)
            if freshness:
                web_params["filters"] = freshness

        # Fan out to three endpoints in parallel — Bing's RSS quality is
        # market-sensitive (forcing mkt=en-US breaks Indonesian queries, the
        # geo default biases English queries towards SEA portals), so both web
        # variants are queried and merged with the news vertical.
        web_en_params = dict(web_params, mkt="en-US")

        news_params: dict[str, str] = {
            "q": query,
            "format": "rss",
        }

        async with AsyncSession(impersonate="chrome") as session:
            fetches = (
                self._fetch_rss_items(session, self.web_url, web_params),
                self._fetch_rss_items(session, self.web_url, web_en_params),
                self._fetch_rss_items(session, self.news_url, news_params),
            )
            web_items, web_en_items, news_items = await asyncio.gather(*fetches)

        # Client-side freshness filtering on news items (only they have dates).
        window = _NEWS_WINDOW.get(date_range or "")
        if window is not None:
            cutoff = datetime.now(timezone.utc) - window
            news_items = [
                (item, pub)
                for item, pub in news_items
                if pub is None or pub >= cutoff
            ]

        # Merge: round-robin across the three sources for diversity, dedupe.
        # Collect a wider candidate pool than _MAX_RESULTS so the lexical
        # ranking below can pick the best items instead of the first ones.
        sources = [web_items, web_en_items, news_items]
        merged: list[SearchResultItem] = []
        seen: set[str] = set()
        for i in range(max((len(s) for s in sources), default=0)):
            for entries in sources:
                if i >= len(entries):
                    continue
                item = entries[i][0]
                key = (item.link or "").split("#")[0].rstrip("/")
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= _CANDIDATE_POOL:
                    break
            if len(merged) >= _CANDIDATE_POOL:
                break

        # Rank by lexical relevance (language-agnostic): count how many distinct
        # query terms appear in the title (x2) and snippet (x1). This kills the
        # random-garbage pages Bing sometimes returns to datacenter IPs (login
        # portals, unrelated homepages) because their text shares no query
        # terms, while genuine articles survive regardless of language.
        query_tokens = _tokenize(query)

        def _relevance(item: SearchResultItem) -> float:
            if not query_tokens:
                return 0.0
            title_tokens = set(_tokenize(item.title))
            snippet_tokens = set(_tokenize(item.snippet))
            score = 2.0 * len(query_tokens & title_tokens)
            score += 1.0 * len(query_tokens & snippet_tokens)
            return score

        # De-prioritise bare homepages ("https://cnn.com/", "https://detik.com")
        # — they carry no query-specific information.
        def _is_homepage(item: SearchResultItem) -> bool:
            try:
                parsed = urlparse(item.link or "")
                return parsed.scheme in ("http", "https") and parsed.netloc and not (parsed.path or "").strip("/") and not parsed.query
            except Exception:
                return False

        ranked = sorted(
            merged,
            key=lambda item: (
                -_relevance(item) - (1.0 if _is_homepage(item) else 0.0),
            ),
        )[:_MAX_RESULTS]
        # Stable within equal scores (source diversity order preserved).

        results = SearchResults(
            query=query,
            date_range=date_range,
            total_results=len(ranked),
            results=ranked,
        )
        if not ranked:
            return ToolResult(
                success=False,
                message=f"Bing RSS search returned no results for: {query}",
                data=results,
            )
        logger.info(
            "Bing RSS search: %d web(geo) + %d web(en) + %d news items → %d "
            "merged for %r",
            len(web_items), len(web_en_items), len(news_items), len(merged), query,
        )
        return ToolResult(success=True, data=results)


if __name__ == "__main__":
    import asyncio

    async def test():
        engine = BingRssSearchEngine()
        for q in ("berita teknologi AI terbaru", "latest AI technology news 2026", "resep rendang padang"):
            result = await engine.search(q)
            print(f"\n=== {q} (success={result.success}) ===")
            for item in (result.data.results if result.data else [])[:5]:
                print(f"- {item.title[:65]}\n    {item.link[:75]}")

    asyncio.run(test())
