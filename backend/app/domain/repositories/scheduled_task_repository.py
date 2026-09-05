from typing import Optional, Protocol, List
from datetime import datetime
from app.domain.models.scheduled_task import ScheduledTask


class ScheduledTaskRepository(Protocol):
    """Repository interface for recurring scheduled agent runs."""

    async def save(self, task: ScheduledTask) -> None:
        ...

    async def find_by_id_and_user_id(self, task_id: str, user_id: str) -> Optional[ScheduledTask]:
        ...

    async def find_by_user_id(self, user_id: str) -> List[ScheduledTask]:
        ...

    async def find_due(self, now: datetime, limit: int = 10) -> List[ScheduledTask]:
        ...

    async def update_run(self, task_id: str, last_run_at: datetime, next_run_at: datetime) -> None:
        ...

    async def set_active(self, task_id: str, user_id: str, is_active: bool) -> None:
        ...

    async def delete(self, task_id: str, user_id: str) -> None:
        ...
