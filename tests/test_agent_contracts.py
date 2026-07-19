import pytest
from pydantic import ValidationError

from bot.agent.contracts import ProgressionDecision, SessionEvaluation


def test_session_evaluation_rejects_extra_fields():
    with pytest.raises(ValidationError):
        SessionEvaluation.model_validate(
            {
                "summary": "Buen trabajo.",
                "decisions": [],
                "extra": "not allowed",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"next_weight": -1, "next_sets": 3, "next_reps_min": 8, "next_reps_max": 10},
        {"next_weight": 20, "next_sets": 0, "next_reps_min": 8, "next_reps_max": 10},
        {"next_weight": 20, "next_sets": 3, "next_reps_min": 12, "next_reps_max": 8},
    ],
)
def test_progression_decision_rejects_invalid_values(payload):
    payload.update(
        {
            "exercise_id": "Press banca",
            "reason": "build_reps",
        }
    )

    with pytest.raises(ValidationError):
        ProgressionDecision.model_validate(payload)


def test_progression_decision_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ProgressionDecision.model_validate(
            {
                "exercise_id": "Press banca",
                "next_weight": 40,
                "next_sets": 3,
                "next_reps_min": 8,
                "next_reps_max": 10,
                "reason": "build_reps",
                "unexpected": True,
            }
        )
