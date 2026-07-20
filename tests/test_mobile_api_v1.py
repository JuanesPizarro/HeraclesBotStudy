import datetime
import asyncio

import pytest
from fastapi import HTTPException

import bot.handlers.web_api as web_api
from bot.handlers import mobile_api


def _auth(token: str) -> dict:
    return f"Bearer {token}"


def _all_days_routine() -> str:
    days = [
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
        "Domingo",
    ]
    return "\n".join(
        f"DÍA {idx} ({day})\n• Press banca: 3x8-10 @ 40 kg\n"
        for idx, day in enumerate(days, start=1)
    )


def test_mobile_v1_requires_bearer_token():
    with pytest.raises(HTTPException) as exc:
        mobile_api.get_mobile_user(None)
    assert exc.value.status_code == 401


def test_mobile_v1_me_uses_authenticated_user(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(active_user, "lunes,miércoles")
    token = store.get_or_create_web_token(active_user)

    user = mobile_api.get_mobile_user(_auth(token))
    response = asyncio.run(mobile_api.get_me(user))

    assert response.name == "Test User"
    assert response.training_days == ["lunes", "miércoles"]


def test_mobile_v1_plan_includes_session_id(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    store.update_training_days(
        active_user,
        "lunes,martes,miércoles,jueves,viernes,sábado,domingo",
    )
    store.save_routine(active_user, _all_days_routine())
    token = store.get_or_create_web_token(active_user)

    user = mobile_api.get_mobile_user(_auth(token))
    body = asyncio.run(mobile_api.get_session_plan(user))

    assert body["is_rest_day"] is False
    assert body["session_id"]
    assert body["exercises"][0]["name"] == "Press banca"


def test_mobile_v1_logs_set_for_owned_session(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    today = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(0))
    ).date().isoformat()
    store.update_training_days(
        active_user,
        "lunes,martes,miércoles,jueves,viernes,sábado,domingo",
    )
    routine_id = store.save_routine(active_user, _all_days_routine())
    session = store.get_or_create_training_session(active_user, today, routine_id)
    token = store.get_or_create_web_token(active_user)

    user = mobile_api.get_mobile_user(_auth(token))
    response = asyncio.run(
        mobile_api.log_session_set(
            mobile_api.SessionSetPayload(
                session_id=session["id"],
                exercise="Press banca",
                reps=10,
                weight_kg=40,
                rpe=8,
                notes="",
            ),
            user,
        )
    )

    assert response["session_id"] == session["id"]
    assert store.get_training_session(session["id"])["user_id"] == active_user


def test_mobile_v1_rejects_noncanonical_exercise(monkeypatch, store, active_user):
    monkeypatch.setattr(web_api, "_store", store)
    today = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(0))
    ).date().isoformat()
    store.update_training_days(
        active_user,
        "lunes,martes,miércoles,jueves,viernes,sábado,domingo",
    )
    routine_id = store.save_routine(active_user, _all_days_routine())
    session = store.get_or_create_training_session(active_user, today, routine_id)
    token = store.get_or_create_web_token(active_user)

    user = mobile_api.get_mobile_user(_auth(token))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            mobile_api.log_session_set(
                mobile_api.SessionSetPayload(
                    session_id=session["id"],
                    exercise="Press de banca",
                    reps=10,
                    weight_kg=40,
                ),
                user,
            )
        )

    assert exc.value.status_code == 400
