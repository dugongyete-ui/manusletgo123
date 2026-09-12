from typing import Optional, List
from datetime import datetime, UTC
from app.domain.models.scheduled_task import ScheduledTask
from app.infrastructure.models.documents import ScheduledTaskDocument
import logging

logger = logging.getLogger(__name__)


class MongoScheduledTaskRepository:
    """MongoDB implementation of ScheduledTaskRepository."""

    async def save(self, task: ScheduledTask) -> None:
        doc = await ScheduledTaskDocument.find_one(
            ScheduledTaskDocument.task_id == task.id
        )
        if not doc:
            doc = ScheduledTaskDocument.from_domain(task)
            await doc.save()
            return
        doc.update_from_domain(task)
        await doc.save()

    async def find_by_id_and_user_id(self, task_id: str, user_id: str) -> Optional[ScheduledTask]:
        doc = await ScheduledTaskDocument.find_one(
            ScheduledTaskDocument.task_id == task_id,
            ScheduledTaskDocument.user_id == user_id,
        )
        return doc.to_domain() if doc else None

    async def find_by_user_id(self, user_id: str) -> List[ScheduledTask]:
        docs = (
            await ScheduledTaskDocument.find(
                ScheduledTaskDocument.user_id == user_id,
            )
            .sort([("is_active", -1), ("next_run_at", 1)])
            .to_list()
        )
        return [d.to_domain() for d in docs]

    async def find_due(self, now: datetime, limit: int = 10) -> List[ScheduledTask]:
        docs = (
            await ScheduledTaskDocument.find(
                ScheduledTaskDocument.is_active == True,  # noqa: E712 — Beanie needs the field query
                {"next_run_at": {"$lte": now}},
            )
            .sort([("next_run_at", 1)])
            .limit(limit)
            .to_list()
        )
        return [d.to_domain() for d in docs]

    async def update_run(self, task_id: str, last_run_at: datetime, next_run_at: datetime) -> None:
        await ScheduledTaskDocument.find_one(
            ScheduledTaskDocument.task_id == task_id
        ).update(
            {
                "$set": {
                    "last_run_at": last_run_at,
                    "next_run_at": next_run_at,
                    "updated_at": datetime.now(UTC),
                },
                "$inc": {"run_count": 1},
            }
        )

    async def set_active(self, task_id: str, user_id: str, is_active: bool) -> None:
        await ScheduledTaskDocument.find_one(
            ScheduledTaskDocument.task_id == task_id,
            ScheduledTaskDocument.user_id == user_id,
        ).update(
            {"$set": {"is_active": is_active, "updated_at": datetime.now(UTC)}}
        )

    async def delete(self, task_id: str, user_id: str) -> None:
        doc = await ScheduledTaskDocument.find_one(
            ScheduledTaskDocument.task_id == task_id,
            ScheduledTaskDocument.user_id == user_id,
        )
        if doc:
            await doc.delete()
