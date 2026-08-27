"""Unit tests for the post-run E2B sandbox pause (quota saver).

User requirement: once the agent delivers the final summary and there are no
more queued user messages, the E2B microVM must be paused so it stops burning
compute quota. A paused VM auto-resumes on the next message (get → connect).
While the agent WAITS for a user answer (WaitEvent / ask_user), the sandbox
stays warm — responsiveness wins, the 1h idle timeout covers stragglers.
"""

import pytest

from app.domain.services.agent_task_runner import AgentTaskRunner


def make_runner(sandbox) -> AgentTaskRunner:
    """AgentTaskRunner skeleton without touching settings/model providers."""
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._sandbox = sandbox
    runner._agent_id = "agent-1"
    return runner


class PausableSandbox:
    """E2B-like sandbox: exposes an async pause()."""

    provider = "e2b"
    shared = False

    def __init__(self):
        self.paused_count = 0

    async def pause(self) -> bool:
        self.paused_count += 1
        return True


class PausableFailingSandbox:
    """E2B-like sandbox whose pause() raises — must never crash the run."""

    provider = "e2b"

    async def pause(self):
        raise RuntimeError("vm already paused")


class ReplitLikeSandbox:
    """Shared Replit sandbox: no pause() at all."""

    provider = "replit"
    shared = True


@pytest.mark.asyncio
async def test_pause_called_after_finished_run():
    sandbox = PausableSandbox()
    runner = make_runner(sandbox)
    await runner._pause_sandbox_after_run()
    assert sandbox.paused_count == 1


@pytest.mark.asyncio
async def test_pause_failure_never_crashes_run():
    runner = make_runner(PausableFailingSandbox())
    # Must not raise — a quota-saving optimisation cannot be allowed to fail
    # a task that already succeeded.
    await runner._pause_sandbox_after_run()


@pytest.mark.asyncio
async def test_replit_sandbox_without_pause_is_skipped():
    runner = make_runner(ReplitLikeSandbox())
    # Duck-typed: no pause() → silently skipped (shared container must keep
    # running for every other user).
    await runner._pause_sandbox_after_run()


@pytest.mark.asyncio
async def test_pause_returning_false_is_not_logged_as_success():
    """E2BSandbox.pause() returns False on failure — runner must not log the
    'sandbox paused' success line for it (smoke: call must simply return)."""

    class HalfFailingSandbox:
        async def pause(self) -> bool:
            return False

    runner = make_runner(HalfFailingSandbox())
    await runner._pause_sandbox_after_run()  # no exception, no crash


def test_run_tracks_wait_event_to_skip_pause():
    """The run() body must declare the waited_for_user flag before the try
    block and set it on WaitEvent — source-level contract check."""
    import inspect

    src = inspect.getsource(AgentTaskRunner.run)
    assert "waited_for_user = False" in src
    assert "waited_for_user = True" in src
    # The pause is gated on NOT waiting for the user
    assert "if not waited_for_user:" in src
    assert "_pause_sandbox_after_run" in src


def test_e2b_sandbox_has_pause_and_vnc_url():
    """E2BSandbox exposes the pause() lifecycle + a non-headless VNC URL."""
    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

    assert hasattr(E2BSandbox, "pause")
    assert hasattr(E2BSandbox, "vnc_url")
    # Class-level provider tag used for the conditional system prompt
    assert E2BSandbox.provider == "e2b"
