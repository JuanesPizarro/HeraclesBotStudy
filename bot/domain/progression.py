from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ProgressionAction(str, Enum):
    BUILD_REPS = "build_reps"
    ADD_SET = "add_set"
    ADD_WEIGHT = "add_weight"
    CONSOLIDATE = "consolidate"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class Prescription:
    exercise_id: str
    weight: Decimal
    sets: int
    reps_min: int
    reps_max: int
    max_sets: int
    weight_increment: Decimal


@dataclass(frozen=True)
class CompletedSet:
    reps: int
    weight: Decimal
    rpe: int | None


@dataclass(frozen=True)
class ProgressionResult:
    exercise_id: str
    next_weight: Decimal
    next_sets: int
    next_reps_min: int
    next_reps_max: int
    action: ProgressionAction


def calculate_progression(
    prescription: Prescription,
    completed_sets: list[CompletedSet],
) -> ProgressionResult:
    """
    Calcula la próxima prescripción con doble progresión.

    La función no interpreta dolor, molestias ni contexto conversacional. Esos
    casos deben resolverse fuera del flujo automático.
    """
    base = ProgressionResult(
        exercise_id=prescription.exercise_id,
        next_weight=prescription.weight,
        next_sets=prescription.sets,
        next_reps_min=prescription.reps_min,
        next_reps_max=prescription.reps_max,
        action=ProgressionAction.CONSOLIDATE,
    )

    if not _has_valid_prescription(prescription) or not completed_sets:
        return ProgressionResult(
            **{**base.__dict__, "action": ProgressionAction.INSUFFICIENT_DATA}
        )

    relevant_sets = completed_sets[: prescription.sets]
    if len(relevant_sets) < prescription.sets:
        return ProgressionResult(
            **{**base.__dict__, "action": ProgressionAction.INSUFFICIENT_DATA}
        )

    if any(s.reps < prescription.reps_min for s in relevant_sets):
        return base

    if any(s.rpe is not None and s.rpe >= 9 for s in relevant_sets):
        return base

    if not all(s.reps >= prescription.reps_max for s in relevant_sets):
        return ProgressionResult(
            **{**base.__dict__, "action": ProgressionAction.BUILD_REPS}
        )

    if prescription.sets < prescription.max_sets:
        return ProgressionResult(
            **{
                **base.__dict__,
                "next_sets": prescription.sets + 1,
                "action": ProgressionAction.ADD_SET,
            }
        )

    if prescription.weight == 0:
        return base

    return ProgressionResult(
        **{
            **base.__dict__,
            "next_weight": prescription.weight + prescription.weight_increment,
            "next_reps_min": prescription.reps_min,
            "next_reps_max": prescription.reps_min,
            "action": ProgressionAction.ADD_WEIGHT,
        }
    )


def _has_valid_prescription(prescription: Prescription) -> bool:
    return (
        bool(prescription.exercise_id.strip())
        and prescription.weight >= 0
        and prescription.sets >= 1
        and prescription.reps_min >= 1
        and prescription.reps_max >= prescription.reps_min
        and prescription.max_sets >= prescription.sets
        and prescription.weight_increment > 0
    )
