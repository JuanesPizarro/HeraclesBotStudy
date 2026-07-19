from decimal import Decimal

from bot.domain.progression import (
    CompletedSet,
    Prescription,
    ProgressionAction,
    calculate_progression,
)


def prescription(**overrides):
    values = {
        "exercise_id": "Press banca",
        "weight": Decimal("40"),
        "sets": 3,
        "reps_min": 8,
        "reps_max": 10,
        "max_sets": 4,
        "weight_increment": Decimal("2.5"),
    }
    values.update(overrides)
    return Prescription(**values)


def completed(*reps, weight=Decimal("40"), rpe=8):
    return [CompletedSet(reps=n, weight=weight, rpe=rpe) for n in reps]


def test_progression_insufficient_without_completed_sets():
    result = calculate_progression(prescription(), [])

    assert result.action == ProgressionAction.INSUFFICIENT_DATA
    assert result.next_weight == Decimal("40")
    assert result.next_sets == 3


def test_progression_insufficient_when_missing_prescribed_sets():
    result = calculate_progression(prescription(), completed(10, 10))

    assert result.action == ProgressionAction.INSUFFICIENT_DATA


def test_progression_consolidates_when_below_minimum_reps():
    result = calculate_progression(prescription(), completed(10, 8, 7))

    assert result.action == ProgressionAction.CONSOLIDATE
    assert result.next_weight == Decimal("40")
    assert result.next_sets == 3


def test_progression_consolidates_when_rpe_is_high():
    result = calculate_progression(prescription(), completed(10, 10, 10, rpe=9))

    assert result.action == ProgressionAction.CONSOLIDATE
    assert result.next_weight == Decimal("40")


def test_progression_builds_reps_before_sets_or_weight():
    result = calculate_progression(prescription(), completed(10, 9, 8))

    assert result.action == ProgressionAction.BUILD_REPS
    assert result.next_weight == Decimal("40")
    assert result.next_sets == 3
    assert result.next_reps_min == 8
    assert result.next_reps_max == 10


def test_progression_adds_set_after_reaching_rep_ceiling():
    result = calculate_progression(prescription(), completed(10, 10, 10))

    assert result.action == ProgressionAction.ADD_SET
    assert result.next_weight == Decimal("40")
    assert result.next_sets == 4


def test_progression_adds_weight_after_max_sets_at_rep_ceiling():
    result = calculate_progression(
        prescription(sets=4, max_sets=4),
        completed(10, 10, 10, 10),
    )

    assert result.action == ProgressionAction.ADD_WEIGHT
    assert result.next_weight == Decimal("42.5")
    assert result.next_sets == 4
    assert result.next_reps_min == 8
    assert result.next_reps_max == 8


def test_progression_does_not_add_weight_to_bodyweight_exercise():
    result = calculate_progression(
        prescription(
            exercise_id="Flexiones",
            weight=Decimal("0"),
            sets=4,
            max_sets=4,
        ),
        completed(10, 10, 10, 10, weight=Decimal("0")),
    )

    assert result.action == ProgressionAction.CONSOLIDATE
    assert result.next_weight == Decimal("0")
