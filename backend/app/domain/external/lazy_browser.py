"""Lazy browser proxy — defers sandbox readiness + CDP connect to first use.

Task creation used to block on `ensure_sandbox()` + `get_browser()` before the
agent could even start planning, adding 30-90 s of silence after the user's
first message (VM resume + Chrome CDP connect). The acknowledgement only needs
the LLM, so the flow is constructed with this proxy instead: the real browser
is connected the first time a browser tool (or the panel screenshot) touches
it — by which time the plan phase has long finished and the sandbox is warm.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


class LazyBrowser:
    """Drop-in async proxy for the Browser protocol.

    Any attribute access returns an async callable that (1) ensures the
    sandbox is running and the real browser is connected (once, under a
    lock), then (2) delegates the call. Private/dunder attributes are
    resolved normally so the proxy's own state stays accessible.
    """

    def __init__(self, sandbox):
        self._sandbox = sandbox
        self._real: object = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._real is not None:
            return self._real
        async with self._lock:
            if self._real is None:
                await self._sandbox.ensure_sandbox()
                self._real = await self._sandbox.get_browser()
                logger.info(
                    "LazyBrowser: connected on first use (sandbox=%s)",
                    getattr(self._sandbox, "id", "?"),
                )
        return self._real

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _call(*args, **kwargs):
            real = await self._ensure()
            return await getattr(real, name)(*args, **kwargs)

        return _call
