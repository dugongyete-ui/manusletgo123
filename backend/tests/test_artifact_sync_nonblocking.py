"""Regression tests: step artifact sync must NEVER block the event pump.

Live incident (session 5a60e5b5, 2026-08-30): the agent's step-1 shell ran
`npm install`, creating ~400 node_modules files. At StepEvent(COMPLETED) the
task runner uploaded every one of them to GridFS one-by-one (2m46s) BEFORE
yielding the event — so the user watched the agent browser-testing while the
plan panel stayed frozen at 0/5 for three minutes, and every later event
(plan updates, next step) piled up behind the uploads.

Two-layer fix under test:
1. `_scan_user_home_files` filters dependency/runtime caches
   (node_modules, __pycache__, venv, …) — they are never user deliverables.
2. The step-completion sync runs as a chained BACKGROUND task: events flow
   immediately; the final summary awaits the background sync before its own
   sweep so no deliverable is lost; consecutive syncs are serialized.
"""

import asyncio
import time

import pytest

from app.domain.models.event import MessageEvent, StepEvent, StepStatus
from app.domain.models.file import FileInfo
from app.domain.models.message import Message
from app.domain.models.plan import Step
from app.domain.services.agent_task_runner import AgentTaskRunner


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _listing_result(entries):
    """Duck-typed ToolResult for the sandbox file_list call."""
    return type("R", (), {"success": True, "data": {"entries": entries}})()


class _FakeSandbox:
    """Sandbox double: user_home + canned directory listings."""

    def __init__(self, listings=None):
        self.user_home = "/home/user"
        self._listings = listings or {}

    async def file_list(self, path):
        return self._listings.get(path)


def _runner_skeleton():
    """AgentTaskRunner without running __init__ (heavy deps)."""
    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._agent_id = "test-agent"
    runner._session_id = "sess-test"
    runner._user_id = "test-user"
    return runner


# ─────────────────────────────────────────────────────────────────────────────
# 1. Junk filter — dependency caches are never artifact candidates
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_skips_dependency_caches():
    """node_modules / __pycache__ / venv subtrees are excluded from the scan;
    normal files (even inside real project dirs) are still found."""
    sandbox = _FakeSandbox({
        "/home/user": _listing_result([
            {"name": "project", "type": "dir", "size": 0},
            {"name": "node_modules", "type": "dir", "size": 0},
            {"name": "__pycache__", "type": "dir", "size": 0},
            {"name": "venv", "type": "dir", "size": 0},
            {"name": ".git", "type": "dir", "size": 0},   # dot-dir: already skipped
            {"name": "readme.md", "type": "file", "size": 12},
        ]),
        "/home/user/project": _listing_result([
            {"name": "index.html", "type": "file", "size": 700},
            {"name": "node_modules", "type": "dir", "size": 0},  # nested junk too
            {"name": "app.js", "type": "file", "size": 100},
        ]),
        # These junk listings must never even be walked:
        "/home/user/node_modules": _listing_result([
            {"name": "leftpad", "type": "dir", "size": 0},
        ]),
        "/home/user/project/node_modules": _listing_result([
            {"name": "express", "type": "dir", "size": 0},
        ]),
    })
    runner = _runner_skeleton()
    runner._sandbox = sandbox

    found = await runner._scan_user_home_files()

    assert found == {
        "/home/user/readme.md": 12,
        "/home/user/project/index.html": 700,
        "/home/user/project/app.js": 100,
    }


