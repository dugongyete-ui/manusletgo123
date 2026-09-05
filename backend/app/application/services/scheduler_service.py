"""Recurring scheduled agent runs (Manus scheduleTask equivalent).

A single background loop per process wakes every POLL_SECONDS, finds due
scheduled tasks, and feeds each task's prompt into its session through the
normal chat pathway — exactly as if the user pressed send. The run happens
server-side (no SSE listener needed): events are persisted by the task
runner, the unread counter bumps, and the user finds the fresh result when
they next open the session.

Failure isolation: one bad run (provider outage, sandbox error) never
stops the loop or the other tasks — the next_run_at still advances so a
transient failure does not hammer the provider every 30 seconds.
"""

import asyncio
import logging
from datetime import datetime, UTC, timedelta

logger = logging.getLogger(__name__)

POLL_SECONDS = 30.0


class SchedulerService:
    def __init__(self, agent_service, scheduled_task_repository):
        self._agent_service = agent_service
        self._repository = scheduled_task_repository
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        # In-flight task ids — a run that takes longer than one poll window
        # must never be double-started.
        self._running: set[str] = set()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="scheduler-service")
        logger.info("Scheduler service started (poll every %.0fs)", POLL_SECONDS)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("scheduler stop cleanup", exc_info=True)
        self._task = None
        logger.info("Scheduler service stopped")

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed — retrying next cycle")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        now = datetime.now(UTC)
        due = await self._repository.find_due(now)
        for scheduled in due:
            if scheduled.id in self._running:
                continue
            self._running.add(scheduled.id)
            asyncio.create_task(self._run_scheduled(scheduled))

    async def _run_scheduled(self, scheduled) -> None:
        """Run one due ScheduledTask, then advance its schedule.

        The schedule ALWAYS advances (even on failure) — a transient
        provider error must not turn into a retry-every-30s hammer.
        """
        try:
            logger.info(
                "Scheduled run: task %s → session %s (%s)",
                scheduled.id, scheduled.session_id, scheduled.prompt[:80],
            )
            # Drive the chat generator to completion. Events are persisted by
            # the task runner; discarding them here is fine (no live listener).
            async for _event in self._agent_service.chat(
                session_id=scheduled.session_id,
                user_id=scheduled.user_id,
                message=scheduled.prompt,
            ):
                pass
            logger.info("Scheduled run completed: task %s", scheduled.id)
        except Exception:
            logger.exception("Scheduled run failed: task %s", scheduled.id)
        finally:
            now = datetime.now(UTC)
            next_run = now + timedelta(minutes=max(5, scheduled.interval_minutes))
            try:
                await self._repository.update_run(scheduled.id, now, next_run)
            except Exception:
                logger.exception(
                    "Failed to advance next_run_at for task %s", scheduled.id
                )
            self._running.discard(scheduled.id)
