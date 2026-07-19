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


def test_update_training_days_uses_runtime_user_context(monkeypatch, store):
    store.upsert_user("user-a", "A")
    store.upsert_user("user-b", "B")
    monkeypatch.setattr(tools, "_store", store)

    token = current_agent_context.set(
        AgentRuntimeContext(user_id="user-a", channel="telegram")
    )
    try:
        result = tools.update_training_days.invoke(
            {
                "training_days": "domingo,lunes,miercoles,jueves,viernes",
                "reason": "cambio confirmado",
            }
        )
    finally:
        current_agent_context.reset(token)

    assert "domingo,lunes,miércoles,jueves,viernes" in result
    assert store.get_user("user-a")["training_days"] == (
        "domingo,lunes,miércoles,jueves,viernes"
    )
    assert store.get_user("user-b")["training_days"] is None


def test_update_training_schedule_relabels_active_routine_without_draft(
    monkeypatch, store
):
    store.upsert_user("user-a", "A")
    store.save_routine(
        "user-a",
        "DÍA 1 (Lunes) - Upper\n"
        "• Press banca: 3x8-10 @ 40 kg\n"
        "DÍA 2 (Martes) - Lower\n"
        "• Sentadilla: 3x8-10 @ 40 kg\n",
    )
    monkeypatch.setattr(tools, "_store", store)
    updated = (
        "DÍA 1 (Domingo) - Upper\n"
        "• Press banca: 3x8-10 @ 40 kg\n"
        "DÍA 2 (Lunes) - Lower\n"
        "• Sentadilla: 3x8-10 @ 40 kg\n"
    )

    token = current_agent_context.set(
        AgentRuntimeContext(user_id="user-a", channel="telegram")
    )
    try:
        result = tools.update_training_schedule.invoke(
            {
                "routine_text": updated,
                "training_days": "domingo,lunes",
                "reason": "cambio confirmado",
            }
        )
    finally:
        current_agent_context.reset(token)

    assert "domingo,lunes" in result
    assert store.get_user("user-a")["training_days"] == "domingo,lunes"
    assert store.get_active_routine("user-a")["routine_text"] == updated


def test_update_training_schedule_rejects_exercise_changes(monkeypatch, store):
    store.upsert_user("user-a", "A")
    store.save_routine(
        "user-a",
        "DÍA 1 (Lunes) - Upper\n"
        "• Press banca: 3x8-10 @ 40 kg\n",
    )
    monkeypatch.setattr(tools, "_store", store)

    token = current_agent_context.set(
        AgentRuntimeContext(user_id="user-a", channel="telegram")
    )
    try:
        with pytest.raises(ValueError, match="cannot add or remove exercises"):
            tools.update_training_schedule.invoke(
                {
                    "routine_text": "DÍA 1 (Domingo) - Upper\n• Remo: 3x10\n",
                    "training_days": "domingo",
                }
            )
    finally:
        current_agent_context.reset(token)


def test_confirm_session_override_draft_uses_runtime_user_context(monkeypatch, store):
    store.upsert_user("user-a", "A")
    store.upsert_user("user-b", "B")
    draft_a = store.create_session_override_draft(
        "user-a",
        target_date="2026-07-20",
        scope="day",
        modification="• Movilidad de cadera: 2x10",
        reason="molestia puntual",
    )
    draft_b = store.create_session_override_draft(
        "user-b",
        target_date="2026-07-20",
        scope="day",
        modification="• Caminata suave: 1x20 min",
        reason="fatiga",
    )
    monkeypatch.setattr(tools, "_store", store)

    token = current_agent_context.set(
        AgentRuntimeContext(user_id="user-a", channel="telegram")
    )
    try:
        result = tools.confirm_session_override_draft.invoke({"override_id": draft_a})
    finally:
        current_agent_context.reset(token)

    assert f"Modificación temporal {draft_a} confirmada" in result
    with store._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, status FROM session_overrides ORDER BY id"
        ).fetchall()
    assert [dict(row) for row in rows] == [
        {"id": draft_a, "user_id": "user-a", "status": "active"},
        {"id": draft_b, "user_id": "user-b", "status": "draft"},
    ]


def test_tool_without_runtime_context_fails_before_writing(monkeypatch, store):
    store.upsert_user("user-a", "A")
    monkeypatch.setattr(tools, "_store", store)

    with pytest.raises(RuntimeError, match="Agent runtime context is missing"):
        tools.create_profile_change_draft.invoke(
            {"field": "goal", "new_value": "perder grasa"}
        )

    assert store.get_user("user-a")["goal"] == "ganar fuerza y masa muscular"
