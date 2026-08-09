import pytest
from langchain_core.messages import AIMessage

from app.domain.models.message import Message
from app.domain.services.agents.planner import PlannerAgent


class FakeStreamingModel:
    def __init__(self, response: str):
        self.response = response
        self.messages = None

    async def astream(self, messages):
        self.messages = messages
        yield AIMessage(content=self.response)


async def collect_events(agent: PlannerAgent, message: Message):
    return [event async for event in agent.acknowledge(message)]


def make_test_agent(response: str) -> PlannerAgent:
    agent = PlannerAgent.__new__(PlannerAgent)
    agent._model = FakeStreamingModel(response)

    async def no_previous_files():
        return []

    agent._get_previous_file_names = no_previous_files
    return agent


@pytest.mark.asyncio
async def test_acknowledgement_does_not_leak_planner_json():
    agent = make_test_agent(
        '{"message":"Saya akan mengerjakannya.","steps":[{"id":"1","description":"Buat folder"}]}'
    )

    events = await collect_events(agent, Message(message="Buat website"))

    assert [event.type for event in events] == ["message_chunk", "message_chunk", "message"]
    assert events[0].content == "Saya akan mengerjakannya."
    assert events[2].message == "Saya akan mengerjakannya."
    assert "{" not in events[0].content
    assert "steps" not in events[0].content
    assert agent._model.messages is not None
    assert len(agent._model.messages) == 2
    assert "JSON" in agent._model.messages[0].content
    assert "Return plain text only" in agent._model.messages[1].content
    assert "Do not return JSON" in agent._model.messages[1].content


@pytest.mark.asyncio
async def test_acknowledgement_emits_clean_plain_text_only():
    agent = make_test_agent("Baik, saya akan membantu membuatnya.")

    events = await collect_events(agent, Message(message="Buat website"))

    assert [event.type for event in events] == ["message_chunk", "message_chunk", "message"]
    assert events[0].content == "Baik, saya akan membantu membuatnya."
    assert events[1].done is True
    assert events[2].message == "Baik, saya akan membantu membuatnya."