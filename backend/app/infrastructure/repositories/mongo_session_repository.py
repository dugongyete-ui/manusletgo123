from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.session import Session, SessionStatus, SessionSummary
from app.domain.models.file import FileInfo
from app.domain.repositories.session_repository import SessionRepository
from app.domain.models.event import BaseEvent
from app.infrastructure.models.documents import SessionDocument
import logging

logger = logging.getLogger(__name__)

SESSION_LIST_PROJECTION = {
    "session_id": 1,
    "user_id": 1,
    "title": 1,
    "unread_message_count": 1,
    "latest_message": 1,
    "latest_message_at": 1,
    "status": 1,
    "is_shared": 1,
    "project_id": 1,
}

class MongoSessionRepository(SessionRepository):
    """MongoDB implementation of SessionRepository"""
    
    async def save(self, session: Session) -> None:
        """Save or update a session.

        UPDATE path merges SCALAR fields only ($set) — it must NEVER
        replace the ``events`` and ``files`` arrays.  Those arrays are
        managed exclusively through the atomic add_event / add_file /
        remove_file operations ($push / $pull).  The previous
        whole-document replace (update_from_domain + save) silently
        wiped concurrently persisted events: e.g. the early-persisted
        user message was erased when warmup_sandbox() / _create_task()
        later saved their own older in-memory copy of the session
        (the "user message bubble disappears" bug).
        """
        mongo_session = await SessionDocument.find_one(
            SessionDocument.session_id == session.id
        )

        if not mongo_session:
            mongo_session = SessionDocument.from_domain(session)
            await mongo_session.save()
            return

        data = session.model_dump(exclude={"id", "created_at", "events", "files"})
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session.id
        ).update({"$set": {**data, "updated_at": datetime.now(UTC)}})
        if not result:
            raise ValueError(f"Session {session.id} not found")


    async def find_by_id(self, session_id: str) -> Optional[Session]:
        """Find a session by its ID"""
        mongo_session = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        )
        return mongo_session.to_domain() if mongo_session else None
    
    async def find_by_user_id(self, user_id: str) -> List[Session]:
        """Find all sessions for a specific user"""
        mongo_sessions = await SessionDocument.find(
            SessionDocument.user_id == user_id
        ).sort("-latest_message_at").to_list()
        return [mongo_session.to_domain() for mongo_session in mongo_sessions]

    async def find_summaries_by_user_id(self, user_id: str) -> List[SessionSummary]:
        """Find lightweight session summaries for a user (excludes events/files)"""
        collection = SessionDocument.get_pymongo_collection()
        cursor = collection.find(
            {"user_id": user_id},
            SESSION_LIST_PROJECTION,
        ).sort("latest_message_at", -1)
        summaries = []
        async for doc in cursor:
            summaries.append(SessionSummary(
                id=doc["session_id"],
                user_id=doc["user_id"],
                title=doc.get("title"),
                unread_message_count=doc.get("unread_message_count", 0),
                latest_message=doc.get("latest_message"),
                latest_message_at=doc.get("latest_message_at"),
                status=doc.get("status", SessionStatus.PENDING),
                is_shared=doc.get("is_shared", False),
                project_id=doc.get("project_id"),
            ))
        return summaries
    
    async def find_by_id_and_user_id(self, session_id: str, user_id: str) -> Optional[Session]:
        """Find a session by ID and user ID (for authorization)"""
        mongo_session = await SessionDocument.find_one(
            SessionDocument.session_id == session_id,
            SessionDocument.user_id == user_id
        )
        return mongo_session.to_domain() if mongo_session else None
    
    async def update_title(self, session_id: str, title: str) -> None:
        """Update the title of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"title": title, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_latest_message(self, session_id: str, message: str, timestamp: datetime) -> None:
        """Update the latest message of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"latest_message": message, "latest_message_at": timestamp, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_sandbox_id(self, session_id: str, sandbox_id: Optional[str]) -> None:
        """Atomically update the sandbox pointer of a session (never touches events)"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"sandbox_id": sandbox_id, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_task_id(self, session_id: str, task_id: Optional[str]) -> None:
        """Atomically update the task pointer of a session (never touches events)"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"task_id": task_id, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def add_event(self, session_id: str, event: BaseEvent) -> None:
        """Add an event to a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$push": {"events": event.model_dump()}, "$set": {"updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")
    
    async def add_file(self, session_id: str, file_info: FileInfo) -> None:
        """Add a file to a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$push": {"files": file_info.model_dump()}, "$set": {"updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")
    
    async def remove_file(self, session_id: str, file_id: str) -> None:
        """Remove a file from a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$pull": {"files": {"file_id": file_id}}, "$set": {"updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def get_file_by_path(self, session_id: str, file_path: str) -> Optional[FileInfo]:
        """Get file by path from a session"""
        mongo_session = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        )
        if not mongo_session:
            raise ValueError(f"Session {session_id} not found")
        
        # Search for file with matching path
        for file_info in mongo_session.files:
            if file_info.file_path == file_path:
                return file_info
        return None

    async def delete(self, session_id: str) -> None:
        """Delete a session"""
        mongo_session = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        )
        if mongo_session:
            await mongo_session.delete()

    async def delete_all_by_user_id(self, user_id: str) -> int:
        """Delete all sessions belonging to a user, returns count deleted"""
        result = await SessionDocument.find(
            SessionDocument.user_id == user_id
        ).delete()
        count = result.deleted_count if result else 0
        logger.info(f"Deleted {count} sessions for user {user_id}")
        return count

    async def get_all(self) -> List[Session]:
        """Get all sessions"""
        mongo_sessions = await SessionDocument.find().sort("-latest_message_at").to_list()
        return [mongo_session.to_domain() for mongo_session in mongo_sessions]
    
    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update the status of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"status": status, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_unread_message_count(self, session_id: str, count: int) -> None:
        """Update the unread message count of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"unread_message_count": count, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def increment_unread_message_count(self, session_id: str) -> None:
        """Atomically increment the unread message count of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$inc": {"unread_message_count": 1}, "$set": {"updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def decrement_unread_message_count(self, session_id: str) -> None:
        """Atomically decrement the unread message count of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$inc": {"unread_message_count": -1}, "$set": {"updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_shared_status(self, session_id: str, is_shared: bool) -> None:
        """Update the shared status of a session"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"is_shared": is_shared, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def update_project_id(self, session_id: str, project_id: Optional[str]) -> None:
        """Move a session into a project (or out when project_id is None)"""
        result = await SessionDocument.find_one(
            SessionDocument.session_id == session_id
        ).update(
            {"$set": {"project_id": project_id, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Session {session_id} not found")

    async def clear_project_id(self, project_id: str) -> None:
        """Detach all sessions from a project (used when deleting the project)"""
        await SessionDocument.find(
            SessionDocument.project_id == project_id
        ).update(
            {"$set": {"project_id": None, "updated_at": datetime.now(UTC)}}
        )

