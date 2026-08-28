"""Lazy sandbox proxy — decouples task creation from VM allocation.

E2B sandbox creation cold-boots a microVM (30-60 s in this environment).
Task creation used to wait for that boot under the session lock, delaying the
first assistant acknowledgement by up to a minute. The runner is now handed
this proxy instead: the real sandbox is allocated/resumed on FIRST use —
which happens in the runner's background ensure task while the ack + plan
already stream to the user.

Static configuration attributes (user_home / upload_dir / provider / shared)
mirror E2BSandbox's values because the proxy is only used on the E2B route.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


class LazySandbox:
    """Drop-in async proxy for the E2B Sandbox.

    Sync config attributes are answered immediately (matching E2BSandbox).
    Every other attribute resolves to an async callable that (1) allocates
    the real sandbox via the resolver (once, under a lock), (2) runs
    ensure_sandbox(), then (3) delegates the call. Lifecycle methods that
    must not FORCE a boot (pause, has_vnc_viewers) are special-cased to
    no-op while the sandbox has never been resolved.
    """

    # Static E2B configuration — mirrors E2BSandbox
    provider = "e2b"
    shared = False

    def __init__(self, resolver):
        """:param resolver: async callable(replace: bool = False) -> Sandbox.
        With replace=True the resolver must allocate a FRESH sandbox (used
        for self-healing when the current VM's bootstrap keeps failing —
        e.g. a bad E2B pool host with broken apt)."""
        self._resolver = resolver
        self._real = None
        self._lock = asyncio.Lock()
        self._bootstrap_failures = 0

    # -- static config -----------------------------------------------------
    @property
    def user_home(self) -> str:
        return "/home/user"

    @property
    def upload_dir(self) -> str:
        return "/home/user/upload"

    @property
    def id(self) -> str:
        rid = getattr(self._real, "id", None) if self._real is not None else None
        return rid or "pending"

    # -- lifecycle ----------------------------------------------------------
    @property
    def resolved(self) -> bool:
        """True once the real sandbox has been allocated. Lets callers skip
        optional sandbox work (e.g. the home-baseline scan) instead of
        blocking on a cold VM boot."""
        return self._real is not None

    async def _ensure(self):
        """Resolve + boot the real sandbox exactly once.

        Self-healing: when the resolved VM's bootstrap fails twice in a row
        (bad pool host, broken apt, dead disk), it is replaced with a FRESH
        sandbox via the resolver instead of retrying the same broken VM
        forever (previously a task could hang for 10+ minutes on one bad VM).
        """
        async with self._lock:
            if self._real is None:
                self._real = await self._resolver()
            try:
                await self._real.ensure_sandbox()
                self._bootstrap_failures = 0
            except Exception as exc:
                self._bootstrap_failures += 1
                if self._bootstrap_failures < 2:
                    raise
                logger.warning(
                    "LazySandbox: VM %s failed bootstrap %d times (%s) — "
                    "replacing with a fresh sandbox",
                    self._real.id, self._bootstrap_failures, str(exc)[:120],
                )
                old = self._real
                self._real = None
                self._bootstrap_failures = 0
                try:
                    self._real = await self._resolver(replace=True)
                except TypeError:
                    # Resolver without replace support — fall back to plain call
                    self._real = await self._resolver()
                await self._real.ensure_sandbox()
                # Best-effort cleanup of the broken VM (never blocks the task)
                try:
                    await old.pause()
                except Exception:
                    pass
        return self._real

    async def pause(self, *args, **kwargs):
        # Never boot a sandbox just to pause it — if it was never resolved,
        # nothing is running and there is nothing to pause.
        if self._real is None:
            logger.debug("LazySandbox.pause skipped — sandbox never booted")
            return
        return await self._real.pause(*args, **kwargs)

    async def has_vnc_viewers(self, *args, **kwargs):
        if self._real is None:
            return False
        return await self._real.has_vnc_viewers(*args, **kwargs)

    async def destroy(self, *args, **kwargs):
        if self._real is None:
            return
        return await self._real.destroy(*args, **kwargs)

    # -- delegation ----------------------------------------------------------
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _call(*args, **kwargs):
            real = await self._ensure()
            return await getattr(real, name)(*args, **kwargs)

        return _call
