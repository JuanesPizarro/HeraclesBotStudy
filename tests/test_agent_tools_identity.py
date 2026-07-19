import pytest

import bot.agent.tools as tools
from bot.agent.runtime import AgentRuntimeContext, current_agent_context


def _tool_schema(tool):
    return tool.args_schema.model_json_schema()


def test_tool_schemas_do_not_expose_user_id():
    for agent_tool in tools.TOOLS:
        schema = _tool_schema(agent_tool)
        assert "user_id" not in schema.get("properties", {})
        assert "user_id" not in schema.get("required", [])


def test_profile_change_draft_uses_runtime_user_context(monkeypatch, store):
    store.upsert_user("user-a", "A")
    store.upsert_user("user-b", "B")
    monkeypatch.setattr(tools, "_store", store)

    token = current_agent_context.set(
        AgentRuntimeContext(user_id="user-a", channel="telegram")
    )
    try:
        tools.create_profile_change_draft.invoke(
            {
                "field": "goal",
                "new_value": "ganar fuerza",
                "reason": "nuevo objetivo",
            }
        )
    finally:
        current_agent_context.reset(token)

    assert store.get_user("user-a")["goal"] == "ganar fuerza y masa muscular"
    assert store.get_user("user-b")["goal"] == "ganar fuerza y masa muscular"
    with store._get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, field, new_value FROM profile_change_drafts"
        ).fetchall()
    assert [dict(row) for row in rows] == [
        {"user_id": "user-a", "field": "goal", "new_value": "ganar fuerza"}
    ]


def test_tool_without_runtime_context_fails_before_writing(monkeypatch, store):
    store.upsert_user("user-a", "A")
    monkeypatch.setattr(tools, "_store", store)

    with pytest.raises(RuntimeError, match="Agent runtime context is missing"):
        tools.create_profile_change_draft.invoke(
            {"field": "goal", "new_value": "perder grasa"}
        )

    assert store.get_user("user-a")["goal"] == "ganar fuerza y masa muscular"
