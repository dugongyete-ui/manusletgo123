from fastapi import APIRouter, Depends
from datetime import datetime, UTC, timedelta
from app.application.errors.exceptions import NotFoundError
from app.domain.models.scheduled_task import ScheduledTask
from app.domain.models.user import User
from app.interfaces.dependencies import (
    get_agent_service,
    get_current_user,
    get_scheduled_task_repository,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.scheduled_task import (
    CreateScheduledTaskRequest,
    CreateScheduledTaskResponse,
    ListScheduledTaskResponse,
    ScheduledTaskResponse,
    ToggleScheduledTaskRequest,
)
from app.domain.repositories.scheduled_task_repository import ScheduledTaskRepository
from app.application.services.agent_service import AgentService

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduled-tasks", tags=["scheduled-tasks"])


@router.post("", response_model=APIResponse[CreateScheduledTaskResponse])
async def create_scheduled_task(
    request: CreateScheduledTaskRequest,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(get_agent_service),
    repository: ScheduledTaskRepository = Depends(get_scheduled_task_repository),
) -> APIResponse[CreateScheduledTaskResponse]:
    # Own session, or create a fresh one for the recurring runs.
    session_id = request.session_id
    if session_id:
        session = await agent_service.get_session(session_id, current_user.id)
        if not session:
            raise NotFoundError("Session not found")
    else:
        session = await agent_service.create_session(current_user.id)
        session_id = session.id

    task = ScheduledTask(
        user_id=current_user.id,
        prompt=request.prompt.strip(),
        session_id=session_id,
        interval_minutes=request.interval_minutes,
        next_run_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    await repository.save(task)
    logger.info(
        "User %s scheduled task %s (session %s, every %d min)",
        current_user.id, task.id, session_id, request.interval_minutes,
    )
    return APIResponse.success(CreateScheduledTaskResponse(
        task_id=task.id, session_id=session_id
    ))


@router.get("", response_model=APIResponse[ListScheduledTaskResponse])
async def list_scheduled_tasks(
    current_user: User = Depends(get_current_user),
    repository: ScheduledTaskRepository = Depends(get_scheduled_task_repository),
) -> APIResponse[ListScheduledTaskResponse]:
    tasks = await repository.find_by_user_id(current_user.id)
    return APIResponse.success(ListScheduledTaskResponse(
        tasks=[ScheduledTaskResponse.from_domain(t) for t in tasks]
    ))


@router.patch("/{task_id}", response_model=APIResponse[None])
async def toggle_scheduled_task(
    task_id: str,
    request: ToggleScheduledTaskRequest,
    current_user: User = Depends(get_current_user),
    repository: ScheduledTaskRepository = Depends(get_scheduled_task_repository),
) -> APIResponse[None]:
    task = await repository.find_by_id_and_user_id(task_id, current_user.id)
    if not task:
        raise NotFoundError("Scheduled task not found")
    await repository.set_active(task_id, current_user.id, request.is_active)
    logger.info("User %s toggled task %s → %s", current_user.id, task_id, request.is_active)
    return APIResponse.success()


@router.delete("/{task_id}", response_model=APIResponse[None])
async def delete_scheduled_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    repository: ScheduledTaskRepository = Depends(get_scheduled_task_repository),
) -> APIResponse[None]:
    task = await repository.find_by_id_and_user_id(task_id, current_user.id)
    if not task:
        raise NotFoundError("Scheduled task not found")
    await repository.delete(task_id, current_user.id)
    return APIResponse.success()
