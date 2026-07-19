from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BlockType(str, Enum):
    STRAIGHT_SETS = "straight_sets"
    CIRCUIT = "circuit"


class RoutineExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=100)
    order: int = Field(ge=1)
    sets: int = Field(ge=1, le=8)
    reps_min: int = Field(ge=1, le=100)
    reps_max: int = Field(ge=1, le=100)
    rest_seconds: int = Field(ge=0, le=600)
    initial_weight: float = Field(ge=0, le=500)

    @model_validator(mode="after")
    def validate_reps(self):
        if self.reps_min > self.reps_max:
            raise ValueError("reps_min cannot exceed reps_max")
        return self


class RoutineBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: BlockType
    order: int = Field(ge=1)
    rounds: int | None = Field(default=None, ge=1, le=10)
    exercises: list[RoutineExercise] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_block(self):
        if self.type == BlockType.CIRCUIT and self.rounds is None:
            raise ValueError("circuit blocks require rounds")
        if self.type == BlockType.STRAIGHT_SETS and self.rounds is not None:
            raise ValueError("straight set blocks cannot define rounds")
        return self


class RoutineDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: str
    order: int = Field(ge=1, le=7)
    blocks: list[RoutineBlock] = Field(min_length=1)

    @field_validator("weekday")
    @classmethod
    def normalize_weekday(cls, value: str) -> str:
        weekday = value.strip().lower()
        valid = {
            "lunes",
            "martes",
            "miércoles",
            "jueves",
            "viernes",
            "sábado",
            "domingo",
        }
        if weekday not in valid:
            raise ValueError("weekday must be a Spanish weekday")
        return weekday


class RoutineDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    days: list[RoutineDay] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_days_and_exercises(self):
        weekdays = [day.weekday for day in self.days]
        if len(weekdays) != len(set(weekdays)):
            raise ValueError("routine days cannot be duplicated")

        for day in self.days:
            names = [
                exercise.exercise_id.strip().lower()
                for block in day.blocks
                for exercise in block.exercises
            ]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicated exercise in {day.weekday}")
        return self
