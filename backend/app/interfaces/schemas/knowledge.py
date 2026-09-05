from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.domain.models.knowledge import KnowledgeStatus


class KnowledgeItemResponse(BaseModel):
    """One knowledge item as shown to the user."""
    knowledge_id: str
    content: str
    kind: str = "user"
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    source_session_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ListKnowledgeResponse(BaseModel):
    items: List[KnowledgeItemResponse]


class AddKnowledgeRequest(BaseModel):
    """User-added durable knowledge ('always remember that ...')."""
    content: str = Field(min_length=2, max_length=1000)


class AddKnowledgeResponse(BaseModel):
    knowledge_id: str


class UpdateKnowledgeStatusRequest(BaseModel):
    """Accept or reject a PENDING learning proposal (or re-activate)."""
    status: KnowledgeStatus


class UpdateKnowledgeStatusResponse(BaseModel):
    knowledge_id: str
    status: KnowledgeStatus
