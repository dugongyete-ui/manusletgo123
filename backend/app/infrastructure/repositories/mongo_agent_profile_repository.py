from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.agent_profile import AgentProfile
from app.infrastructure.models.documents import AgentProfileDocument
import logging

logger = logging.getLogger(__name__)


class MongoAgentProfileRepository:
    """MongoDB implementation of AgentProfileRepository."""

    async def save(self, profile: AgentProfile) -> None:
        doc = await AgentProfileDocument.find_one(
            AgentProfileDocument.profile_id == profile.id
        )
        if not doc:
            doc = AgentProfileDocument.from_domain(profile)
            await doc.save()
            return
        doc.update_from_domain(profile)
        await doc.save()

    async def find_by_id_and_user_id(self, profile_id: str, user_id: str) -> Optional[AgentProfile]:
        doc = await AgentProfileDocument.find_one(
            AgentProfileDocument.profile_id == profile_id,
            AgentProfileDocument.user_id == user_id,
        )
        return doc.to_domain() if doc else None

    async def find_by_user_id(self, user_id: str) -> List[AgentProfile]:
        docs = (
            await AgentProfileDocument.find(
                AgentProfileDocument.user_id == user_id,
            )
            .sort([("created_at", 1)])
            .to_list()
        )
        return [d.to_domain() for d in docs]

    async def delete(self, profile_id: str, user_id: str) -> None:
        doc = await AgentProfileDocument.find_one(
            AgentProfileDocument.profile_id == profile_id,
            AgentProfileDocument.user_id == user_id,
        )
        if doc:
            await doc.delete()
