from typing import Optional, Protocol, List
from app.domain.models.agent_profile import AgentProfile


class AgentProfileRepository(Protocol):
    """Repository interface for user-customisable agent profiles."""

    async def save(self, profile: AgentProfile) -> None:
        ...

    async def find_by_id_and_user_id(self, profile_id: str, user_id: str) -> Optional[AgentProfile]:
        ...

    async def find_by_user_id(self, user_id: str) -> List[AgentProfile]:
        ...

    async def delete(self, profile_id: str, user_id: str) -> None:
        ...
