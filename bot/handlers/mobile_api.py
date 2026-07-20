import datetime
import zoneinfo
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from bot.config import settings
from bot.handlers import web_api
from bot.services.agent_service import run_agent_message


router = APIRouter(prefix="/api/v1", tags=["mobile-v1"])


def get_mobile_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer requerido")
    token = authorization.split(" ", 1)[1].strip()
    user = web_api._store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return user


class MeResponse(BaseModel):
    id: str | None
    name: str
    goal: str
    training_days: list[str]
    session_minutes: int
    equipment: str | None = None
    experience_level: str | None = None


class SessionSetPayload(BaseModel):
    session_id: str = Field(min_length=1)
    exercise: str = Field(min_length=1)
    reps: int = Field(ge=1)
    weight_kg: float = Field(default=0.0, ge=0)
    rpe: Optional[int] = Field(default=None, ge=6, le=10)
    notes: Optional[str] = None


class AgentMessagePayload(BaseModel):
    message: str = Field(min_length=1)


@router.get("/me", response_model=MeResponse)
async def get_me(user: dict = Depends(get_mobile_user)) -> MeResponse:
    training_days = [
        item.strip()
        for item in (user.get("training_days") or "").split(",")
        if item.strip()
    ]
    return MeResponse(
        id=user.get("id"),
        name=user.get("name", "Atleta"),
        goal=user.get("goal", ""),
        training_days=training_days,
        session_minutes=user.get("session_time_minutes") or 60,
        equipment=user.get("equipment"),
        experience_level=user.get("experience_level"),
    )


@router.get("/session/plan")
async def get_session_plan(user: dict = Depends(get_mobile_user)) -> dict:
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    plan = web_api._build_session_plan_payload(user, today=today)
    plan["date"] = today.isoformat()
    plan.setdefault("exercises", [])

    if not plan.get("is_rest_day"):
        routine = web_api._store.get_active_routine(user["telegram_id"])
        session = web_api._store.get_or_create_training_session(
            user["telegram_id"],
            today.isoformat(),
            routine["id"] if routine else None,
        )
        plan["session_id"] = session["id"]

    return plan


@router.get("/session/today")
async def get_today_session(user: dict = Depends(get_mobile_user)) -> dict:
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    return {
        "date": today.isoformat(),
        "sets": web_api._store.get_today_workouts(user["telegram_id"]),
    }


@router.post("/session/sets")
async def log_session_set(
    payload: SessionSetPayload,
    user: dict = Depends(get_mobile_user),
) -> dict:
    session = web_api._store.get_training_session(payload.session_id)
    if not session or session["user_id"] != user["telegram_id"]:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    plan = web_api._build_session_plan_payload(
        user, today=datetime.date.fromisoformat(session["scheduled_date"])
    )
    allowed_exercises = {item["name"] for item in plan.get("exercises", [])}
    if payload.exercise not in allowed_exercises:
        raise HTTPException(status_code=400, detail="Ejercicio fuera del plan de hoy")

    workout_id = web_api._store.save_workout(
        user_id=user["telegram_id"],
        exercise=payload.exercise,
        sets=1,
        reps=payload.reps,
        weight_kg=payload.weight_kg,
        rpe=payload.rpe,
        notes=payload.notes,
        session_id=payload.session_id,
    )
    return {
        "id": workout_id,
        "session_id": payload.session_id,
        "exercise": payload.exercise,
        "sets": 1,
        "reps": payload.reps,
        "weight_kg": payload.weight_kg,
        "rpe": payload.rpe,
        "notes": payload.notes,
    }


@router.post("/sessions/{session_id}/finish")
async def finish_session(
    session_id: str,
    user: dict = Depends(get_mobile_user),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    return await web_api._finish_training_session(user, session_id, idempotency_key)


@router.post("/agent/messages")
async def agent_message(
    payload: AgentMessagePayload,
    user: dict = Depends(get_mobile_user),
) -> dict:
    response = await run_agent_message(
        user_id=user["telegram_id"],
        message=payload.message,
        channel="mobile",
    )
    return response.model_dump(mode="json")
