from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import Optional
from enum import Enum
import uuid


class KnowledgeStatus(str, Enum):
    """Lifecycle of a knowledge item.

    PENDING  — proposed by the agent after a task (learning proposal); the
               user has not decided yet.
    ACTIVE   — accepted (or added manually by the user); injected into every
               future session context for this user.
    REJECTED — declined by the user; kept for reference, never injected.
    """

    PENDING = "pending"
    ACTIVE = "active"
    REJECTED = "rejected"


class KnowledgeKind(str, Enum):
    """Origin of the knowledge item.

    USER     — written by the user (preferences, constraints, facts the agent
               should always remember).
    LEARNING — distilled by the agent from a completed task and offered to
               the user for approval.
    BUILTIN  — shipped platform knowledge (not per-user).
    """

    USER = "user"
    LEARNING = "learning"
    BUILTIN = "builtin"


class KnowledgeItem(BaseModel):
    """A single durable piece of knowledge about a user or their world.

    Manus equivalent: KNOWLEDGE_KIND_USER entries that ride along in the
    context assembly phase and the post-task KnowledgeEvent accept/reject
    learning loop.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str
    content: str
    kind: KnowledgeKind = KnowledgeKind.USER
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    # Session the learning was distilled from (kind=LEARNING only).
    source_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
