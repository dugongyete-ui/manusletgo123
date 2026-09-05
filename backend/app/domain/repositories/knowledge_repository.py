from typing import Optional, Protocol, List
from app.domain.models.knowledge import KnowledgeItem, KnowledgeStatus


class KnowledgeRepository(Protocol):
    """Repository interface for per-user knowledge items."""

    async def save(self, item: KnowledgeItem) -> None:
        ...

    async def find_active_by_user_id(self, user_id: str, limit: int = 200) -> List[KnowledgeItem]:
        ...

    async def find_all_by_user_id(self, user_id: str) -> List[KnowledgeItem]:
        ...

    async def find_by_id_and_user_id(self, item_id: str, user_id: str) -> Optional[KnowledgeItem]:
        ...

    async def update_status(self, item_id: str, user_id: str, status: KnowledgeStatus) -> None:
        ...

    async def delete(self, item_id: str, user_id: str) -> None:
        ...
