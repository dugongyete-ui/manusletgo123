"""Unit tests for the patient rate-limit retry schedule in BaseAgent.

Session c397e25f ground truth: a 429 from the provider killed a 6-minute-old
task instantly. The fix gives limit errors an EXTENDED attempt budget with
capped back-off (~11 min patience) plus primary<->fallback provider rotation
and a user-facing waiting notice. These tests pin all three behaviours down
without touching a real provider.
"""

import pytest

from app.domain.services.agents.base import BaseAgent


class _Chunk:
    def __init__(self, text):
        self.content = text


class _FlakyModel:
    """Mock chat model whose astream() raises the first `failures` calls."""

    def __init__(self, failures: int, exc: Exception):
        self.failures = failures
        self.exc = exc
        self.calls = 0

    async def astream(self, messages):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        yield _Chunk("hello")
        yield _Chunk(" world")


def make_agent(model=None, notice=None) -> BaseAgent:
    """BaseAgent skeleton without touching settings/model providers."""
    agent = BaseAgent.__new__(BaseAgent)
    agent._model = model or _FlakyModel(0, Exception("unused"))
    agent._primary_model = agent._model
    agent._primary_auth_failed = False
    agent._using_fallback = False
    agent.max_retries = 6
    agent.retry_interval = 5.0
    agent.rate_limit_notice = notice
    agent._last_rate_limit_notice_ts = 0.0
    return agent


# ── The schedule itself ──────────────────────────────────────────────────────

def test_limit_retry_wait_schedule_is_capped_and_patient():
    """Waits grow exponentially but cap at 90s; the whole budget spans ~11 min."""
    agent = make_agent()
    waits = [agent._limit_retry_wait(a) for a in range(agent._rate_limit_budget() - 1)]
    assert waits[:5] == [5.0, 10.0, 20.0, 40.0, 80.0]
    assert all(w == 90.0 for w in waits[5:])
    total = sum(waits)
    # ~11 minutes of patience (695s) — never again an instant 429 death.
    assert 10 * 60 <= total <= 13 * 60


def test_rate_limit_budget_extends_the_normal_retry_budget():
    agent = make_agent()
    assert agent._rate_limit_budget() == agent.max_retries + agent._RATE_LIMIT_EXTRA_ATTEMPTS


# ── The streaming retry loop ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_recovers_after_transient_rate_limits(monkeypatch):
    """A few 429s then success: the stream waits on the capped schedule and
    returns the full text — the task must NOT die."""
    model = _FlakyModel(failures=3, exc=Exception("Error code: 429 - rate limit exceeded"))
    agent = make_agent(model=model)
    sleeps: list = []
    switches: list = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        "app.domain.services.agents.base.asyncio.sleep", fake_sleep
    )
    monkeypatch.setattr(
        agent, "_rotate_provider_for_limit", lambda reason: switches.append(reason) or True
    )

    text = await agent.astream_text_with_fallback([{"role": "user", "content": "hi"}])

    assert text == "hello world"
    assert model.calls == 4                      # 3 failures + 1 success
    assert sleeps == [5.0, 10.0, 20.0]           # capped exponential schedule
    assert len(switches) == 3                    # rotated provider on every 429


@pytest.mark.asyncio
async def test_stream_gives_up_only_after_full_patient_budget(monkeypatch):
    """Persistent 429s raise only after max_retries + EXTRA attempts — and the
    waits in between span the full ~11 minute schedule."""
    model = _FlakyModel(failures=10**6, exc=Exception("Error code: 429 - rate limit exceeded"))
    agent = make_agent(model=model)

    sleeps: list = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        "app.domain.services.agents.base.asyncio.sleep", fake_sleep
    )
    monkeypatch.setattr(agent, "_rotate_provider_for_limit", lambda reason: False)

    with pytest.raises(Exception, match="429"):
        await agent.astream_text_with_fallback([{"role": "user", "content": "hi"}])

    budget = agent._rate_limit_budget()
    assert model.calls == budget
    assert len(sleeps) == budget - 1
    assert sum(sleeps) >= 10 * 60                # ~11 minutes of patience first


@pytest.mark.asyncio
async def test_stream_non_limit_error_uses_short_budget(monkeypatch):
    """Ordinary transient errors (5xx) keep the SHORT retry budget."""
    import httpx
    import openai

    resp = httpx.Response(503, request=httpx.Request("POST", "http://test"))
    exc = openai.InternalServerError("503 service unavailable", response=resp, body=None)
    model = _FlakyModel(failures=10**6, exc=exc)
    agent = make_agent(model=model)
    sleeps: list = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        "app.domain.services.agents.base.asyncio.sleep", fake_sleep
    )

    with pytest.raises(openai.InternalServerError):
        await agent.astream_text_with_fallback([{"role": "user", "content": "hi"}])

    assert model.calls == agent.max_retries      # NOT the extended limit budget
    assert len(sleeps) == agent.max_retries - 1


# ── Provider rotation ────────────────────────────────────────────────────────

def test_rotate_provider_alternates_primary_and_fallback(monkeypatch):
    """Consecutive limit errors alternate primary -> fallback -> primary so
    each provider gets its window to clear."""
    agent = make_agent()
    agent._using_fallback = False
    calls: list = []

    monkeypatch.setattr(
        agent, "_switch_to_fallback_model",
        lambda reason: calls.append("to_fallback") or (setattr(agent, "_using_fallback", True) or True),
    )
    monkeypatch.setattr(
        agent, "_switch_to_primary_model",
        lambda reason: calls.append("to_primary") or (setattr(agent, "_using_fallback", False) or True),
    )

    assert agent._rotate_provider_for_limit("429") is True
    assert agent._rotate_provider_for_limit("429") is True
    assert agent._rotate_provider_for_limit("429") is True
    assert calls == ["to_fallback", "to_primary", "to_fallback"]


def test_rotate_never_returns_to_auth_failed_primary():
    agent = make_agent()
    agent._using_fallback = True
    agent._primary_auth_failed = True
    assert agent._rotate_provider_for_limit("429") is False


# ── The user-facing waiting notice ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_notice_fires_for_long_waits_and_is_throttled(monkeypatch):
    """Waits >= 20s announce themselves; the next notice within 180s is
    suppressed so the chat is not spammed while retrying."""
    clock = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    notices: list = []

    async def cb(text):
        notices.append(text)

    agent = make_agent(notice=cb)

    await agent._notify_rate_limit_wait(5.0)     # too short — silent
    assert notices == []

    await agent._notify_rate_limit_wait(20.0)    # long enough — announced
    assert len(notices) == 1

    clock["t"] += 10.0
    await agent._notify_rate_limit_wait(90.0)    # throttled (< 180s later)
    assert len(notices) == 1

    clock["t"] += 200.0
    await agent._notify_rate_limit_wait(90.0)    # throttle window passed
    assert len(notices) == 2
    assert "429" in notices[-1]
    assert "menunggu" in notices[-1]


@pytest.mark.asyncio
async def test_notice_failure_never_breaks_the_retry_loop():
    """A broken callback must not raise into the retry loop."""
    agent = make_agent()

    def broken_cb(text):
        raise RuntimeError("boom")

    agent.rate_limit_notice = broken_cb
    await agent._notify_rate_limit_wait(60.0)    # must not raise
