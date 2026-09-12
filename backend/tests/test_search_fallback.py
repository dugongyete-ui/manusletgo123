"""Tests for the FallbackSearchEngine composite (Tavily primary + fallback).

Covers the QA scenario that motivated it: Tavily's AWS WAF rejects datacenter
IPs with a bare 403 before the API key is validated. The composite must:
- serve via the fallback when the primary fails,
- serve via the primary when it works,
- open the circuit breaker after repeated primary failures and self-heal
  after the cooldown,
- prefer the primary's error message when BOTH providers fail.
"""

from typing import Optional

import pytest

from app.domain.models.search import SearchResultItem, SearchResults
from app.domain.models.tool_result import ToolResult
from app.infrastructure.external.search.fallback_search import FallbackSearchEngine


def _ok(names):
    return ToolResult(
        success=True,
        data=SearchResults(
            query="q",
            date_range=None,
            total_results=len(names),
            results=[
                SearchResultItem(title=n, link=f"https://{n}", snippet="s")
                for n in names
            ],
        ),
    )


def _fail(message):
    return ToolResult(
        success=False,
        message=message,
        data=SearchResults(query="q", date_range=None, total_results=0, results=[]),
    )


class ScriptedEngine:
    """Test double returning scripted results / raising scripted exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def search(self, query: str, date_range: Optional[str] = None):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_primary_failure_serves_fallback():
    primary = ScriptedEngine([_fail("403 Forbidden")])
    fallback = ScriptedEngine([_ok(["bing-1", "bing-2"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    result = await engine.search("q")

    assert result.success is True
    assert [r.title for r in result.data.results] == ["bing-1", "bing-2"]


@pytest.mark.asyncio
async def test_primary_success_skips_fallback():
    primary = ScriptedEngine([_ok(["tavily-1"])])
    fallback = ScriptedEngine([_ok(["bing-1"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    result = await engine.search("q")

    assert result.success is True
    assert [r.title for r in result.data.results] == ["tavily-1"]
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_primary_exception_serves_fallback():
    primary = ScriptedEngine([RuntimeError("boom")])
    fallback = ScriptedEngine([_ok(["bing-1"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    result = await engine.search("q")

    assert result.success is True
    assert [r.title for r in result.data.results] == ["bing-1"]


@pytest.mark.asyncio
async def test_primary_empty_results_uses_fallback():
    # A soft failure (success but zero results) should also degrade.
    primary = ScriptedEngine([_ok([])])
    fallback = ScriptedEngine([_ok(["bing-1"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    result = await engine.search("q")

    assert result.success is True
    assert [r.title for r in result.data.results] == ["bing-1"]


@pytest.mark.asyncio
async def test_both_fail_returns_primary_error():
    primary = ScriptedEngine([_fail("Tavily Search API call failed: 403")])
    fallback = ScriptedEngine([_fail("Bing Web Search failed: timeout")])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    result = await engine.search("q")

    assert result.success is False
    assert "Tavily" in result.message  # configured provider's error wins


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_skips_primary():
    # 1st & 2nd failures: primary still probed. 3rd failure opens the breaker
    # → 4th query goes straight to the fallback without touching the primary.
    primary = ScriptedEngine([_fail("403"), _fail("403"), _fail("403")])
    fallback = ScriptedEngine([_ok(["b1"]), _ok(["b2"]), _ok(["b3"]), _ok(["b4"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    for _ in range(4):
        result = await engine.search("q")
        assert result.success is True

    assert primary.calls == 3  # breaker open: 4th call skipped the primary


@pytest.mark.asyncio
async def test_breaker_cooldown_reprobes_primary():
    primary = ScriptedEngine([_fail("403"), _fail("403"), _fail("403"), _ok(["tavily-back"])])
    fallback = ScriptedEngine([_ok(["b1"]), _ok(["b2"]), _ok(["b3"]), _ok(["b4"]), _ok(["b5"])])
    engine = FallbackSearchEngine(primary, fallback, "tavily", "bing_web")

    # Open the breaker.
    for _ in range(3):
        await engine.search("q")
    assert primary.calls == 3

    # Simulate the cooldown elapsing.
    engine._breaker_opened_at -= FallbackSearchEngine._BREAKER_COOLDOWN_SECONDS

    result = await engine.search("q")

    assert result.success is True
    assert [r.title for r in result.data.results] == ["tavily-back"]
    assert primary.calls == 4  # primary probed again after cooldown
    assert engine._breaker_opened_at is None  # breaker closed after success
