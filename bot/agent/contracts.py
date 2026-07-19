from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Intent(str, Enum):
    TODAY_PLAN = "today_plan"
    ROUTINE = "routine"
    LOG_WORKOUT = "log_workout"
    MODIFY_SESSION = "modify_session"
    CREATE_ROUTINE = "create_routine"
    EVALUATE_SESSION = "evaluate_session"
    UPDATE_PROFILE = "update_profile"
    HISTORY = "history"
    LIMITATION = "limitation"
    OUT_OF_SCOPE = "out_of_scope"


class ProgressionReason(str, Enum):
    BUILD_REPS = "build_reps"
    ADD_SET = "add_set"
    ADD_WEIGHT = "add_weight"
    REDUCE_WEIGHT = "reduce_weight"
    REDUCE_SETS = "reduce_sets"
    CONSOLIDATE = "consolidate"
    INSUFFICIENT_DATA = "insufficient_data"


class ProgressionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=100)
    next_weight: float = Field(ge=0, le=500)
    next_sets: int = Field(ge=1, le=8)
    next_reps_min: int = Field(ge=1, le=100)
    next_reps_max: int = Field(ge=1, le=100)
    reason: ProgressionReason
    basis: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def validate_rep_range(self):
        if self.next_reps_min > self.next_reps_max:
            raise ValueError("next_reps_min cannot exceed next_reps_max")
        return self


class SessionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    decisions: list[ProgressionDecision]


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    actions: list[dict] = Field(default_factory=list)
    requires_confirmation: bool = False
