from functools import lru_cache
from typing import Optional
import logging

from app.domain.external.search import SearchEngine
from app.core.config import get_settings

logger = logging.getLogger(__name__)

@lru_cache()
def get_search_engine() -> Optional[SearchEngine]:
    """Get search engine instance based on configuration"""
    from app.infrastructure.external.search.google_search import GoogleSearchEngine
    from app.infrastructure.external.search.baidu_search import BaiduSearchEngine
    from app.infrastructure.external.search.baidu_web_search import BaiduWebSearchEngine
    from app.infrastructure.external.search.bing_search import BingSearchEngine
    from app.infrastructure.external.search.bing_web_search import BingWebSearchEngine
    from app.infrastructure.external.search.bing_rss_search import BingRssSearchEngine
    from app.infrastructure.external.search.tavily_search import TavilySearchEngine
    
    settings = get_settings()
    if settings.search_provider == "google":
        if settings.google_search_api_key and settings.google_search_engine_id:
            logger.info("Initializing Google Search Engine")
            return GoogleSearchEngine(
                api_key=settings.google_search_api_key,
                cx=settings.google_search_engine_id
            )
        else:
            logger.warning("Google Search Engine not initialized: missing API key or engine ID")
    elif settings.search_provider == "baidu":
        if settings.baidu_search_api_key:
            logger.info("Initializing Baidu Search Engine (API)")
            return BaiduSearchEngine(api_key=settings.baidu_search_api_key)
        else:
            logger.warning("Baidu Search Engine not initialized: missing API key (BAIDU_SEARCH_API_KEY)")
    elif settings.search_provider == "baidu_web":
        logger.info("Initializing Baidu Web Search Engine (scraping)")
        return BaiduWebSearchEngine()
    elif settings.search_provider == "bing":
        if settings.bing_search_api_key:
            logger.info("Initializing Bing Search Engine (API)")
            return BingSearchEngine(api_key=settings.bing_search_api_key)
        else:
            logger.warning("Bing Search Engine not initialized: missing API key (BING_SEARCH_API_KEY)")
    elif settings.search_provider == "bing_web":
        logger.info("Initializing Bing Web Search Engine (scraping)")
        return BingWebSearchEngine()
    elif settings.search_provider == "bing_rss":
        logger.info("Initializing Bing RSS Search Engine (web + news, no API key)")
        return BingRssSearchEngine()
    elif settings.search_provider == "tavily":
        if settings.tavily_api_key:
            from app.infrastructure.external.search.fallback_search import FallbackSearchEngine

            primary = TavilySearchEngine(api_key=settings.tavily_api_key)
            # Tavily's edge (AWS WAF) blocks some datacenter IP ranges with a
            # bare 403 before the key is even validated. Wrap it with an
            # automatic scraping fallback so search works from every host:
            # on networks where Tavily is reachable it serves every query,
            # otherwise we transparently degrade to the fallback provider.
            fallback_provider = (settings.search_fallback_provider or "bing_rss").strip().lower()
            fallback = None
            if fallback_provider == "bing_rss":
                fallback = BingRssSearchEngine()
            elif fallback_provider == "bing_web":
                fallback = BingWebSearchEngine()
            elif fallback_provider == "baidu_web":
                from app.infrastructure.external.search.baidu_web_search import BaiduWebSearchEngine
                fallback = BaiduWebSearchEngine()
            if fallback is not None:
                logger.info(
                    "Initializing Tavily Search Engine (primary) with '%s' "
                    "fallback (auto-used when Tavily is unreachable, e.g. "
                    "datacenter IPs blocked by Tavily's WAF)", fallback_provider,
                )
                return FallbackSearchEngine(
                    primary=primary,
                    fallback=fallback,
                    primary_name="tavily",
                    fallback_name=fallback_provider,
                )
            logger.info("Initializing Tavily Search Engine (no fallback)")
            return primary
        else:
            logger.warning("Tavily Search Engine not initialized: missing API key")
    else:
        logger.warning(f"Unknown search provider: {settings.search_provider}")
    
    return None 