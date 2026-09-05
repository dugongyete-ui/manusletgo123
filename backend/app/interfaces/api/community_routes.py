from fastapi import APIRouter, Depends
from typing import Optional
from app.interfaces.dependencies import get_agent_service
from app.interfaces.schemas.base import APIResponse
from app.interfaces.schemas.session import ListSessionItem, ListSessionResponse
from app.application.services.agent_service import AgentService

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/community", tags=["community"])


@router.get("/sessions", response_model=APIResponse[ListSessionResponse])
async def list_community_sessions(
    limit: Optional[int] = 50,
    agent_service: AgentService = Depends(get_agent_service),
) -> APIResponse[ListSessionResponse]:
    """Public gallery of shared sessions (no auth — discovery only).

    Opening a session goes through the existing share routes, which only
    serve sessions the owner explicitly shared.
    """
    summaries = await agent_service.get_community_sessions(limit=max(1, min(limit, 100)))
    return APIResponse.success(ListSessionResponse(
        sessions=[
            ListSessionItem(
                session_id=s.id,
                title=s.title,
                latest_message=s.latest_message,
                latest_message_at=(
                    int(s.latest_message_at.timestamp()) if s.latest_message_at else None
                ),
                status=s.status,
                unread_message_count=s.unread_message_count,
                is_shared=True,
                project_id=s.project_id,
            )
            for s in summaries
        ]
    ))
