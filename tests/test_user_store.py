def test_upsert_user_does_not_duplicate_rows(store):
    assert store.upsert_user("u1", "Uno") is True
    assert store.upsert_user("u1", "Uno cambiado") is False

    with store._get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE telegram_id = 'u1'"
        ).fetchone()[0]
        row = conn.execute("SELECT name FROM users WHERE telegram_id = 'u1'").fetchone()

    assert count == 1
    assert row["name"] == "Uno"


def test_upsert_user_creates_internal_identity(store):
    store.upsert_user("telegram-1", "Uno")

    user = store.get_user("telegram-1")
    internal_id = store.get_internal_user_id("telegram", "telegram-1")

    assert user["id"]
    assert internal_id == user["id"]


def test_save_routine_deactivates_previous_active_routine(store, active_user):
    first_id = store.save_routine(active_user, "rutina uno")
    second_id = store.save_routine(active_user, "rutina dos")

    assert first_id != second_id
    assert store.get_active_routine(active_user)["routine_text"] == "rutina dos"

    with store._get_conn() as conn:
        active_count = conn.execute(
            "SELECT COUNT(*) FROM routines WHERE user_id = ? AND is_active = 1",
            (active_user,),
        ).fetchone()[0]

    assert active_count == 1


def test_save_workout_preserves_rpe_and_notes(store, active_user):
    workout_id = store.save_workout(
        active_user,
        "Press banca",
        sets=1,
        reps=8,
        weight_kg=42.5,
        rpe=8,
        notes="ultima repeticion lenta",
    )

    with store._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM workouts WHERE id = ?", (workout_id,)
        ).fetchone()

    assert row["rpe"] == 8
    assert row["notes"] == "ultima repeticion lenta"


def test_progression_target_replaces_only_matching_exercise(store, active_user):
    store.save_progression_target(
        active_user, "Press banca", 40, "base", "2026-07-18", "8-10", 3
    )
    store.save_progression_target(
        active_user, "Press militar", 25, "base", "2026-07-18", "6-8", 3
    )
    store.save_progression_target(
        active_user, "Press banca", 42.5, "sube", "2026-07-19", "8-10", 4
    )

    banca = store.get_progression_target(active_user, "Press banca")
    militar = store.get_progression_target(active_user, "Press militar")

    assert banca["next_weight"] == 42.5
    assert banca["next_sets"] == 4
    assert militar["next_weight"] == 25
    assert militar["next_sets"] == 3
