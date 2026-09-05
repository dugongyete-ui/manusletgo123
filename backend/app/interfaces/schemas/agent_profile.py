from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.domain.models.agent_profile import AgentProfile


class AgentProfileResponse(BaseModel):
    profile_id: str
    name: str
    description: Optional[str] = None
    emoji: Optional[str] = None
    instruction: str = ""
    is_builtin: bool = False
    created_at: Optional[datetime] = None

    @staticmethod
    def from_domain(profile: AgentProfile) -> "AgentProfileResponse":
        return AgentProfileResponse(
            profile_id=profile.id,
            name=profile.name,
            description=profile.description,
            emoji=profile.emoji,
            instruction=profile.instruction,
            is_builtin=profile.is_builtin,
            created_at=profile.created_at,
        )


class ListAgentProfileResponse(BaseModel):
    profiles: List[AgentProfileResponse]


class CreateAgentProfileRequest(BaseModel):
    """User-created agent preset."""
    name: str = Field(min_length=1, max_length=60)
    description: Optional[str] = Field(default=None, max_length=300)
    emoji: Optional[str] = Field(default=None, max_length=4)
    instruction: str = Field(min_length=10, max_length=4000)


class CreateAgentProfileResponse(BaseModel):
    profile_id: str
