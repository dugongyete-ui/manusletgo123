from fastapi import APIRouter, Depends
from app.application.errors.exceptions import NotFoundError
from app.domain.models.agent_profile import AgentProfile
from app.domain.models.user import User
from app.interfaces.dependencies import (
    get_agent_profile_repository,
    get_current_user,
)
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.agent_profile import (
    AgentProfileResponse,
    CreateAgentProfileRequest,
    CreateAgentProfileResponse,
    ListAgentProfileResponse,
)
from app.domain.repositories.agent_profile_repository import AgentProfileRepository

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-profiles", tags=["agent-profiles"])


@router.get("", response_model=APIResponse[ListAgentProfileResponse])
async def list_agent_profiles(
    current_user: User = Depends(get_current_user),
    repository: AgentProfileRepository = Depends(get_agent_profile_repository),
) -> APIResponse[ListAgentProfileResponse]:
    from app.domain.models.agent_profile import BUILTIN_PROFILES
    custom = await repository.find_by_user_id(current_user.id)
    profiles = list(BUILTIN_PROFILES) + custom
    return APIResponse.success(ListAgentProfileResponse(
        profiles=[AgentProfileResponse.from_domain(p) for p in profiles]
    ))


@router.post("", response_model=APIResponse[CreateAgentProfileResponse])
async def create_agent_profile(
    request: CreateAgentProfileRequest,
    current_user: User = Depends(get_current_user),
    repository: AgentProfileRepository = Depends(get_agent_profile_repository),
) -> APIResponse[CreateAgentProfileResponse]:
    profile = AgentProfile(
        user_id=current_user.id,
        name=request.name.strip(),
        description=(request.description or "").strip() or None,
        emoji=(request.emoji or "").strip() or None,
        instruction=request.instruction.strip(),
        is_builtin=False,
    )
    await repository.save(profile)
    logger.info("User %s created agent profile %s", current_user.id, profile.id)
    return APIResponse.success(CreateAgentProfileResponse(profile_id=profile.id))


@router.delete("/{profile_id}", response_model=APIResponse[None])
async def delete_agent_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    repository: AgentProfileRepository = Depends(get_agent_profile_repository),
) -> APIResponse[None]:
    profile = await repository.find_by_id_and_user_id(profile_id, current_user.id)
    if not profile:
        raise NotFoundError("Agent profile not found")
    await repository.delete(profile_id, current_user.id)
    return APIResponse.success()
