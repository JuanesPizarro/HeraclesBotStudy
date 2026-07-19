from langchain_core.messages import HumanMessage

import bot.agent.nodes as nodes
from bot.agent.contracts import Intent
from bot.agent.intent import allowed_tools_for_intent, classify_intent_text
from bot.agent.prompts import BASE_PROMPT_FILES, build_system_prompt, load_prompt


def test_today_plan_intent_exposes_no_write_tools():
    intent = classify_intent_text("¿Qué me corresponde hoy?")

    assert intent == Intent.TODAY_PLAN
    assert allowed_tools_for_intent(intent) == []


def test_current_routine_intent_exposes_no_write_tools():
    intent = classify_intent_text("¿Cuál es mi rutina?")

    assert intent == Intent.ROUTINE
    assert allowed_tools_for_intent(intent) == []


def test_base_prompt_has_no_telegram_formatting_or_urls():
    base = "\n".join(load_prompt(name) for name in BASE_PROMPT_FILES).lower()

    assert "telegram" not in base
    assert "http://" not in base
    assert "https://" not in base
    assert "tablas" not in base


def test_build_system_prompt_is_channel_neutral():
    prompt = build_system_prompt(
        {
            "today": "2026-07-20 (Lunes)",
            "today_date": "2026-07-20",
            "session_today": "Press banca",
            "today_done": "Nada registrado",
            "webapp_url": "https://example.invalid/app?token=secret",
            "profile": "Atleta",
            "routine": "Rutina",
            "overrides": "Sin cambios",
            "recent_workouts": "Sin historial",
        }
    ).lower()

    assert "telegram" not in prompt
    assert "https://example.invalid" not in prompt


def test_direct_today_plan_response_uses_context_without_tools(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "_build_context",
        lambda user_id: {
            "session_today": "Hoy corresponde empuje.",
            "recent_workouts": "Sin historial",
        },
    )
    state = {
        "messages": [HumanMessage(content="¿Qué me corresponde hoy?")],
        "user_id": "user-1",
        "channel": "telegram",
        "intent": Intent.TODAY_PLAN,
    }

    result = nodes.direct_response_node(state)

    assert result["messages"][-1].content == "Hoy corresponde empuje."
    assert result["response"].message == "Hoy corresponde empuje."


def test_direct_routine_response_uses_active_routine_context(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "_build_context",
        lambda user_id: {
            "session_today": "Hoy corresponde empuje.",
            "routine": "Rutina activa completa",
            "recent_workouts": "Sin historial",
        },
    )
    state = {
        "messages": [HumanMessage(content="muéstrame mi rutina")],
        "user_id": "user-1",
        "channel": "telegram",
        "intent": Intent.ROUTINE,
    }

    result = nodes.direct_response_node(state)

    assert result["messages"][-1].content == "Rutina activa completa"
