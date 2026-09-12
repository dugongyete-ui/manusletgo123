from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import Optional
import uuid


class ScheduledTask(BaseModel):
    """A recurring agent run the user asked for.

    The scheduler wakes up periodically, finds tasks whose ``next_run_at``
    is due, and feeds the prompt back into the session exactly like the user
    pressing send themselves — the agent then runs autonomously and the
    result lands in the session (unread counter bumps so the user notices).

    Manus equivalent: scheduleTask — "agent jalan otomatis tanpa kamu".
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str
    # Prompt fed to the agent on every run.
    prompt: str
    # Session the runs happen in. None is not allowed after creation — the
    # task always owns a concrete session (created together with the task).
    session_id: str
    # Minutes between runs (minimum 5 to protect the provider quota).
    interval_minutes: int = 1440
    next_run_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
