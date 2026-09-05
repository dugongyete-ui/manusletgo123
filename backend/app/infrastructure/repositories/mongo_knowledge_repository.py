from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.infrastructure.models.documents import KnowledgeDocument
import logging

logger = logging.getLogger(__name__)


class MongoKnowledgeRepository:
    """MongoDB implementation of KnowledgeRepository."""

    async def save(self, item: KnowledgeItem) -> None:
        doc = await KnowledgeDocument.find_one(
            KnowledgeDocument.knowledge_id == item.id
        )
        if not doc:
            doc = KnowledgeDocument.from_domain(item)
            await doc.save()
            return
        doc.update_from_domain(item)
        await doc.save()

    async def find_active_by_user_id(self, user_id: str, limit: int = 200) -> List[KnowledgeItem]:
        docs = (
            await KnowledgeDocument.find(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.status == KnowledgeStatus.ACTIVE.value,
            )
            .sort([("updated_at", -1)])
            .limit(limit)
            .to_list()
        )
        return [d.to_domain() for d in docs]

    async def find_all_by_user_id(self, user_id: str) -> List[KnowledgeItem]:
        docs = (
            await KnowledgeDocument.find(
                KnowledgeDocument.user_id == user_id,
            )
            .sort([("status", 1), ("updated_at", -1)])
            .to_list()
        )
        return [d.to_domain() for d in docs]

    async def find_by_id_and_user_id(self, item_id: str, user_id: str) -> Optional[KnowledgeItem]:
        doc = await KnowledgeDocument.find_one(
            KnowledgeDocument.knowledge_id == item_id,
            KnowledgeDocument.user_id == user_id,
        )
        return doc.to_domain() if doc else None

    async def update_status(self, item_id: str, user_id: str, status: KnowledgeStatus) -> None:
        await KnowledgeDocument.find_one(
            KnowledgeDocument.knowledge_id == item_id,
            KnowledgeDocument.user_id == user_id,
        ).update(
            {"$set": {"status": status.value, "updated_at": datetime.now(UTC)}}
        )

    async def delete(self, item_id: str, user_id: str) -> None:
        doc = await KnowledgeDocument.find_one(
            KnowledgeDocument.knowledge_id == item_id,
            KnowledgeDocument.user_id == user_id,
        )
        if doc:
            await doc.delete()
