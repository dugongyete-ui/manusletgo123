from typing import Dict, Optional, List, Type, TypeVar, Generic, get_args, Self
from datetime import datetime, timezone, UTC
from beanie import Document
from pydantic import BaseModel, Field
from app.domain.models.agent import Agent
from app.domain.models.memory import Memory
from app.domain.models.event import AgentEvent
from app.domain.models.session import Session, SessionStatus
from app.domain.models.file import FileInfo
from app.domain.models.user import User, UserRole
from app.domain.models.project import Project
from app.domain.models.knowledge import KnowledgeItem
from app.domain.models.scheduled_task import ScheduledTask
from app.domain.models.agent_profile import AgentProfile
from pymongo import IndexModel, ASCENDING, DESCENDING

T = TypeVar('T', bound=BaseModel)

class BaseDocument(Document, Generic[T]):
    def __init_subclass__(cls, id_field="id", domain_model_class: Type[T] = None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._ID_FIELD = id_field
        cls._DOMAIN_MODEL_CLASS = domain_model_class
    
    def update_from_domain(self, domain_obj: T) -> None:
        """Update the document from domain model"""
        data = domain_obj.model_dump(exclude={'id', 'created_at'})
        data[self._ID_FIELD] = domain_obj.id
        if hasattr(self, 'updated_at'):
            data['updated_at'] = datetime.now(UTC)
        
        for field, value in data.items():
            setattr(self, field, value)
    
    def to_domain(self) -> T:
        """Convert MongoDB document to domain model"""
        # Convert to dict and map agent_id to id field
        data = self.model_dump(exclude={'id'})
        data['id'] = data.pop(self._ID_FIELD)
        return self._DOMAIN_MODEL_CLASS.model_validate(data)
    
    @classmethod
    def from_domain(cls, domain_obj: T) -> Self:
        """Create a new MongoDB agent from domain"""
        # Convert to dict and map id to agent_id field
        data = domain_obj.model_dump()
        data[cls._ID_FIELD] = data.pop('id')
        return cls.model_validate(data)

class UserDocument(BaseDocument[User], id_field="user_id", domain_model_class=User):
    """MongoDB document for User"""
    user_id: str
    fullname: str
    email: str  # Now required field for login
    password_hash: Optional[str] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)
    last_login_at: Optional[datetime] = None

    class Settings:
        name = "users"
        indexes = [
            "user_id",
            "fullname",  # Keep fullname index but not unique
            IndexModel([("email", ASCENDING)], unique=True),  # Email as unique index
        ]

class AgentDocument(BaseDocument[Agent], id_field="agent_id", domain_model_class=Agent):
    """MongoDB document for Agent"""
    agent_id: str
    model_name: str
    temperature: float
    max_tokens: int
    memories: Dict[str, Memory] = {}
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)

    class Settings:
        name = "agents"
        indexes = [
            "agent_id",
        ]


class SessionDocument(BaseDocument[Session], id_field="session_id", domain_model_class=Session):
    """MongoDB model for Session"""
    session_id: str
    user_id: str  # User ID that owns this session
    sandbox_id: Optional[str] = None
    agent_id: str
    task_id: Optional[str] = None
    title: Optional[str] = None
    unread_message_count: int = 0
    latest_message: Optional[str] = None
    latest_message_at: Optional[datetime] = None
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)
    events: List[AgentEvent]
    status: SessionStatus
    files: List[FileInfo] = []
    is_shared: Optional[bool] = False
    project_id: Optional[str] = None
    agent_profile_id: Optional[str] = None
    class Settings:
        name = "sessions"
        indexes = [
            "session_id",
            "user_id",
            "project_id",
            IndexModel(
                [("user_id", ASCENDING), ("latest_message_at", DESCENDING)],
                name="user_id_latest_message_at",
            ),
        ]


class ProjectDocument(BaseDocument[Project], id_field="project_id", domain_model_class=Project):
    """MongoDB document for Project"""
    project_id: str
    user_id: str
    name: str
    instruction: Optional[str] = None
    is_pinned: bool = False
    sort_order: int = 0
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)

    class Settings:
        name = "projects"
        indexes = [
            "project_id",
            "user_id",
            IndexModel(
                [("user_id", ASCENDING), ("is_pinned", DESCENDING), ("sort_order", ASCENDING), ("updated_at", DESCENDING)],
                name="user_id_pinned_sort",
            ),
        ]


class FileFavoriteDocument(Document):
    """Per-user library file favorite (attachment-level, not session-level)."""
    user_id: str
    file_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "file_favorites"
        indexes = [
            IndexModel(
                [("user_id", ASCENDING), ("file_id", ASCENDING)],
                unique=True,
                name="user_id_file_id",
            ),
        ]


class KnowledgeDocument(BaseDocument[KnowledgeItem], id_field="knowledge_id", domain_model_class=KnowledgeItem):
    """Per-user durable knowledge items (user-added + agent learnings)."""
    knowledge_id: str
    user_id: str
    content: str
    kind: str = "user"
    status: str = "active"
    source_session_id: Optional[str] = None
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)

    class Settings:
        name = "knowledge"
        indexes = [
            "knowledge_id",
            IndexModel(
                [("user_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
                name="user_id_status_updated",
            ),
        ]


class ScheduledTaskDocument(BaseDocument[ScheduledTask], id_field="task_id", domain_model_class=ScheduledTask):
    """Recurring agent runs (scheduleTask)."""
    task_id: str
    user_id: str
    prompt: str
    session_id: str
    interval_minutes: int = 1440
    next_run_at: datetime = datetime.now(timezone.utc)
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    is_active: bool = True
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)

    class Settings:
        name = "scheduled_tasks"
        indexes = [
            "task_id",
            "user_id",
            IndexModel(
                [("is_active", ASCENDING), ("next_run_at", ASCENDING)],
                name="active_next_run",
            ),
        ]


class AgentProfileDocument(BaseDocument[AgentProfile], id_field="profile_id", domain_model_class=AgentProfile):
    """User-customisable agent presets."""
    profile_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    emoji: Optional[str] = None
    instruction: str = ""
    is_builtin: bool = False
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)

    class Settings:
        name = "agent_profiles"
        indexes = [
            "profile_id",
            "user_id",
        ]


