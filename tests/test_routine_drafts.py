from bot.domain.routines import RoutineDraft
from bot.handlers.web_api import _build_session_plan_payload, _routine_draft_to_text


def structured_routine() -> RoutineDraft:
    return RoutineDraft.model_validate(
        {
            "name": "Rutina estructurada",
            "days": [
                {
                    "weekday": "lunes",
                    "order": 1,
                    "blocks": [
                        {
                            "type": "straight_sets",
                            "order": 1,
                            "exercises": [
                                {
                                    "exercise_id": "Press banca",
                                    "order": 1,
                                    "sets": 3,
                                    "reps_min": 8,
                                    "reps_max": 10,
                                    "rest_seconds": 120,
                                    "initial_weight": 40,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_creating_routine_draft_does_not_replace_active_routine(store, active_user):
    active_id = store.save_routine(active_user, "DÍA 1 (Lunes)\n• Remo: 3x10")
    draft = structured_routine()

    draft_id = store.create_routine_draft(
        active_user,
        _routine_draft_to_text(draft),
        draft.model_dump_json(),
    )

    assert draft_id != active_id
    assert store.get_active_routine(active_user)["id"] == active_id
    assert store.get_routine(active_user, draft_id)["status"] == "draft"


def test_confirming_routine_draft_archives_previous_active_routine(store, active_user):
    active_id = store.save_routine(active_user, "DÍA 1 (Lunes)\n• Remo: 3x10")
    draft = structured_routine()
    draft_id = store.create_routine_draft(
        active_user,
        _routine_draft_to_text(draft),
        draft.model_dump_json(),
    )

    store.confirm_routine_draft(active_user, draft_id)

    assert store.get_active_routine(active_user)["id"] == draft_id
    assert store.get_routine(active_user, active_id)["status"] == "archived"


def test_canceling_routine_draft_keeps_active_routine(store, active_user):
    active_id = store.save_routine(active_user, "DÍA 1 (Lunes)\n• Remo: 3x10")
    draft_id = store.create_routine_draft(active_user, "otra rutina")

    store.cancel_routine_draft(active_user, draft_id)

    assert store.get_active_routine(active_user)["id"] == active_id
    assert store.get_routine(active_user, draft_id)["status"] == "archived"


def test_structured_routine_can_render_plan_without_text_parser(
    monkeypatch, store, active_user
):
    import bot.handlers.web_api as web_api

    monkeypatch.setattr(web_api, "_store", store)
    draft = structured_routine()
    draft_id = store.create_routine_draft(
        active_user,
        "texto que no contiene bullets parseables",
        draft.model_dump_json(),
    )
    store.confirm_routine_draft(active_user, draft_id)
    store.update_training_days(active_user, "lunes")

    plan = _build_session_plan_payload(
        store.get_user(active_user), today=__import__("datetime").date(2026, 7, 20)
    )

    assert plan["is_rest_day"] is False
    assert plan["exercises"][0]["name"] == "Press banca"
    assert plan["exercises"][0]["target_sets"] == 3
