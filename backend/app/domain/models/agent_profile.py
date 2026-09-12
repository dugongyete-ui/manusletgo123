from pydantic import BaseModel, Field
from datetime import datetime, UTC
from typing import Optional
import uuid


class AgentProfile(BaseModel):
    """A user-customisable agent preset (Manus InitManusAgent equivalent).

    The profile's ``instruction`` is appended to the system prompt of every
    session created with it, so users can shape tone, focus and conventions
    without editing prompts. Built-in profiles are resolved from code (never
    stored per user); custom profiles live in Mongo.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    user_id: str
    name: str
    description: Optional[str] = None
    # Short emoji/character shown in the picker.
    emoji: Optional[str] = None
    # Natural-language persona appended to the system prompt.
    instruction: str = ""
    is_builtin: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# Built-in profiles available to every user. ids are namespaced so they can
# never collide with Mongo-generated hex ids.
BUILTIN_PROFILES: list[AgentProfile] = [
    AgentProfile(
        id="builtin-general",
        user_id="",
        name="Dzeck",
        emoji="✦",
        description="Serbaguna — penelitian, analisis, dan pembuatan file.",
        instruction=(
            "Approach every task with balanced depth: research enough to be "
            "accurate, build carefully, and explain results clearly."
        ),
        is_builtin=True,
    ),
    AgentProfile(
        id="builtin-engineer",
        user_id="",
        name="Engineer",
        emoji="⚙",
        description="Fokus engineering: aplikasi, API, dan kode berkualitas.",
        instruction=(
            "You are an experienced software engineer. Prefer working, "
            "verified code over lengthy prose: build, run, and test before "
            "reporting. Surface trade-offs only when they change the decision."
        ),
        is_builtin=True,
    ),
    AgentProfile(
        id="builtin-researcher",
        user_id="",
        name="Researcher",
        emoji="🔎",
        description="Fokus riset: sumber banyak, verifikasi, dan sitasi.",
        instruction=(
            "You are a meticulous researcher. Cross-check claims across "
            "independent sources, note publication dates, and distinguish "
            "established facts from speculation. Prefer primary sources."
        ),
        is_builtin=True,
    ),
]
BUILTIN_PROFILE_IDS = {p.id for p in BUILTIN_PROFILES}


def resolve_builtin_profile(profile_id: str) -> Optional[AgentProfile]:
    for profile in BUILTIN_PROFILES:
        if profile.id == profile_id:
            return profile
    return None
