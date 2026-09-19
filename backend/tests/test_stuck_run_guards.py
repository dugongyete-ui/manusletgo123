"""Anti-stuck guards for the agent runtime (Persib-session incident).

Root cause of the reported "AI berpikir terus, tidak jalan": the runner's
wall-clock checkpoints only fire BETWEEN flow events — a hung tool call
(wedged browser init retrying a dead Chrome) blocks the pump and no
checkpoint ever fires, so the session sat RUNNING with zero progress for
~12 minutes while the user watched eternal "thinking".

Three layers are enforced here:
1. Runner watchdog  — run() supervises _run_impl and cancels it at the
   wall clock even when the pump is blocked; the session ends CANCELLED
   (resumable) with an explicit overtime notice.
2. Gate tool ceiling — one tool execution (all transports, retries
   included) can never exceed manus_tool_timeout_seconds; the model gets
   an honest TIMEOUT failure payload instead of an eternal await.
3. Browser hygiene  — stale tabs are closed before session init (they
   starve browser_use's start() watchdog) and a wedged Chrome triggers
   the heal hook instead of endless plain retries.
"""

import asyncio
import urllib.request

import pytest

from app.domain.services.agent_task_runner import AgentTaskRunner
from app.domain.services.manus_registry.gate import ManusGate
from app.infrastructure.external.browser import browser_use_browser as bub


# ─────────────────────────────────────────────────────────────────────────────
# Harness
#─────────────────────────────────────────────────────────────────────────────


class _FakeQueue:
    async def put(self, event_json):
        return "id-1"


class _FakeTask:
    def __init__(self):
        self.output_stream = _FakeQueue()


class _FakeSessionRepo:
    def __init__(self):
        self.statuses = []

    async def update_status(self, session_id, status):
        self.statuses.append((session_id, status))


class _FakeSettings:
    def __init__(self, task_timeout_ms, tool_timeout_seconds=300.0):
        self.manus_task_timeout_ms = task_timeout_ms
        self.manus_tool_timeout_seconds = tool_timeout_seconds


def _runner_skeleton():
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._agent_id = "test-agent"
    runner._session_id = "sess-test"
    runner._user_id = "test-user"
    runner._run_task_id = "run-1"
    runner._run_failed = False
    runner._timed_out = False
    runner._session_repository = _FakeSessionRepo()
    return runner


# ─────────────────────────────────────────────────────────────────────────────
# 1. Runner watchdog — the pump being blocked can no longer hide overtime
#─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watchdog_finalizes_hung_run_as_resumable(monkeypatch):
    """_run_impl hangs forever (stuck tool) → watchdog cancels it → the
    session is finalized CANCELLED with the overtime notice (resumable),
    never left RUNNING."""
    from app.domain.models.event import MessageEvent

    runner = _runner_skeleton()
    emitted = []

    async def _hung_impl(task):
        await asyncio.sleep(999)  # never returns — the incident, distilled

    async def _fake_put(task, event):
        emitted.append(event)

    monkeypatch.setattr(runner, "_run_impl", _hung_impl)
    monkeypatch.setattr(runner, "_put_and_add_event", _fake_put)
    monkeypatch.setattr(
        "app.domain.services.agent_task_runner.get_settings",
        lambda: _FakeSettings(task_timeout_ms=300),  # 0.3 s budget
    )

    await asyncio.wait_for(runner.run(_FakeTask()), timeout=10)

    assert runner._timed_out is True
    last_status = runner._session_repository.statuses[-1]
    assert last_status[0] == "sess-test"
    assert last_status[1] in ("CANCELLED", "cancelled") or getattr(
        last_status[1], "value", ""
    ) == "cancelled"
    finals = [e for e in emitted if isinstance(e, MessageEvent) and e.is_final]
    assert finals, "overtime notice must be emitted as a final message"
    assert "batas waktu" in finals[0].message


@pytest.mark.asyncio
async def test_user_stop_still_propagates_cancel(monkeypatch):
    """A cancellation of run() itself (STOP button path) is forwarded to the
    impl and re-raised when the impl has no handler — the old contract."""
    runner = _runner_skeleton()

    async def _hung_impl(task):
        await asyncio.sleep(999)

    monkeypatch.setattr(runner, "_run_impl", _hung_impl)
    monkeypatch.setattr(
        "app.domain.services.agent_task_runner.get_settings",
        lambda: _FakeSettings(task_timeout_ms=60_000),
    )

    task = asyncio.ensure_future(runner.run(_FakeTask()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_no_watchdog_when_guard_disabled(monkeypatch):
    """manus_task_timeout_ms=0 (operator opt-out) runs the impl inline."""
    runner = _runner_skeleton()
    ran = []

    async def _impl(task):
        ran.append(True)

    monkeypatch.setattr(runner, "_run_impl", _impl)
    monkeypatch.setattr(
        "app.domain.services.agent_task_runner.get_settings",
        lambda: _FakeSettings(task_timeout_ms=0),
    )
    await runner.run(_FakeTask())
    assert ran == [True]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Gate tool ceiling
#─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_timeout_returns_honest_failure(monkeypatch):
    """A tool that never returns becomes a TIMEOUT failure payload for the
    model — the loop survives and can pick a different approach."""
    gate = ManusGate.__new__(ManusGate)

    async def _hung():
        await asyncio.sleep(30)

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _FakeSettings(task_timeout_ms=0, tool_timeout_seconds=0.2),
    )
    payload = await gate._bounded_tool_exec("browser_navigate", _hung)
    assert payload["success"] is False
    assert payload["error"]["code"] == "TIMEOUT"
    assert "batas waktu" in payload["error"]["message"]
    assert payload.get("retryable") is True  # TIMEOUT is in RETRYABLE_CODES


@pytest.mark.asyncio
async def test_gate_ceiling_disabled_passes_through(monkeypatch):
    gate = ManusGate.__new__(ManusGate)

    async def _fast():
        return {"success": True, "tool": "x", "data": {"ok": 1}, "error": None}

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _FakeSettings(task_timeout_ms=0, tool_timeout_seconds=0),
    )
    payload = await gate._bounded_tool_exec("any_tool", _fast)
    assert payload["success"] is True


