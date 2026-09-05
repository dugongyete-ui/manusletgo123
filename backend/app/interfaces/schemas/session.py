from pydantic import BaseModel
from typing import Optional, List
from app.interfaces.schemas.event import AgentSSEEvent
from app.domain.models.session import SessionStatus


class ChatRequest(BaseModel):
    """Chat request schema"""
    timestamp: Optional[int] = None
    message: Optional[str] = None
    attachments: Optional[List[dict]] = None
    event_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Optional body when creating a session.

    agent_profile_id: built-in preset id ("builtin-general", ...) or one of
    the user's custom agent profile ids. Omitted → default Dzeck behaviour.
    """
    agent_profile_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    """Create session response schema"""
    session_id: str


class ForkSessionResponse(BaseModel):
    """Fork session response schema — the new session the user now owns."""
    session_id: str
    title: Optional[str] = None


class ShellViewRequest(BaseModel):
    """Shell view request schema"""
    session_id: str


class CreateSessionResponse(BaseModel):
    """Create session response schema"""
    session_id: str


class GetSessionResponse(BaseModel):
    """Get session response schema"""
    session_id: str
    title: Optional[str] = None
    status: SessionStatus
    events: List[AgentSSEEvent] = []
    is_shared: bool = False


class ListSessionItem(BaseModel):
    """List session item schema"""
    session_id: str
    title: Optional[str] = None
    latest_message: Optional[str] = None
    latest_message_at: Optional[int] = None
    status: SessionStatus
    unread_message_count: int
    is_shared: bool = False
    project_id: Optional[str] = None


class ListSessionResponse(BaseModel):
    """List session response schema"""
    sessions: List[ListSessionItem]


class ConsoleRecord(BaseModel):
    """Console record schema"""
    ps1: str
    command: str
    output: str


class ShellViewResponse(BaseModel):
    """Shell view response schema"""
    output: str
    session_id: str
    console: Optional[List[ConsoleRecord]] = None


class ShareSessionResponse(BaseModel):
    """Share session response schema"""
    session_id: str
    is_shared: bool


class SharedSessionResponse(BaseModel):
    """Shared session response schema (for public access)"""
    session_id: str
    title: Optional[str] = None
    status: SessionStatus
    events: List[AgentSSEEvent] = []
    is_shared: bool


class MoveSessionProjectRequest(BaseModel):
    """Move session to project (null to remove from project)"""
    project_id: Optional[str] = None


class MoveSessionProjectResponse(BaseModel):
    session_id: str
    project_id: Optional[str] = None


class LibraryFileItem(BaseModel):
    """Library file item schema (files aggregated across sessions)"""
    session_id: str
    session_title: Optional[str] = None
    file_id: Optional[str] = None
    filename: Optional[str] = None
    file_path: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None
    upload_date: Optional[str] = None
    is_favorite: bool = False
    latest_message_at: Optional[int] = None


class LibraryResponse(BaseModel):
    """Library files response schema"""
    files: List[LibraryFileItem]


class FavoriteLibraryFileResponse(BaseModel):
    """Favorite library file response schema"""
    file_id: str
    is_favorite: bool
