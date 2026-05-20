import logging
from typing import Optional

from app.domain.external.claw import ClawInstanceInfo

logger = logging.getLogger(__name__)


class DockerClawRuntime:
    """Stub: Claw via Docker is disabled. Use CLAW_ADDRESS for a fixed instance."""

    creates_immediately = False

    async def create(self, claw_id: str, api_key: str) -> ClawInstanceInfo:
        raise RuntimeError(
            "DockerClawRuntime is disabled. Set CLAW_ADDRESS to use a fixed Claw instance, "
            "or set CLAW_ENABLED=false to disable the Claw feature entirely."
        )

    async def destroy(self, instance_name: Optional[str]) -> None:
        pass

    async def wait_for_ready(self, base_url: str) -> bool:
        return False
