from fastapi import APIRouter, Depends
from app.application.errors.exceptions import NotFoundError
from app.domain.models.knowledge import KnowledgeItem, KnowledgeKind, KnowledgeStatus
from app.domain.models.user import User
from app.interfaces.dependencies import get_current_user, get_knowledge_repository
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.knowledge import (
    AddKnowledgeRequest,
    AddKnowledgeResponse,
    KnowledgeItemResponse,
    ListKnowledgeResponse,
    UpdateKnowledgeStatusRequest,
    UpdateKnowledgeStatusResponse,
)
from app.domain.repositories.knowledge_repository import KnowledgeRepository

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("", response_model=APIResponse[ListKnowledgeResponse])
async def list_knowledge(
    current_user: User = Depends(get_current_user),
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> APIResponse[ListKnowledgeResponse]:
    items = await knowledge_repository.find_all_by_user_id(current_user.id)
    return APIResponse.success(ListKnowledgeResponse(
        items=[
            KnowledgeItemResponse(
                knowledge_id=i.id,
                content=i.content,
                kind=i.kind.value if hasattr(i.kind, "value") else str(i.kind),
                status=i.status,
                source_session_id=i.source_session_id,
                created_at=i.created_at,
                updated_at=i.updated_at,
            )
            for i in items
        ]
    ))


@router.post("", response_model=APIResponse[AddKnowledgeResponse])
async def add_knowledge(
    request: AddKnowledgeRequest,
    current_user: User = Depends(get_current_user),
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> APIResponse[AddKnowledgeResponse]:
    item = KnowledgeItem(
        user_id=current_user.id,
        content=request.content.strip(),
        kind=KnowledgeKind.USER,
        status=KnowledgeStatus.ACTIVE,
    )
    await knowledge_repository.save(item)
    logger.info("User %s added knowledge %s", current_user.id, item.id)
    return APIResponse.success(AddKnowledgeResponse(knowledge_id=item.id))


@router.patch("/{knowledge_id}", response_model=APIResponse[UpdateKnowledgeStatusResponse])
async def update_knowledge_status(
    knowledge_id: str,
    request: UpdateKnowledgeStatusRequest,
    current_user: User = Depends(get_current_user),
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> APIResponse[UpdateKnowledgeStatusResponse]:
    item = await knowledge_repository.find_by_id_and_user_id(
        knowledge_id, current_user.id
    )
    if not item:
        raise NotFoundError("Knowledge item not found")
    await knowledge_repository.update_status(
        knowledge_id, current_user.id, request.status
    )
    logger.info(
        "User %s set knowledge %s → %s",
        current_user.id, knowledge_id, request.status,
    )
    return APIResponse.success(UpdateKnowledgeStatusResponse(
        knowledge_id=knowledge_id, status=request.status
    ))


@router.delete("/{knowledge_id}", response_model=APIResponse[None])
async def delete_knowledge(
    knowledge_id: str,
    current_user: User = Depends(get_current_user),
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> APIResponse[None]:
    item = await knowledge_repository.find_by_id_and_user_id(
        knowledge_id, current_user.id
    )
    if not item:
        raise NotFoundError("Knowledge item not found")
    await knowledge_repository.delete(knowledge_id, current_user.id)
    return APIResponse.success()