@pytest.mark.asyncio
async def test_gate_ceiling_bounds_retry_budget_too(monkeypatch):
    """The ceiling covers executor retries + backoff: a retryable failure
    whose attempts+backoff outlive the budget is cut off by the ceiling and
    surfaces as TIMEOUT for the model (never an eternal await)."""
    from app.domain.services.manus_registry.retry import run_with_retry
    from app.domain.services.manus_registry.errors import failure_payload

    gate = ManusGate.__new__(ManusGate)
    calls = []

    async def _slow_flaky():
        calls.append(1)
        await asyncio.sleep(0.6)  # each attempt burns the budget
        return failure_payload("some_tool", "TRANSIENT_NETWORK", "connection reset")

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _FakeSettings(task_timeout_ms=0, tool_timeout_seconds=1.0),
    )
    payload = await gate._bounded_tool_exec(
        "some_tool", lambda: run_with_retry(_slow_flaky, tool_name="some_tool")
    )
    assert payload["success"] is False
    assert len(calls) >= 1  # the first attempt ran
    assert payload["error"]["code"] in {"TIMEOUT", "TRANSIENT_NETWORK"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Browser hygiene
#─────────────────────────────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        import json as _json
        return _json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_close_stale_tabs_keeps_blank_pages(monkeypatch):
    """Only non-blank PAGE targets are closed; browser_ui targets and blank
    pages stay. The wrapper never raises."""
    browser = bub.BrowserUseBrowser("http://127.0.0.1:8222")
    targets = [
        {"id": "1", "type": "page", "url": "https://example.com/"},
        {"id": "2", "type": "page", "url": "http://127.0.0.1:34543/form"},
        {"id": "3", "type": "page", "url": "about:blank"},
        {"id": "4", "type": "browser_ui", "url": "chrome://omnibox-popup.top-chrome/"},
    ]
    closed, listed = [], []

    def _fake_urlopen(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url if hasattr(req, "full_url") else req
        url = str(url)
        if "/json/list" in url:
            listed.append(url)
            return _FakeResp(targets)
        if "/json/close/" in url:
            closed.append(url)
            return _FakeResp({"success": True})
        raise AssertionError(f"unexpected fetch {url}")

    monkeypatch.setattr(bub.urllib.request, "urlopen", _fake_urlopen)
    n = await browser._close_stale_tabs()
    assert n == 2
    assert all("/json/close/2" in c or "/json/close/1" in c for c in closed)
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_close_stale_tabs_swallows_cdp_failure(monkeypatch):
    """CDP down → cleanup is skipped silently (hygiene must never block)."""
    browser = bub.BrowserUseBrowser("http://127.0.0.1:8222")

    def _dead(req, timeout=0):
        raise ConnectionError("refused")

    monkeypatch.setattr(bub.urllib.request, "urlopen", _dead)
    assert await browser._close_stale_tabs() == 0


@pytest.mark.asyncio
async def test_wedged_chrome_triggers_heal_then_recovers(monkeypatch):
    """browser_use event-handler timeouts (wedged Chrome) invoke the heal
    hook — plain retries can never fix a wedged browser."""
    browser = bub.BrowserUseBrowser("http://127.0.0.1:8222")
    heals = []

    async def _heal():
        heals.append(1)

    browser._heal_hook = _heal

    class _FakeSession:
        _attempts = {"n": 0}

        def __init__(self, **kwargs):
            _FakeSession._attempts["n"] += 1
            self.n = _FakeSession._attempts["n"]

        async def start(self):
            if self.n == 1:
                raise RuntimeError(
                    "Event handler BrowserSession.on_BrowserStartEvent "
                    "timed out after 30.0s and interrupted any processing"
                )
            return None  # recovered after heal

        async def stop(self):
            return None

    async def _no_close():
        return 0

    async def _no_fit(*a, **k):
        return None

    monkeypatch.setattr(bub, "BrowserSession", _FakeSession)
    monkeypatch.setattr(browser, "_close_stale_tabs", _no_close)
    monkeypatch.setattr(bub, "fit_window_browser_use", _no_fit)
    monkeypatch.setattr(bub, "clear_viewport_overrides_browser_use", _no_fit)
    # shrink the real backoff sleeps so the test stays fast
    real_sleep = asyncio.sleep

    async def _fast_sleep(delay, *a, **k):
        await real_sleep(min(delay, 0.01))

    monkeypatch.setattr(bub.asyncio, "sleep", _fast_sleep)

    session = await asyncio.wait_for(browser._ensure_session(), timeout=15)
    assert session is not None
    assert len(heals) == 1
    assert browser._session is session
