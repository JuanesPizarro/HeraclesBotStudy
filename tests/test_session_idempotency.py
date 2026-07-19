import asyncio
import json

import pytest

import bot.handlers.web_api as web_api


def test_training_session_returns_cached_evaluation(store, active_user):
    session = store.get_or_create_training_session(active_user, "2026-07-20", None)
    payload = {"suggestions": [{"exercise": "Press banca"}], "evaluation": "ok"}

    store.complete_session_evaluation(
        session["id"],
        json.dumps(payload, ensure_ascii=False),
    )

    cached = store.get_training_session(session["id"])

    assert cached["status"] == "evaluated"
    assert json.loads(cached["evaluation_json"]) == payload


def test_finish_training_session_is_idempotent(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    monkeypatch.setattr(web_api.settings, "DEEPSEEK_API_KEY", "")
    session = store.get_or_create_training_session(active_user, "2026-07-20", None)
    store.save_workout(
        active_user, "Press banca", 3, 10, 40, rpe=8, session_id=session["id"]
    )

    user = store.get_user(active_user)
    first = asyncio.run(web_api._finish_training_session(user, session["id"], "key-1"))
    second = asyncio.run(web_api._finish_training_session(user, session["id"], "key-1"))

    assert first["session_id"] == session["id"]
    assert second["session_id"] == session["id"]
    assert second["idempotent"] is True
    assert second["suggestions"] == first["suggestions"]


def test_training_session_cannot_be_claimed_twice_before_evaluation(store, active_user):
    session = store.get_or_create_training_session(active_user, "2026-07-20", None)

    store.begin_session_evaluation(session["id"], "key-1")

    with pytest.raises(ValueError, match="already in progress"):
        store.begin_session_evaluation(session["id"], "key-1")
