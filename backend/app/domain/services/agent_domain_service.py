from typing import Optional, AsyncGenerator, List
import asyncio
import logging
from datetime import datetime, timezone
from app.domain.models.session import Session, SessionStatus
from app.domain.external.sandbox import Sandbox
from app.domain.external.search import SearchEngine
from app.domain.models.event import BaseEvent, ErrorEvent, DoneEvent, MessageEvent, WaitEvent, AgentEvent
from pydantic import TypeAdapter
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.session_repository import SessionRepository
from app.domain.services.agent_task_runner import AgentTaskRunner
from app.domain.external.task import Task
from typing import Type
from app.domain.external.file import FileStorage
from app.domain.models.file import FileInfo
from app.domain.repositories.mcp_repository import MCPRepository
from app.infrastructure.external.sandbox.user_sandbox import UserScopedSandbox
from app.domain.external.lazy_browser import LazyBrowser
from app.domain.external.lazy_sandbox import LazySandbox

# Setup logging
logger = logging.getLogger(__name__)

class AgentDomainService:
    """
    Agent domain service, responsible for coordinating the work of planning agent and execution agent
    """

    # Per-session asyncio locks prevent concurrent sandbox creation for the same
    # session (warmup task vs first-chat _create_task race condition — M1).
    _session_locks: dict[str, asyncio.Lock] = {}

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the asyncio.Lock for a given session."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def __init__(
        self,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        sandbox_cls: Type[Sandbox],
        task_cls: Type[Task],
        file_storage: FileStorage,
        mcp_repository: MCPRepository,
        search_engine: Optional[SearchEngine] = None,
        project_repository=None,
    ):
        self._repository = agent_repository
        self._session_repository = session_repository
        self._sandbox_cls = sandbox_cls
        self._search_engine = search_engine
        self._task_cls = task_cls
        self._file_storage = file_storage
        self._mcp_repository = mcp_repository
        self._project_repository = project_repository
        logger.info("AgentDomainService initialization completed")
            
    async def shutdown(self) -> None:
        """Clean up all Agent's resources"""
        logger.info("Starting to close all Agents")
        await self._task_cls.destroy()
        logger.info("All agents closed successfully")

    async def warmup_sandbox(self, session_id: str) -> None:
        """Warm up the sandbox eagerly in the background right after
        session creation so the first chat message is not blocked by the
        sandbox readiness check.  Uses a per-session lock to avoid racing
        with _create_task.

        The lock is held ONLY for the sandbox allocation (create + save) —
        the slow tail (VM boot, user-home setup, package pre-install, the
        quota-saving pause) runs WITHOUT the lock so an incoming chat can
        proceed with the allocated sandbox immediately instead of queueing
        behind the whole warm-up."""
        async with self._get_session_lock(session_id):
            try:
                session = await self._session_repository.find_by_id(session_id)
                if not session:
                    logger.warning("[Warmup] Session %s not found — skipping", session_id)
                    return
                if session.sandbox_id:
                    logger.info("[Warmup] Session %s already has sandbox %s — skipping", session_id, session.sandbox_id)
                    return
                sandbox = await self._sandbox_cls.create()
                session.sandbox_id = sandbox.id
                await self._session_repository.save(session)
            except Exception as e:
                logger.warning("[Warmup] Background sandbox warmup failed for session %s: %s", session_id, e)
                return
            # Lock released here — chat()/_create_task can use this sandbox now.

        try:
            logger.info("[Warmup] Sandbox %s created for session %s — running ensure_sandbox…", sandbox.id, session_id)
            await sandbox.ensure_sandbox()
            logger.info("[Warmup] Sandbox %s fully ready for session %s", sandbox.id, session_id)
            # Shared sandboxes (Replit) get per-user directory isolation;
            # dedicated sandboxes (E2B) are already fully isolated.
            if getattr(sandbox, "shared", False):
                user_sandbox = UserScopedSandbox(sandbox, session.user_id)
                await user_sandbox.setup_user_home()
            elif hasattr(sandbox, "setup_user_home"):
                await sandbox.setup_user_home()
            # Pre-install all common packages in the background so the
            # agent never wastes task time on pip/apt installs.
            if hasattr(sandbox, "warmup_packages"):
                asyncio.ensure_future(sandbox.warmup_packages())
            # E2B quota saver: pause the freshly warmed VM immediately.
            # The (expensive) first-boot install already happened in the
            # background, and the first message auto-resumes the paused VM
            # in seconds — so a session that sits idle (or is abandoned
            # without any message) burns no compute quota.
            # SKIP the pause when a task is already attached (a chat arrived
            # during warm-up) — pausing now would pause a VM the runner is
            # actively resuming / using.
            pause = getattr(sandbox, "pause", None)
            if callable(pause):
                try:
                    current = await self._session_repository.find_by_id(session_id)
                    if current is not None and current.task_id:
                        logger.info(
                            "[Warmup] Session %s already has an active task — skipping quota pause",
                            session_id,
                        )
                    else:
                        await pause()
                except Exception as e:
                    logger.warning("[Warmup] post-warmup pause failed for session %s: %s", session_id, e)
        except Exception as e:
            logger.warning("[Warmup] Background sandbox warmup failed for session %s: %s", session_id, e)

    async def _create_task(self, session: Session) -> Task:
        """Create a new agent task — uses a per-session lock to prevent
        concurrent sandbox creation racing with the warmup task (M1).

        Fast-path: this must NOT block on sandbox readiness. On the E2B route
        the task is created with LazySandbox/LazyBrowser proxies — the VM
        allocation, resume, user-home setup, and Chrome CDP connect all run
        in the runner's background ensure while the first acknowledgement
        streams within seconds of the user's message."""
        from app.infrastructure.external.sandbox.sandbox_factory import (
            will_use_e2b,
        )

        if will_use_e2b():
            # ── E2B route: fully lazy — no session-lock wait at all ─────────
            # The resolver allocates (or reconnects) under the session lock on
            # FIRST use, so a chat that arrives while the warm-up is still
            # cold-booting the VM reuses that same VM instead of queueing
            # behind it or creating a duplicate.
            async def _resolve_sandbox(replace: bool = False) -> Sandbox:
                async with self._get_session_lock(session.id):
                    fresh = await self._session_repository.find_by_id(session.id)
                    sid = fresh.sandbox_id if fresh else None
                    sandbox = None
                    if sid and not replace:
                        try:
                            sandbox = await self._sandbox_cls.get(sid)
                        except Exception as exc:
                            logger.warning(
                                "Failed to reconnect to sandbox %s (%s) — creating a new one",
                                sid, exc,
                            )
                            sandbox = None
                    if not sandbox:
                        sandbox = await self._sandbox_cls.create()
                        if fresh is not None:
                            fresh.sandbox_id = sandbox.id
                            await self._session_repository.save(fresh)
                    return sandbox

            sandbox = LazySandbox(_resolve_sandbox)
            browser = LazyBrowser(sandbox)
        else:
            # ── Shared (local Replit) route: synchronous — fast local ops ──
            async with self._get_session_lock(session.id):
                # RE-FETCH the session inside the lock — the warm-up may have
                # allocated a sandbox while this chat was waiting for the lock.
                fresh = await self._session_repository.find_by_id(session.id)
                if fresh is not None:
                    session = fresh

                sandbox = None
                sandbox_id = session.sandbox_id
                if sandbox_id:
                    try:
                        sandbox = await self._sandbox_cls.get(sandbox_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to reconnect to existing sandbox %s (%s) — creating a new one",
                            sandbox_id, exc,
                        )
                        sandbox = None
                if not sandbox:
                    sandbox = await self._sandbox_cls.create()
                    session.sandbox_id = sandbox.id
                    await self._session_repository.save(session)

                if getattr(sandbox, "shared", False):
                    sandbox = UserScopedSandbox(sandbox, session.user_id)
                    await sandbox.setup_user_home()

                browser = LazyBrowser(sandbox)
                await self._session_repository.save(session)

        # Project instructions: when the session belongs to a project that
        # defines an instruction, inject it into the system prompt so every
        # task in the project follows the same guidance (Manus behaviour).
        project_instruction: Optional[str] = None
        if getattr(session, "project_id", None) and self._project_repository:
            try:
                project = await self._project_repository.find_by_id_and_user_id(
                    session.project_id, session.user_id
                )
                if project and (project.instruction or "").strip():
                    project_instruction = project.instruction
            except Exception as exc:
                logger.warning(
                    "Failed to load project %s instructions for session %s: %s",
                    session.project_id, session.id, exc,
                )

        task_runner = AgentTaskRunner(
            session_id=session.id,
            agent_id=session.agent_id,
            user_id=session.user_id,
            sandbox=sandbox,
            browser=browser,
            file_storage=self._file_storage,
            search_engine=self._search_engine,
            session_repository=self._session_repository,
            agent_repository=self._repository,
            mcp_repository=self._mcp_repository,
            project_instruction=project_instruction,
        )

        task = self._task_cls.create(task_runner)
        session.task_id = task.id
        await self._session_repository.save(session)

        return task
        
    async def _get_task(self, session: Session) -> Optional[Task]:
        """Get a task for the given session"""

        task_id = session.task_id
        if not task_id:
            return None
        
        return self._task_cls.get(task_id)

    async def stop_session(self, session_id: str) -> None:
        """Stop a session"""
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Attempted to stop non-existent Session {session_id}")
            raise RuntimeError("Session not found")
        task = await self._get_task(session)
        if task:
            task.cancel()
        await self._session_repository.update_status(session_id, SessionStatus.COMPLETED)

    async def chat(
        self,
        session_id: str,
        user_id: str,
        message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        latest_event_id: Optional[str] = None,
        attachments: Optional[List[dict]] = None
    ) -> AsyncGenerator[BaseEvent, None]:
        """
        Chat with an agent
        """

        try:
            session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
            if not session:
                logger.error(f"Attempted to chat with non-existent Session {session_id} for user {user_id}")
                raise RuntimeError("Session not found")

            task = await self._get_task(session)

            if message:
                # ── Deduplication ──────────────────────────────────────────────
                # fetchEventSource (frontend) automatically retries the same POST
                # when the SSE connection drops.  If the session is already RUNNING
                # and the incoming timestamp is within 10 s of the last queued
                # message we treat this as a reconnect — skip re-queuing and just
                # re-subscribe to the already-running output stream.
                def _to_utc_naive(dt: datetime) -> datetime:
                    """Strip timezone for safe comparison."""
                    if dt.tzinfo is not None:
                        return dt.astimezone(timezone.utc).replace(tzinfo=None)
                    return dt

                incoming_ts = _to_utc_naive(timestamp) if timestamp else None
                stored_ts   = _to_utc_naive(session.latest_message_at) if session.latest_message_at else None

                is_reconnect = (
                    session.status == SessionStatus.RUNNING
                    and task is not None
                    and incoming_ts is not None
                    and stored_ts is not None
                    and abs((incoming_ts - stored_ts).total_seconds()) < 10
                )

                if is_reconnect:
                    logger.info(
                        "[Dedup] Session %s: duplicate message detected (reconnect) — "
                        "skipping re-queue, re-subscribing to existing task output",
                        session_id,
                    )
                else:
                    if session.status != SessionStatus.RUNNING or task is None:
                        task = await self._create_task(session)
                        if not task:
                            raise RuntimeError("Failed to create task")

                    assert task is not None, "task must not be None after creation guard"
                    await self._session_repository.update_latest_message(session_id, message, timestamp or datetime.now())

                    message_event = MessageEvent(
                        message=message,
                        role="user",
                        attachments=[
                            FileInfo(
                                file_id=attachment.get("file_id"),
                                filename=attachment.get("filename"),
                                content_type=attachment.get("content_type"),
                                size=attachment.get("size"),
                            )
                            for attachment in attachments
                        ] if attachments else None
                    )

                    event_id = await task.input_stream.put(message_event.model_dump_json())
                    message_event.id = event_id
                    await self._session_repository.add_event(session_id, message_event)

                    await task.run()
                    logger.debug(f"Put message into Session {session_id}'s event queue: {message[:50]}...")
            
            logger.info(f"Session {session_id} started")
            logger.debug(f"Session {session_id} task: {task}")
           
            # Drain the task's output stream until a TERMINAL event (done /
            # error / wait) is delivered. Do NOT stop merely because the
            # producing task finished: the client consumes events slower than
            # the agent produces them (e.g. streaming a long summary in
            # chunks), and stopping at `task.done` dropped the final summary
            # message and the DoneEvent — the stream closed while the user was
            # still waiting ("execution stopped before it finished" bug).
            while task:
                event_id, event_str = await task.output_stream.get(
                    start_id=latest_event_id, block_ms=1000
                )
                # Keep the last valid cursor — get() returns (None, None) on
                # timeout/transport errors, and resetting the cursor to None
                # would replay the whole stream from "0" (duplicate events).
                if event_id is not None:
                    latest_event_id = event_id
                if event_str is None:
                    if task.done:
                        # No new events for a full block window AND the
                        # producer has finished — the stream is fully drained
                        # (terminal events are always put before the task
                        # completes, so this only happens if they were lost).
                        logger.info(
                            "Session %s output stream drained after task completion",
                            session_id,
                        )
                        break
                    continue
                event = TypeAdapter(AgentEvent).validate_json(event_str)
                event.id = latest_event_id
                logger.debug(f"Got event from Session {session_id}'s event queue: {type(event).__name__}")
                await self._session_repository.update_unread_message_count(session_id, 0)
                yield event
                if isinstance(event, (DoneEvent, ErrorEvent, WaitEvent)):
                    break
            
            logger.info(f"Session {session_id} completed")

        except Exception as e:
            logger.exception(f"Error in Session {session_id}")
            event = ErrorEvent(error=str(e))
            await self._session_repository.add_event(session_id, event)
            # Yield the ErrorEvent so the SSE stream delivers the error to the
            # frontend before closing. Raising an HTTP exception here is not
            # possible — the response has already started streaming.
            yield event
            return
        finally:
            await self._session_repository.update_unread_message_count(session_id, 0)