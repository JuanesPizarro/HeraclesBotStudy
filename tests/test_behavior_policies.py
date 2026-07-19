from datetime import date

import bot.handlers.web_api as web_api
from bot.agent.contracts import Intent
from bot.agent.intent import classify_intent_text
from bot.agent.policies import allowed_tools_for_intent


def test_tool_permissions_match_policy_table():
    assert allowed_tools_for_intent(Intent.TODAY_PLAN) == []
    assert allowed_tools_for_intent(Intent.ROUTINE) == []
    assert allowed_tools_for_intent(Intent.HISTORY) == []
    assert allowed_tools_for_intent(Intent.LOG_WORKOUT) == ["save_workout"]
    assert allowed_tools_for_intent(Intent.MODIFY_SESSION) == [
        "create_session_override_draft"
    ]
    assert allowed_tools_for_intent(Intent.CREATE_ROUTINE) == ["create_routine_draft"]
    assert allowed_tools_for_intent(Intent.EVALUATE_SESSION) == []
    assert allowed_tools_for_intent(Intent.UPDATE_PROFILE) == [
        "create_profile_change_draft"
    ]
    assert allowed_tools_for_intent(Intent.LIMITATION) == [
        "create_session_override_draft"
    ]
    assert allowed_tools_for_intent(Intent.OUT_OF_SCOPE) == []


def test_pain_reports_are_limitation_intent():
    assert (
        classify_intent_text("Me duele la rodilla al hacer sentadillas")
        == Intent.LIMITATION
    )


def test_session_override_draft_does_not_affect_active_overrides(store, active_user):
    store.create_session_override_draft(
        active_user,
        target_date="2026-07-20",
        scope="day",
        modification="Cambiar sentadilla por movilidad",
        reason="dolor",
    )

    assert store.get_active_overrides(active_user) == []


def test_confirmed_session_override_becomes_active(store, active_user):
    draft_id = store.create_session_override_draft(
        active_user,
        target_date="2026-07-20",
        scope="day",
        modification="Cambiar sentadilla por movilidad",
        reason="dolor",
    )

    store.confirm_session_override_draft(active_user, draft_id)

    assert len(store.get_active_overrides(active_user)) == 1


def test_profile_change_draft_requires_confirmation(store, active_user):
    draft_id = store.create_profile_change_draft(
        active_user,
        field="goal",
        new_value="perder grasa",
        reason="nuevo ciclo",
    )

    assert store.get_user(active_user)["goal"] == "ganar fuerza y masa muscular"
    store.confirm_profile_change_draft(active_user, draft_id)
    assert store.get_user(active_user)["goal"] == "perder grasa"


def test_pain_note_blocks_automatic_progression(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes")
    store.save_routine(
        active_user,
        "DÍA 1 (Lunes)\n• Sentadilla: 3x8-10 @ 40 kg\n",
    )
    today_sets = [
        {
            "exercise": "Sentadilla",
            "sets": 1,
            "reps": 10,
            "weight_kg": 40,
            "rpe": 7,
            "notes": "molestia leve en rodilla",
        },
        {
            "exercise": "Sentadilla",
            "sets": 1,
            "reps": 10,
            "weight_kg": 40,
            "rpe": 7,
            "notes": "",
        },
        {
            "exercise": "Sentadilla",
            "sets": 1,
            "reps": 10,
            "weight_kg": 40,
            "rpe": 7,
            "notes": "",
        },
    ]

    suggestions = web_api._calculate_deterministic_suggestions(
        store.get_user(active_user),
        today_sets,
        date(2026, 7, 20),
    )

    assert suggestions[0]["reason"] == "consolidate"
    assert suggestions[0]["next_weight"] == 40.0
    assert suggestions[0]["basis"] == "Molestia reportada -> no progresar"
