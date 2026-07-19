import json
from datetime import date

import pytest

import bot.handlers.web_api as web_api
from bot.handlers.web_api import (
    _calculate_deterministic_suggestions,
    _parse_session_evaluation,
)


TODAY_SETS = [
    {"exercise": "Press banca", "reps": 10, "weight_kg": 40, "rpe": 8},
    {"exercise": "Remo mancuerna", "reps": 12, "weight_kg": 20, "rpe": 8},
]


def test_parse_session_evaluation_accepts_contract_payload():
    raw = json.dumps(
        {
            "summary": "Buen cierre de sesión.",
            "decisions": [
                {
                    "exercise_id": "Press banca",
                    "next_weight": 42.5,
                    "next_sets": 3,
                    "next_reps_min": 8,
                    "next_reps_max": 10,
                    "reason": "add_weight",
                    "basis": "techo completo",
                }
            ],
        }
    )

    summary, suggestions = _parse_session_evaluation(raw, TODAY_SETS)

    assert summary == "Buen cierre de sesión."
    assert suggestions == [
        {
            "exercise": "Press banca",
            "next_weight": 42.5,
            "next_reps": "8-10",
            "next_sets": 3,
            "reason": "add_weight",
            "basis": "techo completo",
        }
    ]


def test_parse_session_evaluation_rejects_unknown_exercise():
    raw = json.dumps(
        {
            "summary": "Buen cierre de sesión.",
            "decisions": [
                {
                    "exercise_id": "Curl inventado",
                    "next_weight": 10,
                    "next_sets": 3,
                    "next_reps_min": 8,
                    "next_reps_max": 10,
                    "reason": "build_reps",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="Unknown exercise"):
        _parse_session_evaluation(raw, TODAY_SETS)


def test_parse_session_evaluation_rejects_duplicate_exercise():
    raw = json.dumps(
        {
            "summary": "Buen cierre de sesión.",
            "decisions": [
                {
                    "exercise_id": "Press banca",
                    "next_weight": 40,
                    "next_sets": 3,
                    "next_reps_min": 8,
                    "next_reps_max": 10,
                    "reason": "build_reps",
                },
                {
                    "exercise_id": "Press banca",
                    "next_weight": 42.5,
                    "next_sets": 3,
                    "next_reps_min": 8,
                    "next_reps_max": 10,
                    "reason": "add_weight",
                },
            ],
        }
    )

    with pytest.raises(ValueError, match="Duplicate progression"):
        _parse_session_evaluation(raw, TODAY_SETS)


def test_parse_session_evaluation_rejects_unavailable_weight_increment():
    raw = json.dumps(
        {
            "summary": "Buen cierre de sesión.",
            "decisions": [
                {
                    "exercise_id": "Press banca",
                    "next_weight": 42.25,
                    "next_sets": 3,
                    "next_reps_min": 8,
                    "next_reps_max": 10,
                    "reason": "add_weight",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="0.5 kg increments"):
        _parse_session_evaluation(raw, TODAY_SETS)


def test_deterministic_suggestions_use_today_plan(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes")
    store.save_routine(
        active_user,
        "DÍA 1 (Lunes)\n• Press banca: 3x8-10 @ 40 kg\n",
    )
    user = store.get_user(active_user)
    today_sets = [
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
    ]

    suggestions = _calculate_deterministic_suggestions(
        user, today_sets, date(2026, 7, 20)
    )

    assert suggestions == [
        {
            "exercise": "Press banca",
            "next_weight": 40.0,
            "next_reps": "8-10",
            "next_sets": 4,
            "reason": "add_set",
            "basis": "Techo completo -> +1 serie",
        }
    ]


def test_deterministic_suggestions_are_repeatable(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes")
    store.save_routine(
        active_user,
        "DÍA 1 (Lunes)\n• Press banca: 4x8-10 @ 40 kg\n",
    )
    user = store.get_user(active_user)
    today_sets = [
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
    ]

    first = _calculate_deterministic_suggestions(user, today_sets, date(2026, 7, 20))
    second = _calculate_deterministic_suggestions(user, today_sets, date(2026, 7, 20))

    assert first == second
    assert first[0]["next_weight"] == 42.5
    assert first[0]["reason"] == "add_weight"


def test_agent_guardrails_accept_safe_weight_reduction(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes")
    store.save_routine(
        active_user,
        "DÍA 1 (Lunes)\n• Press banca: 3x8-10 @ 40 kg\n",
    )
    user = store.get_user(active_user)
    today_sets = [
        {"exercise": "Press banca", "sets": 1, "reps": 8, "weight_kg": 40, "rpe": 9},
        {"exercise": "Press banca", "sets": 1, "reps": 7, "weight_kg": 40, "rpe": 10},
        {"exercise": "Press banca", "sets": 1, "reps": 6, "weight_kg": 40, "rpe": 10},
    ]
    fallback = _calculate_deterministic_suggestions(user, today_sets, date(2026, 7, 20))
    agent_suggestions = [
        {
            "exercise": "Press banca",
            "next_weight": 35.0,
            "next_reps": "8-10",
            "next_sets": 3,
            "reason": "reduce_weight",
            "basis": "RPE alto y reps caen",
        }
    ]

    suggestions = web_api._apply_agent_guardrails(
        user, today_sets, date(2026, 7, 20), agent_suggestions, fallback
    )

    assert suggestions == agent_suggestions


def test_agent_guardrails_fallback_when_weight_jump_is_unsafe(
    monkeypatch, store, active_user
):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes")
    store.save_routine(
        active_user,
        "DÍA 1 (Lunes)\n• Press banca: 3x8-10 @ 40 kg\n",
    )
    user = store.get_user(active_user)
    today_sets = [
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
        {"exercise": "Press banca", "sets": 1, "reps": 10, "weight_kg": 40, "rpe": 8},
    ]
    fallback = _calculate_deterministic_suggestions(user, today_sets, date(2026, 7, 20))
    agent_suggestions = [
        {
            "exercise": "Press banca",
            "next_weight": 50.0,
            "next_reps": "8-10",
            "next_sets": 3,
            "reason": "add_weight",
            "basis": "salto demasiado agresivo",
        }
    ]

    suggestions = web_api._apply_agent_guardrails(
        user, today_sets, date(2026, 7, 20), agent_suggestions, fallback
    )

    assert suggestions == fallback
