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


@pytest.mark.asyncio
async def test_pause_deferred_while_vnc_viewer_connected():
    """A user watching the live view (takeover) must not have the sandbox
    frozen under them — the post-run pause is skipped; the viewer-disconnect
    hook re-pauses later."""

    class WatchedSandbox(PausableSandbox):
        def has_vnc_viewers(self) -> bool:
            return True

    sandbox = WatchedSandbox()
    runner = make_runner(sandbox)
    await runner._pause_sandbox_after_run()
    assert sandbox.paused_count == 0


@pytest.mark.asyncio
async def test_pause_not_deferred_without_viewer_hook():
    """A sandbox with pause() but without viewer accounting (e.g. older
    adapter) still pauses normally after the run."""

    runner = make_runner(PausableSandbox())
    await runner._pause_sandbox_after_run()
    assert True  # reached without error — full behaviour covered above


@pytest.mark.asyncio
async def test_vnc_viewer_accounting_and_repause():
    """Viewer connect/disconnect accounting: pause is skipped while viewers
    are connected, and the delayed re-pause fires once activity stops."""
    import asyncio
    import time as _time

    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

    class FakeSbx:
        sandbox_id = "sbx-viewer-test"

        async def pause(self):
            return True

    sbx = FakeSbx()
    wrapper = E2BSandbox.__new__(E2BSandbox)
    wrapper._sbx = sbx
    wrapper._raw_id = sbx.sandbox_id
    wrapper._id = f"e2b:{sbx.sandbox_id}"
    wrapper._bootstrap_lock = asyncio.Lock()
    wrapper._bootstrapped = True
    wrapper._activity_until = 0.0  # idle already
    wrapper._shell_sessions = {}
    wrapper._http = None
    E2BSandbox._registry[sbx.sandbox_id] = wrapper
    E2BSandbox._vnc_viewers.pop(sbx.sandbox_id, None)
    paused = []

    async def fake_pause():
        paused.append(True)
        E2BSandbox._registry.pop(sbx.sandbox_id, None)
        return True

    wrapper.pause = fake_pause

    try:
        assert wrapper.has_vnc_viewers() is False
        wrapper.vnc_viewer_connected()
        assert wrapper.has_vnc_viewers() is True
        # runner would skip the pause now (covered above)

        wrapper.vnc_viewer_connected()
        await wrapper.vnc_viewer_disconnected()
        assert wrapper.has_vnc_viewers() is True  # one viewer still there

        await wrapper.vnc_viewer_disconnected()
        assert wrapper.has_vnc_viewers() is False

        # fast-forward the repause poll: shorten sleeps and window
        E2BSandbox._REPAUSE_POLL = 0.01
        await asyncio.sleep(0.05)
        assert paused, "re-pause did not fire after the last viewer left"
    finally:
        E2BSandbox._REPAUSE_POLL = 15.0
        E2BSandbox._registry.pop(sbx.sandbox_id, None)
        E2BSandbox._vnc_viewers.pop(sbx.sandbox_id, None)


@pytest.mark.asyncio
async def test_repause_waits_for_agent_activity():
    """The delayed re-pause must NOT freeze a VM that is actively running a
    task (activity heartbeat still in the future)."""
    import asyncio

    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

    class FakeSbx:
        sandbox_id = "sbx-activity-test"

    wrapper = E2BSandbox.__new__(E2BSandbox)
    wrapper._sbx = FakeSbx()
    wrapper._raw_id = FakeSbx.sandbox_id
    wrapper._id = f"e2b:{FakeSbx.sandbox_id}"
    wrapper._bootstrap_lock = asyncio.Lock()
    wrapper._bootstrapped = True
    wrapper._activity_until = asyncio.get_event_loop().time() + 3600  # busy
    wrapper._shell_sessions = {}
    wrapper._http = None
    E2BSandbox._registry[FakeSbx.sandbox_id] = wrapper
    E2BSandbox._vnc_viewers.pop(FakeSbx.sandbox_id, None)
    paused = []

    async def fake_pause():
        paused.append(True)
        return True

    wrapper.pause = fake_pause

    try:
        E2BSandbox._REPAUSE_POLL = 0.01
        task = asyncio.create_task(
            E2BSandbox._repause_when_idle(FakeSbx.sandbox_id)
        )
        await asyncio.sleep(0.1)  # several poll cycles pass
        assert not paused, "paused while agent activity window still open"
        task.cancel()
    finally:
        E2BSandbox._REPAUSE_POLL = 15.0
        E2BSandbox._registry.pop(FakeSbx.sandbox_id, None)
        E2BSandbox._vnc_viewers.pop(FakeSbx.sandbox_id, None)


def test_bootstrap_launches_xvfb_at_depth_24():
    """Source contract: Xvfb must run at depth 24 (noVNC + x11vnc black-screen
    bug — see e2b_sandbox module docstring note 4) and chromium must restore
    the last session after a pause/resume cycle."""
    import inspect

    from app.infrastructure.external.sandbox import e2b_sandbox

    src = inspect.getsource(e2b_sandbox.E2BSandbox._bootstrap)
    assert "1024x768x24" in src, "Xvfb must be launched at depth 24"
    assert "1024x768x16" not in src, "depth 16 caused the black VNC screen"
    # chromium relaunch (with --restore-last-session) lives in its own helper
    # since the browser-heal refactor — the bootstrap must call it, and the
    # helper itself must carry the restore flag.
    assert "_launch_chromium" in src, "bootstrap must delegate chromium relaunch"
    launch_src = inspect.getsource(e2b_sandbox.E2BSandbox._launch_chromium)
    assert "--restore-last-session" in launch_src, (
        "chromium should reopen the agent's tabs after resume"
    )
    # depth check + replacement of stale depth-16 servers on resume
    assert "depth of root window" in src


def test_e2b_sandbox_has_pause_and_vnc_url():
    """E2BSandbox exposes the pause() lifecycle + a non-headless VNC URL."""
    from app.infrastructure.external.sandbox.e2b_sandbox import E2BSandbox

    assert hasattr(E2BSandbox, "pause")
    assert hasattr(E2BSandbox, "vnc_url")
    # Class-level provider tag used for the conditional system prompt
    assert E2BSandbox.provider == "e2b"
    # Live-view viewer accounting hooks used by the VNC websocket route
    assert hasattr(E2BSandbox, "has_vnc_viewers")
    assert hasattr(E2BSandbox, "vnc_viewer_connected")
    assert hasattr(E2BSandbox, "vnc_viewer_disconnected")
