from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.domain.models.scheduled_task import ScheduledTask


class CreateScheduledTaskRequest(BaseModel):
    """Create a recurring agent run.

    Either attach it to an existing session (continue that conversation) or
    omit session_id to let the server create a fresh session for the runs.
    """
    prompt: str = Field(min_length=2, max_length=4000)
    session_id: Optional[str] = None
    # Minutes between runs; minimum 5 to protect the provider quota.
    interval_minutes: int = Field(default=1440, ge=5, le=60 * 24 * 30)


class ScheduledTaskResponse(BaseModel):
    task_id: str
    session_id: str
    prompt: str
    interval_minutes: int
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    is_active: bool = True
    created_at: Optional[datetime] = None

    @staticmethod
    def from_domain(task: ScheduledTask) -> "ScheduledTaskResponse":
        return ScheduledTaskResponse(
            task_id=task.id,
            session_id=task.session_id,
            prompt=task.prompt,
            interval_minutes=task.interval_minutes,
            next_run_at=task.next_run_at,
            last_run_at=task.last_run_at,
            run_count=task.run_count,
            is_active=task.is_active,
            created_at=task.created_at,
        )


class ListScheduledTaskResponse(BaseModel):
    tasks: List[ScheduledTaskResponse]


class CreateScheduledTaskResponse(BaseModel):
    task_id: str
    session_id: str


class ToggleScheduledTaskRequest(BaseModel):
    is_active: bool
