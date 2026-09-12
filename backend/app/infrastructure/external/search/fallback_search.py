import time
import logging
from typing import Optional

from app.domain.external.search import SearchEngine
from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)


class FallbackSearchEngine(SearchEngine):
    """Composite search engine: primary provider first, transparent fallback.

    Motivation: Tavily's AWS edge (WAF on the ELB) rejects requests coming from
    some datacenter IP ranges with a bare ``403 Forbidden`` HTML page — the API
    key is never even validated. The SAME key works fine from residential /
    other-cloud networks (e.g. Replit). Instead of hard-wiring one provider,
    this engine tries the configured primary (Tavily) and, when it is
    unreachable/blocked/returns nothing, transparently serves the query via a
    scraping fallback (Bing) so the agent's search tool keeps working on every
    host.

    A small circuit breaker avoids paying the failed primary round-trip on
    every call: after ``_BREAKER_THRESHOLD`` consecutive primary failures the
    primary is skipped for ``_BREAKER_COOLDOWN_SECONDS`` (then probed again so
    the engine self-heals when the block is lifted or the app moves networks).
    """

    _BREAKER_THRESHOLD = 3
    _BREAKER_COOLDOWN_SECONDS = 600.0  # 10 minutes

    def __init__(
        self,
        primary: SearchEngine,
        fallback: SearchEngine,
        primary_name: str = "primary",
        fallback_name: str = "fallback",
    ):
        self._primary = primary
        self._fallback = fallback
        self._primary_name = primary_name
        self._fallback_name = fallback_name
        # Circuit-breaker state (engine instances are singletons via
        # get_search_engine()'s lru_cache, so this state persists per process).
        self._primary_failures = 0
        self._breaker_opened_at: Optional[float] = None

    # ── Circuit breaker ────────────────────────────────────────────────────
    def _breaker_open(self) -> bool:
        if self._breaker_opened_at is None:
            return False
        if time.monotonic() - self._breaker_opened_at >= self._BREAKER_COOLDOWN_SECONDS:
            # Cooldown elapsed — re-probe the primary (self-healing).
            logger.info(
                "Search fallback breaker: cooldown elapsed, retrying primary "
                "provider '%s'", self._primary_name,
            )
            self._breaker_opened_at = None
            self._primary_failures = 0
            return False
        return True

    def _record_primary_failure(self) -> None:
        self._primary_failures += 1
        if self._primary_failures >= self._BREAKER_THRESHOLD:
            self._breaker_opened_at = time.monotonic()
            logger.warning(
                "Search provider '%s' failed %d times in a row — skipping it "
                "for %ds (queries served by '%s' meanwhile; will re-probe "
                "automatically)",
                self._primary_name, self._primary_failures,
                int(self._BREAKER_COOLDOWN_SECONDS), self._fallback_name,
            )

    def _record_primary_success(self) -> None:
        if self._primary_failures or self._breaker_opened_at is not None:
            logger.info(
                "Search provider '%s' recovered — serving queries again",
                self._primary_name,
            )
        self._primary_failures = 0
        self._breaker_opened_at = None

    # ── SearchEngine API ───────────────────────────────────────────────────
    async def search(
        self,
        query: str,
        date_range: Optional[str] = None,
    ) -> ToolResult:
        primary_result: Optional[ToolResult] = None
        # 1) Try the primary provider (unless the breaker is open).
        if self._breaker_open():
            logger.info(
                "Search: primary '%s' on cooldown — going straight to fallback "
                "'%s'", self._primary_name, self._fallback_name,
            )
        else:
            try:
                result = await self._primary.search(query, date_range)
            except Exception as exc:  # defensive: engines normally catch
                logger.error(
                    "Search: primary '%s' raised %s: %s",
                    self._primary_name, type(exc).__name__, exc,
                )
                result = None

            if result is not None and result.success and result.data and result.data.results:
                self._record_primary_success()
                logger.info(
                    "Search: served by primary '%s' (%d results)",
                    self._primary_name, len(result.data.results),
                )
                return result

            # Primary failed or returned nothing useful.
            reason = (
                result.message if result is not None and result.message
                else "no results"
            )
            logger.warning(
                "Search: primary '%s' unusable (%s) — falling back to '%s'",
                self._primary_name, reason, self._fallback_name,
            )
            self._record_primary_failure()
            primary_result = result

        # 2) Serve via the fallback provider.
        try:
            fb_result = await self._fallback.search(query, date_range)
        except Exception as exc:  # defensive
            logger.error(
                "Search: fallback '%s' raised %s: %s",
                self._fallback_name, type(exc).__name__, exc,
            )
            fb_result = None

        if fb_result is not None and fb_result.success and fb_result.data and fb_result.data.results:
            logger.info(
                "Search: served by fallback '%s' (%d results)",
                self._fallback_name, len(fb_result.data.results),
            )
            return fb_result

        # 3) Both unusable — prefer the primary's error (it describes the
        #    CONFIGURED provider, which is what the operator needs to see).
        if fb_result is not None and fb_result.message:
            logger.error(
                "Search: fallback '%s' failed too: %s",
                self._fallback_name, fb_result.message,
            )
        if primary_result is not None:
            return primary_result
        if fb_result is not None:
            return fb_result

        # Neither engine produced a ToolResult (both raised) — synthesize one.
        from app.domain.models.search import SearchResults
        return ToolResult(
            success=False,
            message=(
                f"All search providers failed: primary '{self._primary_name}' "
                f"and fallback '{self._fallback_name}' are unreachable."
            ),
            data=SearchResults(
                query=query, date_range=date_range,
                total_results=0, results=[],
            ),
        )
