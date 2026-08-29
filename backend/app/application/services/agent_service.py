from typing import AsyncGenerator, Optional, List
import asyncio
import logging
from datetime import datetime
from app.domain.models.session import Session, SessionSummary
from app.domain.repositories.session_repository import SessionRepository

from app.interfaces.schemas.session import ShellViewResponse
from app.interfaces.schemas.file import FileViewResponse
from app.domain.models.agent import Agent
from app.domain.services.agent_domain_service import AgentDomainService
from app.domain.models.event import AgentEvent
from typing import Type
from app.domain.models.agent import Agent
from app.domain.external.sandbox import Sandbox
from app.domain.external.search import SearchEngine
from app.domain.external.file import FileStorage
from app.domain.repositories.agent_repository import AgentRepository
from app.domain.repositories.file_favorite_repository import FileFavoriteRepository
from app.domain.external.task import Task
from app.domain.models.file import FileInfo
from app.core.config import get_settings
from app.domain.repositories.mcp_repository import MCPRepository
from app.domain.models.session import SessionStatus

# Set up logger
logger = logging.getLogger(__name__)

class AgentService:
    def __init__(
        self,
        agent_repository: AgentRepository,
        session_repository: SessionRepository,
        sandbox_cls: Type[Sandbox],
        task_cls: Type[Task],
        file_storage: FileStorage,
        mcp_repository: MCPRepository,
        search_engine: Optional[SearchEngine] = None,
        file_favorite_repository: Optional[FileFavoriteRepository] = None,
        project_repository=None,
    ):
        logger.info("Initializing AgentService")
        self._agent_repository = agent_repository
        self._session_repository = session_repository
        self._file_storage = file_storage
        self._file_favorite_repository = file_favorite_repository
        self._agent_domain_service = AgentDomainService(
            self._agent_repository,
            self._session_repository,
            sandbox_cls,
            task_cls,
            file_storage,
            mcp_repository,
            search_engine,
            project_repository=project_repository,
        )
        self._search_engine = search_engine
        self._sandbox_cls = sandbox_cls
    
    async def create_session(self, user_id: str) -> Session:
        logger.info(f"Creating new session for user: {user_id}")
        agent = await self._create_agent()
        session = Session(agent_id=agent.id, user_id=user_id)
        logger.info(f"Created new Session with ID: {session.id} for user: {user_id}")
        await self._session_repository.save(session)
        # Warm up Replit sandbox in background so the first chat message is not
        # blocked by the sandbox readiness check.
        asyncio.get_event_loop().create_task(
            self._warmup_sandbox(session.id),
            name=f"sandbox-warmup-{session.id}",
        )
        return session

    async def _warmup_sandbox(self, session_id: str) -> None:
        """Delegate background sandbox warmup to domain service (uses per-session lock)."""
        await self._agent_domain_service.warmup_sandbox(session_id)

    async def _create_agent(self) -> Agent:
        logger.info("Creating new agent")
        settings = get_settings()
        agent = Agent(
            model_name=settings.model_name,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
        logger.info(f"Created new Agent with ID: {agent.id}")
        
        # Save agent to repository
        await self._agent_repository.save(agent)
        logger.info(f"Saved agent {agent.id} to repository")
        
        logger.info(f"Agent created successfully with ID: {agent.id}")
        return agent

    async def chat(
        self,
        session_id: str,
        user_id: str,
        message: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        event_id: Optional[str] = None,
        attachments: Optional[List[dict]] = None
    ) -> AsyncGenerator[AgentEvent, None]:
        logger.info(f"Starting chat with session {session_id}: {(message or '')[:50]}...")
        # Directly use the domain service's chat method, which will check if the session exists
        async for event in self._agent_domain_service.chat(session_id, user_id, message, timestamp, event_id, attachments):
            logger.debug(f"Received event: {event}")
            yield event
        logger.info(f"Chat with session {session_id} completed")
    
    async def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """Get a session by ID, ensuring it belongs to the user"""
        logger.info(f"Getting session {session_id} for user {user_id}")
        if not user_id:
            session = await self._session_repository.find_by_id(session_id)
        else:
            session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
        return session
    
    async def get_all_sessions(self, user_id: str) -> List[SessionSummary]:
        """Get all sessions for a specific user (lightweight summaries)"""
        logger.debug(f"Getting all sessions for user {user_id}")
        return await self._session_repository.find_summaries_by_user_id(user_id)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        """Delete a session, ensuring it belongs to the user"""
        logger.info(f"Deleting session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")

        # Purge GridFS artifacts referenced by this session's events
        # (browser screenshots / tool file previews) BEFORE dropping the
        # document — otherwise they leak forever on the 512MB Atlas free
        # tier and eventually block ALL writes (quota exhausted).
        await self._purge_session_files(session, user_id)

        await self._session_repository.delete(session_id)
        logger.info(f"Session {session_id} deleted successfully")

    async def _purge_session_files(self, session: Session, user_id: str) -> None:
        """Best-effort deletion of every GridFS file referenced by a session's events."""
        try:
            file_ids = set()
            for event in getattr(session, "events", []) or []:
                tool_content = getattr(event, "tool_content", None)
                if not tool_content:
                    continue
                for field in ("screenshot", "file_id"):
                    fid = getattr(tool_content, field, None)
                    if fid:
                        file_ids.add(fid)
            for file_info in getattr(session, "files", []) or []:
                if getattr(file_info, "file_id", None):
                    file_ids.add(file_info.file_id)
            for file_id in file_ids:
                try:
                    await self._file_storage.delete_file(file_id, user_id)
                except Exception:
                    # File may already be gone (retention deleted it) — ignore.
                    pass
            if file_ids:
                logger.info(f"Purged {len(file_ids)} GridFS files of session {session.id}")
        except Exception as e:
            # Never let cleanup block a user-facing delete.
            logger.warning(f"File purge for session {session.id} failed: {e}")

    async def delete_all_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user"""
        logger.info(f"Deleting all sessions for user {user_id}")
        count = await self._session_repository.delete_all_by_user_id(user_id)
        logger.info(f"Deleted {count} sessions for user {user_id}")
        return count

    async def stop_session(self, session_id: str, user_id: str) -> None:
        """Stop a session, ensuring it belongs to the user"""
        logger.info(f"Stopping session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        await self._agent_domain_service.stop_session(session_id)
        logger.info(f"Session {session_id} stopped successfully")

    async def clear_unread_message_count(self, session_id: str, user_id: str) -> None:
        """Clear the unread message count for a session, ensuring it belongs to the user"""
        logger.info(f"Clearing unread message count for session {session_id} for user {user_id}")
        await self._session_repository.update_unread_message_count(session_id, 0)
        logger.info(f"Unread message count cleared for session {session_id}")

    async def shutdown(self):
        logger.info("Closing all agents and cleaning up resources")
        # Clean up all Agents and their associated sandboxes
        await self._agent_domain_service.shutdown()
        logger.info("All agents closed successfully")

    async def shell_view(self, session_id: str, shell_session_id: str, user_id: str) -> ShellViewResponse:
        """View shell session output, ensuring session belongs to the user"""
        logger.info(f"Getting shell view for session {session_id} for user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        
        if not session.sandbox_id:
            raise RuntimeError("Session has no sandbox environment")
        
        # Get sandbox and shell output
        sandbox = await self._sandbox_cls.get(session.sandbox_id)
        if not sandbox:
            raise RuntimeError("Sandbox environment not found")
        
        result = await sandbox.view_shell(shell_session_id, console=True)
        if result.success:
            return ShellViewResponse(**result.data)
        else:
            raise RuntimeError(f"Failed to get shell output: {result.message}")

    async def get_vnc_url(self, session_id: str) -> str:
        """Get VNC URL for a session, ensuring it belongs to the user"""
        logger.info(f"Getting VNC URL for session {session_id}")

        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            raise RuntimeError("Session not found")

        if not session.sandbox_id:
            raise RuntimeError("Session has no sandbox environment")

        # Get sandbox and return VNC URL
        sandbox = await self._sandbox_cls.get(session.sandbox_id)
        if not sandbox:
            raise RuntimeError("Sandbox environment not found")

        return sandbox.vnc_url

    async def get_vnc_sandbox(self, session_id: str):
        """Get the sandbox object backing a session's live view (takeover).

        Reconnecting auto-resumes a paused E2B sandbox and re-bootstraps its
        VNC stack, so the user's takeover screen comes alive even after the
        post-summary quota-saver pause. Returns the sandbox itself (not just
        the URL) so the VNC websocket route can attach viewer accounting —
        while a viewer is connected the sandbox must not be paused.
        """
        logger.info(f"Getting VNC sandbox for session {session_id}")

        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            raise RuntimeError("Session not found")

        if not session.sandbox_id:
            raise RuntimeError("Session has no sandbox environment")

        sandbox = await self._sandbox_cls.get(session.sandbox_id)
        if not sandbox:
            raise RuntimeError("Sandbox environment not found")

        return sandbox

    async def file_view(self, session_id: str, file_path: str, user_id: str) -> FileViewResponse:
        """View file content, ensuring session belongs to the user"""
        logger.info(f"Getting file view for session {session_id} for user {user_id}")
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        
        if not session.sandbox_id:
            raise RuntimeError("Session has no sandbox environment")
        
        # Get sandbox and file content
        sandbox = await self._sandbox_cls.get(session.sandbox_id)
        if not sandbox:
            raise RuntimeError("Sandbox environment not found")
        
        result = await sandbox.file_read(file_path)
        if result.success:
            return FileViewResponse(**result.data)
        else:
            raise RuntimeError(f"Failed to read file: {result.message}")
    
    async def is_session_shared(self, session_id: str) -> bool:
        """Check if a session is shared"""
        logger.info(f"Checking if session {session_id} is shared")
        session = await self._session_repository.find_by_id(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            raise RuntimeError("Session not found")
        return session.is_shared

    async def get_session_files(self, session_id: str, user_id: Optional[str] = None) -> List[FileInfo]:
        """Get files for a session, ensuring it belongs to the user"""
        logger.info(f"Getting files for session {session_id} for user {user_id}")
        session = await self.get_session(session_id, user_id)
        if not session:
            raise RuntimeError("Session not found")
        return session.files
    
    async def get_shared_session_files(self, session_id: str) -> List[FileInfo]:
        """Get files for a shared session"""
        logger.info(f"Getting files for shared session {session_id}")
        session = await self._session_repository.find_by_id(session_id)
        if not session or not session.is_shared:
            logger.error(f"Shared session {session_id} not found or not shared")
            raise RuntimeError("Session not found")
        return session.files

    async def share_session(self, session_id: str, user_id: str) -> None:
        """Share a session, ensuring it belongs to the user"""
        logger.info(f"Sharing session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        
        await self._session_repository.update_shared_status(session_id, True)
        logger.info(f"Session {session_id} shared successfully")

    async def unshare_session(self, session_id: str, user_id: str) -> None:
        """Unshare a session, ensuring it belongs to the user"""
        logger.info(f"Unsharing session {session_id} for user {user_id}")
        # First verify the session belongs to the user
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        
        await self._session_repository.update_shared_status(session_id, False)
        logger.info(f"Session {session_id} unshared successfully")

    async def get_shared_session(self, session_id: str) -> Optional[Session]:
        """Get a shared session by ID (no user authentication required)"""
        logger.info(f"Getting shared session {session_id}")
        session = await self._session_repository.find_by_id(session_id)
        if not session or not session.is_shared:
            logger.error(f"Shared session {session_id} not found or not shared")
            return None
        return session

    # ─────────────────────────────────────────────────────────────────
    # Library (files aggregated across sessions)
    # ─────────────────────────────────────────────────────────────────

    async def get_library_files(self, user_id: str, limit: int = 100) -> List[dict]:
        """Aggregate recent files across the user's sessions for Library view"""
        sessions = await self._session_repository.find_by_user_id(user_id)
        sessions = sorted(
            sessions,
            key=lambda s: s.latest_message_at or s.updated_at,
            reverse=True,
        )
        favorite_ids: set = set()
        if self._file_favorite_repository:
            favorite_ids = await self._file_favorite_repository.list_favorite_file_ids(user_id)
        items: List[dict] = []
        for session in sessions:
            for file_info in session.files or []:
                upload_date = getattr(file_info, "upload_date", None)
                file_id = file_info.file_id
                items.append({
                    "session_id": session.id,
                    "session_title": session.title,
                    "file_id": file_id,
                    "filename": file_info.filename,
                    "file_path": getattr(file_info, "file_path", None),
                    "content_type": getattr(file_info, "content_type", None),
                    "size": getattr(file_info, "size", None),
                    "upload_date": upload_date.isoformat() if upload_date else None,
                    "is_favorite": bool(file_id and file_id in favorite_ids),
                    "latest_message_at": (
                        int(session.latest_message_at.timestamp())
                        if session.latest_message_at
                        else None
                    ),
                })
                if len(items) >= limit:
                    return items
        return items

    async def update_library_file_favorite(
        self,
        file_id: str,
        user_id: str,
        is_favorite: bool,
    ) -> None:
        """Update favorite status of a library file (per attachment, not session)."""
        if not self._file_favorite_repository:
            raise RuntimeError("File favorite repository not available")
        if not await self._user_owns_library_file(user_id, file_id):
            raise RuntimeError("File not found")
        await self._file_favorite_repository.set_favorite(user_id, file_id, is_favorite)

    async def _user_owns_library_file(self, user_id: str, file_id: str) -> bool:
        sessions = await self._session_repository.find_by_user_id(user_id)
        for session in sessions:
            for file_info in session.files or []:
                if file_info.file_id == file_id:
                    return True
        return False

    async def update_session_project(
        self, session_id: str, user_id: str, project_id: Optional[str]
    ) -> None:
        """Move a session into a project (or out of it when project_id is None)."""
        session = await self._session_repository.find_by_id_and_user_id(session_id, user_id)
        if not session:
            logger.error(f"Session {session_id} not found for user {user_id}")
            raise RuntimeError("Session not found")
        await self._session_repository.update_project_id(session_id, project_id)
        logger.info(f"Session {session_id} moved to project {project_id}")