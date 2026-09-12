from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.agent import Agent
from app.domain.models.memory import Memory
from app.domain.repositories.agent_repository import AgentRepository
from app.infrastructure.models.documents import AgentDocument
import logging


logger = logging.getLogger(__name__)

class MongoAgentRepository(AgentRepository):
    """MongoDB implementation of AgentRepository"""

    async def save(self, agent: Agent) -> None:
        """Save or update an agent"""
        mongo_agent = await AgentDocument.find_one(
            AgentDocument.agent_id == agent.id
        )
        
        if not mongo_agent:
            mongo_agent = AgentDocument.from_domain(agent)
            await mongo_agent.save()
            return
        
        # Update fields from agent domain model
        mongo_agent.update_from_domain(agent)
        await mongo_agent.save()

    async def find_by_id(self, agent_id: str) -> Optional[Agent]:
        """Find an agent by its ID"""
        mongo_agent = await AgentDocument.find_one(
            AgentDocument.agent_id == agent_id
        )
        return mongo_agent.to_domain() if mongo_agent else None

    async def add_memory(self, agent_id: str,
                          name: str,
                          memory: Memory) -> None:
        """Add or update a memory for an agent"""
        result = await AgentDocument.find_one(
            AgentDocument.agent_id == agent_id
        ).update(
            {"$set": {f"memories.{name}": memory, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Agent {agent_id} not found")

    async def get_memory(self, agent_id: str, name: str) -> Memory:
        """Get memory by name from agent, create if not exists"""
        mongo_agent = await AgentDocument.find_one(
            AgentDocument.agent_id == agent_id
        )
        if not mongo_agent:
            raise ValueError(f"Agent {agent_id} not found")
        return mongo_agent.memories.get(name, Memory(messages=[]))
    
    async def save_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        """Update the messages of a memory.

        Never lets a persistence failure kill the running agent task:
        a memory document that exceeds MongoDB's 16MB BSON cap (observed with
        huge tool payloads, e.g. base64 images) is first aggressively compacted
        and retried once; if it still does not fit, the in-memory state is kept
        and the error is logged — the task continues instead of crashing.
        """
        try:
            await self._do_save_memory(agent_id, name, memory)
        except Exception as e:
            if "too large" in str(e).lower():
                logger.warning(
                    f"Memory '{name}' of agent {agent_id} too large for MongoDB "
                    f"({e}) — compacting aggressively and retrying once"
                )
                try:
                    memory.compact()
                    # Extra safety: truncate any remaining oversized tool payloads
                    for message in memory.messages:
                        if message.type == "tool":
                            content = getattr(message, "content", None)
                            if isinstance(content, str) and len(content) > 100_000:
                                message.content = content[:100_000] + "…[truncated]"
                    await self._do_save_memory(agent_id, name, memory)
                    logger.info(
                        f"Memory '{name}' of agent {agent_id} saved after compaction"
                    )
                    return
                except Exception as retry_err:
                    logger.error(
                        f"Could not persist memory '{name}' of agent {agent_id} "
                        f"even after compaction: {retry_err} — continuing without "
                        f"persistence (task keeps running)"
                    )
                    return
            raise

    async def _do_save_memory(self, agent_id: str, name: str, memory: Memory) -> None:
        result = await AgentDocument.find_one(
            AgentDocument.agent_id == agent_id
        ).update(
            {"$set": {f"memories.{name}": memory, "updated_at": datetime.now(UTC)}}
        )
        if not result:
            raise ValueError(f"Agent {agent_id} not found")