@pytest.mark.asyncio
async def test_scan_keeps_normal_project_files():
    """Sanity: a real deliverable tree (src/, dist/) is fully captured."""
    sandbox = _FakeSandbox({
        "/home/user": _listing_result([
            {"name": "site", "type": "dir", "size": 0},
        ]),
        "/home/user/site": _listing_result([
            {"name": "dist", "type": "dir", "size": 0},
            {"name": "package.json", "type": "file", "size": 300},
        ]),
        "/home/user/site/dist": _listing_result([
            {"name": "index.html", "type": "file", "size": 900},
        ]),
    })
    runner = _runner_skeleton()
    runner._sandbox = sandbox

    found = await runner._scan_user_home_files()
    assert found == {
        "/home/user/site/package.json": 300,
        "/home/user/site/dist/index.html": 900,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Non-blocking step sync — events flow while uploads run in background
# ─────────────────────────────────────────────────────────────────────────────

class _SyncTracker:
    def __init__(self, delay=0.25):
        self.delay = delay
        self.calls = []          # (start, end)
        self.overlaps = 0

    async def sync_run_artifacts(self, baseline, files_written, pending):
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        self.calls.append((start, time.monotonic()))
        # Serialize check: no call may start before the previous one ended.
        if len(self.calls) >= 2 and self.calls[-2][1] > start:
            self.overlaps += 1


def _make_flow_runner(tracker: _SyncTracker, step_events, final_after=0.05):
    """Runner skeleton wired for _run_flow with a fake flow + slow sync."""
    runner = _runner_skeleton()
    runner._sandbox = _FakeSandbox()          # empty home baseline

    class _Flow:
        async def run(self, message):
            for ev in step_events:
                yield ev
            await asyncio.sleep(final_after)  # let the bg sync get going
            yield MessageEvent(role="assistant", message="selesai", is_final=True)

    runner._flow = _Flow()

    async def _no_tool_event(event):
        return None

    async def _sync_attachment(path, *, add_to_session=True):
        return FileInfo(file_id="f1", filename=path.split("/")[-1],
                        file_path=path, size=10)

    runner._handle_tool_event = _no_tool_event
    runner._sync_file_to_storage = _sync_attachment
    runner._sync_run_artifacts = tracker.sync_run_artifacts

    async def _noop_msg_attachments(event):
        return None

    runner._sync_message_attachments_to_storage = _noop_msg_attachments
    return runner


@pytest.mark.asyncio
async def test_step_event_not_blocked_by_slow_sync():
    """THE incident: StepEvent(COMPLETED) must reach the consumer immediately
    even while the artifact sync takes its time in the background."""
    tracker = _SyncTracker(delay=0.3)
    step = Step(id="1", description="buat", status=None or __import__(
        "app.domain.models.plan", fromlist=["ExecutionStatus"]).ExecutionStatus.COMPLETED)
    step.success = True
    step.attachments = ["/home/user/out.txt"]
    events_in = [StepEvent(step=step, status=StepStatus.COMPLETED)]
    runner = _make_flow_runner(tracker, events_in)

    arrivals = {}
    async for ev in runner._run_flow(Message(message="test")):
        arrivals[type(ev).__name__] = time.monotonic()

    # The step event arrived WELL BEFORE the 0.3s background sync finished…
    step_arrival = arrivals["StepEvent"]
    first_sync_end = tracker.calls[0][1]
    assert step_arrival < first_sync_end - 0.1, (
        f"StepEvent blocked by artifact sync: arrived {step_arrival:.3f}, "
        f"sync finished {first_sync_end:.3f}"
    )
    # …and the final message waited for the sync (nothing lost), carrying the
    # step attachment with it.
    final_arrival = arrivals["MessageEvent"]
    assert final_arrival >= first_sync_end
    # Two sweeps happened: background (step) + final (summary).
    assert len(tracker.calls) == 2


@pytest.mark.asyncio
async def test_step_attachment_survives_to_final_summary():
    """Files synced by the background step sync must land on the final summary
    message — non-blocking must not mean non-delivery."""
    tracker = _SyncTracker(delay=0.05)
    from app.domain.models.plan import ExecutionStatus
    step = Step(id="1", description="buat", status=ExecutionStatus.COMPLETED)
    step.success = True
    step.attachments = ["/home/user/laporan.txt"]
    runner = _make_flow_runner(tracker, [StepEvent(step=step, status=StepStatus.COMPLETED)])

    final_event = None
    async for ev in runner._run_flow(Message(message="test")):
        if isinstance(ev, MessageEvent) and ev.is_final:
            final_event = ev

    assert final_event is not None
    paths = [f.file_path for f in (final_event.attachments or [])]
    assert "/home/user/laporan.txt" in paths


@pytest.mark.asyncio
async def test_consecutive_step_syncs_are_serialized():
    """Two steps completing back-to-back schedule two background syncs — they
    must run one-after-another (never overlapping scans on the same paths)."""
    from app.domain.models.plan import ExecutionStatus
    tracker = _SyncTracker(delay=0.2)
    steps = []
    for i in (1, 2):
        s = Step(id=str(i), description=f"step {i}", status=ExecutionStatus.COMPLETED)
        s.success = True
        steps.append(StepEvent(step=s, status=StepStatus.COMPLETED))

    runner = _make_flow_runner(tracker, steps)
    arrivals = []
    async for ev in runner._run_flow(Message(message="test")):
        arrivals.append((type(ev).__name__, time.monotonic()))

    # Both step events flowed immediately (before the first 0.2s sync ended).
    first_sync_end = tracker.calls[0][1]
    step_arrivals = [t for name, t in arrivals if name == "StepEvent"]
    assert len(step_arrivals) == 2
    assert all(t < first_sync_end - 0.05 for t in step_arrivals)
    # Background sync + final sweep = 3 calls, none overlapping.
    assert len(tracker.calls) == 3
    assert tracker.overlaps == 0


@pytest.mark.asyncio
async def test_background_sync_failure_never_breaks_the_flow():
    """A crashing BACKGROUND sync logs a warning — events and the final
    summary still deliver normally. (Only the first — background — call
    raises; the final sweep runs on the healthy path.)"""
    class _BoomFirstTracker(_SyncTracker):
        def __init__(self):
            super().__init__(delay=0)
            self._first = True

        async def sync_run_artifacts(self, baseline, files_written, pending):
            if self._first:
                self._first = False
                raise RuntimeError("GridFS unavailable")
            await super().sync_run_artifacts(baseline, files_written, pending)

    tracker = _BoomFirstTracker()
    from app.domain.models.plan import ExecutionStatus
    step = Step(id="1", description="x", status=ExecutionStatus.COMPLETED)
    step.success = True
    runner = _make_flow_runner(tracker, [StepEvent(step=step, status=StepStatus.COMPLETED)])

    got = [type(ev).__name__ async for ev in runner._run_flow(Message(message="test"))]
    assert "StepEvent" in got and "MessageEvent" in got
