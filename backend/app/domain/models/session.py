from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import List, Optional
from enum import Enum
import uuid
from app.domain.models.event import PlanEvent, AgentEvent
from app.domain.models.plan import Plan
from app.domain.models.file import FileInfo


class SessionStatus(str, Enum):
    """Session status enum"""
    PENDING = "pending"
    # Message accepted, sandbox/task bootstrap still running — the run has
    # not started producing events yet (queue-like state, Manus IN_QUEUE).
    IN_QUEUE = "in_queue"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    # The run terminated through an unrecoverable error instead of a normal
    # summary — surfaced honestly instead of masquerading as COMPLETED.
    FAILED = "failed"


class SessionSummary(BaseModel):
    """Lightweight session model for list views (excludes heavy events/files)"""
    id: str
    user_id: str
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = None
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False
    project_id: Optional[str] = None


class Session(BaseModel):
    """Session model"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str  # User ID that owns this session
    sandbox_id: Optional[str] = Field(default=None)  # Identifier for the sandbox environment
    agent_id: str
    task_id: Optional[str] = None
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    events: List[AgentEvent] = []
    files: List[FileInfo] = []
    status: SessionStatus = SessionStatus.PENDING
    is_shared: bool = False  # Whether this session is shared publicly
    project_id: Optional[str] = None  # Project this session belongs to
    # Agent profile (custom preset) this session was created with — its
    # instruction is appended to the system prompt of every run.
    agent_profile_id: Optional[str] = None

    def get_last_plan(self) -> Optional[Plan]:
        """Get the last plan from the events"""
        for event in reversed(self.events):
            if isinstance(event, PlanEvent):
                return event.plan
        return None