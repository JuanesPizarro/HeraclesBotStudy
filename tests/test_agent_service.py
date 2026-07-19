from langchain_core.messages import AIMessage

import pytest

from bot.agent.contracts import AgentResponse
from bot.services import agent_service


class FakeGraph:
    async def ainvoke(self, input, config):
        return {"messages": [AIMessage(content="respuesta neutral")]}


class FakeResponseGraph:
    async def ainvoke(self, input, config):
        return {"response": AgentResponse(message="respuesta estructurada")}


@pytest.mark.asyncio
async def test_run_agent_message_returns_neutral_response(monkeypatch):
    monkeypatch.setattr(agent_service, "agent_graph", FakeGraph())

    response = await agent_service.run_agent_message("user-1", "hola", "api")

    assert response.message == "respuesta neutral"
    assert response.actions == []


@pytest.mark.asyncio
async def test_run_agent_message_preserves_structured_response(monkeypatch):
    monkeypatch.setattr(agent_service, "agent_graph", FakeResponseGraph())

    response = await agent_service.run_agent_message("user-1", "plan de hoy", "api")

    assert response.message == "respuesta estructurada"
