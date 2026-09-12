"""Contract tests for the post-task knowledge loop (auto-accept, silent).

Product decision (user request): the "Pelajaran dari task ini" accept/reject
card must NEVER appear in the chat. The runner still distils learnings
after a real task — but saves them directly as ACTIVE knowledge (auto
-accepted, rides along in future sessions) and emits NO KnowledgeEvent.
A per-item save error skips that item silently (reject-on-error).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.models.knowledge import KnowledgeKind, KnowledgeStatus


class _FakeRepo:
    def __init__(self):
        self.saved = []

    async def save(self, item):
        if item.content == "FORCE SAVE ERROR":
            raise RuntimeError("db down")
        self.saved.append(item)


class _FakeStep:
    def __init__(self):
        self.description = "do work"
        self.status = MagicMock(value="completed")
        self.result = "ok"
        self.error = ""


class _FakePlan:
    def __init__(self):
        self.steps = [_FakeStep()]


class _FakeMemory:
    def get_messages(self):
        msgs = []
        for role in ("human", "ai", "ai"):
            m = MagicMock()
            m.type = role
            m.content = f"{role} content"
            msgs.append(m)
        return msgs


class _FakeExecutor:
    memory = _FakeMemory()


class _FakeFlow:
    plan = _FakePlan()
    executor = _FakeExecutor()


def _make_runner(repo):
    from app.domain.services.agent_task_runner import AgentTaskRunner

    runner = AgentTaskRunner.__new__(AgentTaskRunner)
    runner._knowledge_repository = repo
    runner._flow = _FakeFlow()
    runner._user_id = "user-1"
    runner._session_id = "sess-1"
    # The knowledge event emission must NEVER happen now — track it.
    runner._put_and_add_event = AsyncMock()
    return runner


@pytest.mark.asyncio
async def test_learnings_auto_accepted_silent(monkeypatch):
    """Learnings are saved ACTIVE (auto-accept) and NO KnowledgeEvent is
    emitted — the chat never shows the accept/reject card."""
    repo = _FakeRepo()
    runner = _make_runner(repo)

    async def fake_propose(digest, user_message):
        return ["User prefers Indonesian replies.", "Deliver zips, never loose folders."]

    monkeypatch.setattr(
        "app.domain.services.agents.knowledge_learner.propose_learnings",
        fake_propose,
    )

    await runner._propose_learnings(task=MagicMock(), user_message="buatkan aplikasi")

    assert len(repo.saved) == 2
    for item in repo.saved:
        assert item.status == KnowledgeStatus.ACTIVE
        assert item.kind == KnowledgeKind.LEARNING
        assert item.user_id == "user-1"
        assert item.source_session_id == "sess-1"
    # The card contract: zero events emitted into the chat.
    runner._put_and_add_event.assert_not_called()


@pytest.mark.asyncio
async def test_learning_save_error_skips_item_silently(monkeypatch):
    """A failing save skips just that item (reject-on-error) — no raise, no
    chat event; the healthy items still land."""
    repo = _FakeRepo()
    runner = _make_runner(repo)

    async def fake_propose(digest, user_message):
        return ["FORCE SAVE ERROR", "Healthy lesson."]

    monkeypatch.setattr(
        "app.domain.services.agents.knowledge_learner.propose_learnings",
        fake_propose,
    )

    await runner._propose_learnings(task=MagicMock(), user_message="task")

    assert [i.content for i in repo.saved] == ["Healthy lesson."]
    assert repo.saved[0].status == KnowledgeStatus.ACTIVE
    runner._put_and_add_event.assert_not_called()


@pytest.mark.asyncio
async def test_no_repo_or_empty_plan_means_noop():
    """No repository / no plan → nothing happens at all (never raises)."""
    runner = _make_runner(None)
    await runner._propose_learnings(task=MagicMock(), user_message="x")  # no repo

    runner2 = _make_runner(_FakeRepo())
    runner2._flow.plan.steps = []
    await runner2._propose_learnings(task=MagicMock(), user_message="x")
