"""
Router FastAPI para la app web de registro de entrenamientos.

[CONCEPTO: Separación de responsabilidades — routers en FastAPI]
Cada router maneja una "área de negocio" independiente.
Este router maneja la interfaz web pública (con Cloudflare Tunnel):
- Servir el HTML de la SPA
- API JSON autenticada por web_token para que Alpine.js consulte/guarde datos

La app web comparte el mismo SQLite que el bot de Telegram —
un único source of truth para todos los canales de entrada.
"""

import datetime
import json
import os
import re
import zoneinfo
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Header
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from bot.agent.contracts import (
    ProgressionDecision,
    ProgressionReason,
    SessionEvaluation,
)
from bot.agent.policies import text_reports_pain
from bot.domain.progression import (
    CompletedSet,
    Prescription,
    ProgressionAction,
    ProgressionResult,
    calculate_progression,
)
from bot.domain.routines import BlockType, RoutineDraft
from bot.services.agent_service import run_agent_message
from bot.storage.user_store import UserStore
from bot.agent.nodes import apply_progression_to_routine_text
from bot.config import settings

# =====================================================================
# [CONCEPTO: Dependency Injection en FastAPI]
# FastAPI permite declarar "dependencias" que se ejecutan antes del handler.
# Aquí usamos Depends(get_current_user) para validar el web_token en
# cada endpoint protegido, sin repetir el código de validación.
#
# Patrón equivalente a middleware pero más granular:
# Solo los endpoints que declaran la dependencia la ejecutan.
# =====================================================================

router = APIRouter(tags=["web"])
_store = UserStore()

_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _suggest_rest(reps_min: int, reps_max: int) -> int:
    """
    Calcula el tiempo de descanso sugerido según el rango de repeticiones.

    [CONCEPTO: Fisiología del descanso entre series]
    El tiempo de recuperación óptimo depende del sistema energético:
    • 1-5 reps (fuerza máxima)  → 3 min (sistema fosfágeno, alta demanda neural)
    • 6-8 reps (fuerza/hipertrofia) → 2.5 min
    • 8-12 reps (hipertrofia)   → 2 min (glucolítico, recuperación parcial)
    • 12-20 reps (resistencia)  → 90 seg
    • 20+ reps (circuito/core)  → 60 seg
    """
    avg = (reps_min + reps_max) / 2
    if avg <= 5:
        return 180
    elif avg <= 8:
        return 150
    elif avg <= 12:
        return 120
    elif avg <= 20:
        return 90
    return 60


def _parse_session_exercises(section_text: str) -> list[dict]:
    """
    Parsea las líneas de una sección de rutina en objetos estructurados.

    [CONCEPTO: Parsing de formatos mixtos con estado]
    La rutina puede mezclar dos formatos en el mismo día:

    Formato normal:
      • Sentadilla goblet: 3x10-12 — Sujeta una mancuerna
      → target_sets=3, is_circuit=False

    Formato circuito:
      • Circuito (3 rondas, descanso 60s entre rondas):
        • Zancadas: 10 por pierna
        • Plancha: 30 segundos
      → target_sets=3 (rondas), is_circuit=True, circuit_position=0/1

    El parser usa una máquina de estados: normal vs. dentro_de_circuito.
    Los sub-ítems del circuito tienen 2 espacios de sangría.
    """
    exercises: list[dict] = []
    in_circuit = False
    circuit_rounds = 0
    circuit_rest = 0
    circuit_items: list[dict] = []

    def _flush_circuit() -> None:
        nonlocal in_circuit, circuit_items
        if not circuit_items:
            return
        size = len(circuit_items)
        for pos, item in enumerate(circuit_items):
            item.update(
                {
                    "is_circuit": True,
                    "circuit_rounds": circuit_rounds,
                    "circuit_rest": circuit_rest,
                    "circuit_position": pos,
                    "circuit_size": size,
                    "target_sets": circuit_rounds,
                    # Descanso solo después del último ejercicio de cada ronda
                    "suggested_rest": circuit_rest if pos == size - 1 else 0,
                }
            )
            exercises.append(item)
        circuit_items.clear()
        in_circuit = False

    for line in section_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        is_indented = line.startswith("  ")

        # ── Sub-ítem de circuito (sangría + bullet) ────────────────────────
        if in_circuit and is_indented and stripped.startswith("•"):
            sub = re.match(r"^[•]\s+(.+?):\s+([\d]+(?:-[\d]+)?)\s*(.*)", stripped)
            if sub:
                name = sub.group(1).strip()
                reps_raw = sub.group(2).strip()
                unit_note = sub.group(3).strip()
                # "reps" y "repeticiones" son unidades, no notas
                note = (
                    ""
                    if unit_note.lower() in ("reps", "rep", "repeticiones")
                    else unit_note
                )
                nums = re.findall(r"\d+", reps_raw)
                reps_min = reps_max = int(nums[0]) if nums else 8
                if len(nums) >= 2:
                    reps_min, reps_max = int(nums[0]), int(nums[1])
                circuit_items.append(
                    {
                        "name": name,
                        "target_reps": reps_raw + (" " + note if note else ""),
                        "reps_min": reps_min,
                        "reps_max": reps_max,
                        "note": note,
                        "suggested_weight": 0.0,
                    }
                )
            continue

        # ── Solo bullets de primer nivel (sin sangría) ─────────────────────
        if not stripped.startswith("•") or is_indented:
            continue

        _flush_circuit()  # cerrar circuito anterior si lo hay

        # ── Encabezado de circuito ─────────────────────────────────────────
        c_match = re.match(
            r"^[•]\s+[Cc]ircuito[^(]*\((\d+)\s+rondas[^)]*descanso\s+(\d+)s",
            stripped,
        )
        if c_match:
            in_circuit = True
            circuit_rounds = int(c_match.group(1))
            circuit_rest = int(c_match.group(2))
            continue

        # ── Ejercicio normal: '• Nombre: SxR — nota' ──────────────────────
        match = re.match(
            r"^[•]\s+(.+?):\s+(\d+)\s*[xX×]\s*([\d]+(?:-[\d]+)?(?:\s+(?:seg|segundos|min))?)(.*)",
            stripped,
        )
        if not match:
            continue
        name = match.group(1).strip()
        sets = int(match.group(2))
        reps_raw = match.group(3).strip()
        note = match.group(4).strip().lstrip("—").strip()

        nums = re.findall(r"\d+", reps_raw)
        if len(nums) >= 2:
            reps_min, reps_max = int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            reps_min = reps_max = int(nums[0])
        else:
            reps_min = reps_max = 8

        exercises.append(
            {
                "name": name,
                "target_sets": sets,
                "target_reps": reps_raw,
                "reps_min": reps_min,
                "reps_max": reps_max,
                "note": note,
                "suggested_rest": _suggest_rest(reps_min, reps_max),
                "suggested_weight": 0.0,
                "is_circuit": False,
                "circuit_rounds": 0,
                "circuit_rest": 0,
                "circuit_position": 0,
                "circuit_size": 0,
            }
        )

    _flush_circuit()  # flush si la sección termina dentro de un circuito
    return exercises


def _extract_day_section(routine_text: str, day_name: str) -> str | None:
    """
    Extrae la sección de la rutina correspondiente a un día específico.

    Solo activa/corta la captura en líneas que son encabezados "DÍA N"
    (no en cualquier línea que mencione el día) para evitar que una nota
    del tipo "puedes moverlo al {day}" dentro de otro día contamine la sección.
    """
    lines = routine_text.split("\n")
    in_section = False
    section_lines: list[str] = []
    header_pattern = re.compile(r"DÍA\s+\d+", re.IGNORECASE)
    day_pattern = re.compile(rf"\b{re.escape(day_name)}\b", re.IGNORECASE)

    for line in lines:
        if header_pattern.search(line):
            if day_pattern.search(line):
                in_section = True
                section_lines = [line]
            elif in_section:
                break
        elif in_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip() if section_lines else None


def _parse_exercises(routine_text: str) -> list[str]:
    """Extrae nombres de ejercicios del texto de rutina con formato '• Nombre: ...'."""
    exercises = []
    for line in routine_text.split("\n"):
        match = re.match(r"^[•\-\*]\s+([^:]+?):", line.strip())
        if match:
            name = match.group(1).strip()
            if 2 < len(name) < 50:
                exercises.append(name)
    return list(dict.fromkeys(exercises))


def _format_reps_range(reps_min: int, reps_max: int) -> str:
    if reps_min == reps_max:
        return str(reps_min)
    return f"{reps_min}-{reps_max}"


def _routine_draft_to_text(draft: RoutineDraft) -> str:
    lines = [draft.name]
    for day in sorted(draft.days, key=lambda item: item.order):
        lines.append("")
        lines.append(f"DÍA {day.order} ({day.weekday.capitalize()})")
        for block in sorted(day.blocks, key=lambda item: item.order):
            if block.type == BlockType.CIRCUIT:
                rest = max(
                    (exercise.rest_seconds for exercise in block.exercises), default=0
                )
                lines.append(
                    f"• Circuito ({block.rounds} rondas, descanso {rest}s entre rondas):"
                )
                for exercise in sorted(block.exercises, key=lambda item: item.order):
                    reps = _format_reps_range(exercise.reps_min, exercise.reps_max)
                    lines.append(f"  • {exercise.exercise_id}: {reps} reps")
            else:
                for exercise in sorted(block.exercises, key=lambda item: item.order):
                    reps = _format_reps_range(exercise.reps_min, exercise.reps_max)
                    weight = (
                        f" @ {_fmt_kg(exercise.initial_weight)} kg"
                        if exercise.initial_weight
                        else ""
                    )
                    lines.append(
                        f"• {exercise.exercise_id}: {exercise.sets}x{reps}{weight}"
                    )
    return "\n".join(lines).strip()


def _routine_json_to_draft(routine_json: str | None) -> RoutineDraft | None:
    if not routine_json:
        return None
    return RoutineDraft.model_validate_json(routine_json)


def _routine_draft_exercise_names(draft: RoutineDraft) -> list[str]:
    names = []
    for day in sorted(draft.days, key=lambda item: item.order):
        for block in sorted(day.blocks, key=lambda item: item.order):
            for exercise in sorted(block.exercises, key=lambda item: item.order):
                if exercise.exercise_id not in names:
                    names.append(exercise.exercise_id)
    return names


def _structured_day_exercises(
    draft: RoutineDraft, weekday: str
) -> tuple[str, list[dict]]:
    day = next((item for item in draft.days if item.weekday == weekday), None)
    if day is None:
        return "", []

    exercises: list[dict] = []
    day_name = f"DÍA {day.order} ({day.weekday.capitalize()})"
    for block in sorted(day.blocks, key=lambda item: item.order):
        ordered = sorted(block.exercises, key=lambda item: item.order)
        if block.type == BlockType.CIRCUIT:
            size = len(ordered)
            for pos, exercise in enumerate(ordered):
                reps = _format_reps_range(exercise.reps_min, exercise.reps_max)
                exercises.append(
                    {
                        "name": exercise.exercise_id,
                        "target_sets": block.rounds,
                        "target_reps": reps,
                        "reps_min": exercise.reps_min,
                        "reps_max": exercise.reps_max,
                        "note": "",
                        "suggested_rest": exercise.rest_seconds
                        if pos == size - 1
                        else 0,
                        "suggested_weight": exercise.initial_weight,
                        "is_circuit": True,
                        "circuit_rounds": block.rounds,
                        "circuit_rest": exercise.rest_seconds if pos == size - 1 else 0,
                        "circuit_position": pos,
                        "circuit_size": size,
                    }
                )
        else:
            for exercise in ordered:
                reps = _format_reps_range(exercise.reps_min, exercise.reps_max)
                exercises.append(
                    {
                        "name": exercise.exercise_id,
                        "target_sets": exercise.sets,
                        "target_reps": reps,
                        "reps_min": exercise.reps_min,
                        "reps_max": exercise.reps_max,
                        "note": "",
                        "suggested_rest": exercise.rest_seconds,
                        "suggested_weight": exercise.initial_weight,
                        "is_circuit": False,
                        "circuit_rounds": 0,
                        "circuit_rest": 0,
                        "circuit_position": 0,
                        "circuit_size": 0,
                    }
                )
    return day_name, exercises


def _apply_progression_targets(uid: str, exercises: list[dict]) -> None:
    """
    Sobrescribe suggested_weight y suggested_reps en cada ejercicio con los
    valores calculados por el agente al final de la última sesión.
    Si no hay target guardado, cae al último peso registrado en workouts.
    """
    for ex in exercises:
        target = _store.get_progression_target(uid, ex["name"])
        if target is not None:
            ex["suggested_weight"] = target["next_weight"]
            if target.get("next_reps"):
                ex["suggested_reps"] = target["next_reps"]
        else:
            last = _store.get_last_weight_for_exercise(uid, ex["name"])
            if last is not None:
                ex["suggested_weight"] = last


def get_current_user(
    token: str = Query(..., description="web_token personal del usuario"),
) -> dict:
    """
    Dependencia FastAPI: valida el web_token y devuelve el perfil del usuario.

    [CONCEPTO: Query(...) — parámetro requerido]
    Query(...) con Ellipsis como default indica que el parámetro es OBLIGATORIO.
    FastAPI devuelve 422 automáticamente si el cliente no lo envía.
    Luego nosotros devolvemos 401 si el token no existe en la DB.

    Aprende más: https://fastapi.tiangolo.com/tutorial/dependencies/
    """
    user = _store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return user


def get_bearer_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer requerido")
    token = authorization.split(" ", 1)[1].strip()
    user = _store.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return user


def _build_session_plan_payload(
    user: dict,
    today: datetime.date | None = None,
) -> dict:
    uid = user["telegram_id"]
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = today or datetime.datetime.now(tz).date()
    today_day = _DAYS_ES[today.weekday()]

    training_days = [
        d.strip() for d in (user.get("training_days") or "").split(",") if d.strip()
    ]
    is_training_day = today_day in training_days

    today_str = today.strftime("%Y-%m-%d")
    overrides = _store.get_active_overrides(uid)
    today_override = next(
        (ov for ov in overrides if ov["target_date"] == today_str), None
    )

    override_exercises: list[dict] = []
    if today_override:
        override_exercises = _parse_session_exercises(today_override["modification"])

    has_override_session = bool(override_exercises)

    if not is_training_day and not has_override_session:
        next_day = None
        today_idx = _DAYS_ES.index(today_day)
        for i in range(1, 8):
            candidate = _DAYS_ES[(today_idx + i) % 7]
            if candidate in training_days:
                next_day = candidate
                break
        return {
            "is_rest_day": True,
            "today_day": today_day,
            "next_training_day": next_day,
        }

    routine = _store.get_active_routine(uid)
    exercises: list[dict] = []
    day_name = ""

    if routine and is_training_day:
        draft = _routine_json_to_draft(routine.get("routine_json"))
        if draft:
            day_name, exercises = _structured_day_exercises(draft, today_day)
        else:
            section = _extract_day_section(routine["routine_text"], today_day)
            if section:
                first_line = section.split("\n")[0].strip()
                day_name = re.sub(r"^[^\w]+", "", first_line).strip()
                exercises = _parse_session_exercises(section)
        _apply_progression_targets(uid, exercises)

    if has_override_session:
        exercises = override_exercises
        _apply_progression_targets(uid, exercises)

    return {
        "is_rest_day": False,
        "today_day": today_day,
        "day_name": day_name,
        "exercises": exercises,
        "override": today_override,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/app")
async def serve_app() -> FileResponse:
    """
    Sirve el HTML de la app web.

    [CONCEPTO: FileResponse en FastAPI]
    Devuelve un archivo del disco como respuesta HTTP con el Content-Type correcto.
    El cliente (navegador) recibe el HTML, luego Alpine.js hace las llamadas API.
    La autenticación ocurre en las llamadas API, no al servir el HTML.
    """
    return FileResponse(
        os.path.join(_TEMPLATES, "workout.html"), media_type="text/html"
    )


@router.get("/api/session/me")
async def get_profile(user: dict = Depends(get_current_user)) -> dict:
    """
    Devuelve el perfil del usuario y los ejercicios de su rutina activa.
    Alpine.js llama esto al iniciar la página para personalizar la interfaz.
    """
    uid = user["telegram_id"]
    routine = _store.get_active_routine(uid)
    exercises = []
    if routine:
        draft = _routine_json_to_draft(routine.get("routine_json"))
        exercises = (
            _routine_draft_exercise_names(draft)
            if draft
            else _parse_exercises(routine["routine_text"])
        )

    return {
        "name": user.get("name", "Atleta"),
        "goal": user.get("goal", ""),
        "exercises": exercises,
        "session_minutes": user.get("session_time_minutes", 60),
    }


class SetPayload(BaseModel):
    """
    Datos de una serie registrada desde la app web.

    [CONCEPTO: Pydantic — validación automática del body]
    FastAPI deserializa el JSON del body y valida tipos automáticamente.
    Campos con Optional[X] y default None no son requeridos.
    Si el cliente envía un tipo incorrecto (ej: reps="abc") → 422 automático.
    """

    token: str
    exercise: str
    reps: int
    weight_kg: float = 0.0
    rpe: Optional[int] = None  # Esfuerzo Percibido: 6=liviano, 10=fallo
    notes: Optional[str] = None


class RoutineDraftPayload(BaseModel):
    token: str
    draft: RoutineDraft


class RoutineDraftActionPayload(BaseModel):
    token: str


class AgentMessagePayload(BaseModel):
    message: str
    channel: str = "api"


@router.post("/api/session/set")
async def log_set(payload: SetPayload) -> dict:
    """
    Registra una serie individual. Se llama después de cada set completado.

    Diferencia vs el bot de Telegram:
    - Bot: el LLM infiere "4x8 80kg" → un registro con sets=4
    - App web: el usuario registra serie por serie → un registro con sets=1
    Mayor granularidad permite tracking de RPE por serie individual.
    """
    # Validar token desde el body (no usamos Depends aquí porque el token va en el body)
    user = _store.get_user_by_token(payload.token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")

    uid = user["telegram_id"]
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    routine = _store.get_active_routine(uid)
    session = _store.get_or_create_training_session(
        uid,
        today.strftime("%Y-%m-%d"),
        routine["id"] if routine else None,
    )
    workout_id = _store.save_workout(
        user_id=uid,
        exercise=payload.exercise,
        sets=1,
        reps=payload.reps,
        weight_kg=payload.weight_kg,
        rpe=payload.rpe,
        notes=payload.notes,
        session_id=session["id"],
    )

    # Devolvemos el registro completo para que Alpine.js actualice el log
    # sin un GET adicional — evita un round-trip de red.
    return {
        "id": workout_id,
        "exercise": payload.exercise,
        "sets": 1,
        "reps": payload.reps,
        "weight_kg": payload.weight_kg,
        "rpe": payload.rpe,
        "notes": payload.notes,
        "session_id": session["id"],
    }


@router.post("/api/routines/drafts")
async def create_routine_draft(payload: RoutineDraftPayload) -> dict:
    user = _store.get_user_by_token(payload.token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")

    routine_json = payload.draft.model_dump_json()
    routine_text = _routine_draft_to_text(payload.draft)
    routine_id = _store.create_routine_draft(
        user["telegram_id"],
        routine_text=routine_text,
        routine_json=routine_json,
    )
    return {
        "id": routine_id,
        "status": "draft",
        "routine": payload.draft.model_dump(mode="json"),
        "routine_text": routine_text,
    }


@router.post("/api/routines/drafts/{routine_id}/confirm")
async def confirm_routine_draft(
    routine_id: int, payload: RoutineDraftActionPayload
) -> dict:
    user = _store.get_user_by_token(payload.token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")
    try:
        _store.confirm_routine_draft(user["telegram_id"], routine_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Borrador no encontrado")
    routine = _store.get_routine(user["telegram_id"], routine_id)
    draft = _routine_json_to_draft(routine.get("routine_json") if routine else None)
    if draft:
        training_days = ",".join(
            day.weekday for day in sorted(draft.days, key=lambda item: item.order)
        )
        _store.update_training_days(user["telegram_id"], training_days)
    return {"id": routine_id, "status": "active"}


@router.post("/api/routines/drafts/{routine_id}/cancel")
async def cancel_routine_draft(
    routine_id: int, payload: RoutineDraftActionPayload
) -> dict:
    user = _store.get_user_by_token(payload.token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")
    _store.cancel_routine_draft(user["telegram_id"], routine_id)
    return {"id": routine_id, "status": "archived"}


@router.get("/api/session/plan")
async def get_session_plan(user: dict = Depends(get_current_user)) -> dict:
    """
    Devuelve el plan estructurado de la sesión de hoy.

    Incluye:
    - Si hoy es día de entrenamiento o descanso
    - El nombre del bloque de hoy (DÍA 2 — TRACCIÓN)
    - Los ejercicios en orden con sets objetivo, reps, descanso sugerido y último peso
    - Override activo si hay uno para hoy

    [CONCEPTO: API orientada a la pantalla (Screen-Oriented API)]
    Este endpoint devuelve exactamente lo que la pantalla necesita renderizar,
    evitando que el cliente tenga que combinar múltiples llamadas.
    Trade-off: más acoplamiento backend/frontend, menos re-uso.
    Para un proyecto personal es el enfoque correcto.
    """
    return _build_session_plan_payload(user)


@router.post("/api/agent/message")
async def agent_message(
    payload: AgentMessagePayload,
    user: dict = Depends(get_bearer_user),
) -> dict:
    response = await run_agent_message(
        user_id=user["telegram_id"],
        message=payload.message,
        channel=payload.channel,
    )
    return response.model_dump(mode="json")


@router.get("/api/session/today")
async def get_today_session(user: dict = Depends(get_current_user)) -> list:
    """
    Devuelve todas las series registradas hoy, en orden cronológico.
    Alpine.js llama esto al iniciar para mostrar la sesión en curso.
    """
    return _store.get_today_workouts(user["telegram_id"])


# ─────────────────────────────────────────────────────────────────────────────
# Progresión post-sesión
# ─────────────────────────────────────────────────────────────────────────────


def _build_progression_prompt(
    user: dict,
    today_sets: list[dict],
    history: dict[str, list[dict]],
) -> str:
    """
    Construye el contexto para que el agente calcule la progresión de carga.

    El agente propone como entrenador; el backend valida límites de seguridad
    antes de persistir. Si la respuesta no valida, se usa fallback determinístico.
    """
    today_by_ex: dict[str, list[dict]] = {}
    for s in today_sets:
        today_by_ex.setdefault(s["exercise"], []).append(s)

    lines_today = []
    for ex, sets in today_by_ex.items():
        series_str = "  ".join(
            f"S{i + 1}: {s['reps']}r @{s['weight_kg']}kg"
            + (f" RPE{s['rpe']}" if s.get("rpe") is not None else "")
            for i, s in enumerate(sets)
        )
        lines_today.append(f"• {ex}: {series_str}")

    lines_hist = []
    for ex, records in history.items():
        if not records:
            continue
        rec_str = " | ".join(
            f"{r['reps']}r @{r['weight_kg']}kg"
            + (f" RPE{r['rpe']}" if r.get("rpe") is not None else "")
            + f" [{r['session_date']}]"
            for r in records
        )
        lines_hist.append(f"• {ex}: {rec_str}")

    return f"""Eres Heracles, entrenador experto en fuerza e hipertrofia.

PERFIL DEL USUARIO:
• Nombre: {user.get("name", "?")}
• Objetivo: {user.get("goal", "?")}
• Nivel: {user.get("experience_level", "?")}
• Equipamiento: {user.get("home_equipment_detail") or user.get("equipment", "?")}

ESCALA RPE (Esfuerzo Percibido) — IMPORTANTE:
RPE 10 = fallo total (0 reps restantes, máximo esfuerzo)
RPE 9 = 1 rep en recámara, muy cerca del fallo
RPE 8 = 2 reps en recámara, buena intensidad
RPE 7 = 3 reps en recámara
RPE 6 = 4+ reps en recámara, liviano
→ RPE alto (9-10) = peso desafiante. RPE bajo (6-7) = peso demasiado liviano, subir carga.

SESIÓN COMPLETADA HOY:
{chr(10).join(lines_today) or "Sin series registradas"}

HISTORIAL RECIENTE (últimas sesiones registradas por ejercicio):
{chr(10).join(lines_hist) or "Sin historial previo"}

CRITERIO DE PROGRESIÓN:
Actúa como entrenador personal. Usa el perfil, objetivo, nivel, equipamiento,
rendimiento de hoy, RPE, notas y tendencia del historial para decidir la próxima
prescripción de cada ejercicio.

Puedes subir peso, bajar peso, subir o bajar series, ajustar el rango de reps o
consolidar. La doble progresión es una guía, no una regla rígida: normalmente
se construyen reps/series antes de subir carga, pero puedes desviarte si el
historial, la fatiga, el RPE, el estancamiento o el objetivo del usuario lo
justifican.

Límites que debes respetar:
• Si hay dolor o molestia reportada, no aumentes carga ni volumen.
• Si RPE 9-10, evita subir peso salvo que el historial lo justifique de forma
  muy clara; en general consolida o reduce.
• No hagas saltos grandes de carga; prefiere incrementos de 2.5 kg.
• Ejercicios de peso corporal con weight_kg=0 mantienen next_weight=0 salvo
  que el usuario ya use carga externa registrada.
• No cambies varias palancas a la vez salvo que sea una descarga o haya una
  justificación clara.

Responde ÚNICAMENTE con JSON válido, sin texto adicional ni markdown:
{{
  "summary": "2-3 frases evaluando la sesión en segunda persona: qué salió bien, qué vigilar. Tono de entrenador cercano, español neutro.",
  "decisions": [
    {{
      "exercise_id": "nombre exacto del ejercicio",
      "next_weight": 32.5,
      "next_sets": 3,
      "next_reps_min": 8,
      "next_reps_max": 10,
      "reason": "build_reps",
      "basis": "justificación breve en ≤10 palabras"
    }}
  ]
}}

Valores permitidos para reason:
build_reps, add_set, add_weight, reduce_weight, reduce_sets, consolidate,
insufficient_data.

Si el rango de reps o el número de series actual ya es correcto, repite el mismo
valor."""


def _parse_reps_range(value: str) -> tuple[int, int]:
    nums = [int(n) for n in re.findall(r"\d+", value)]
    if not nums:
        raise ValueError("next_reps must contain at least one number")
    if len(nums) == 1:
        return nums[0], nums[0]
    return nums[0], nums[1]


def _normalize_session_evaluation_payload(payload: object) -> dict:
    """
    Acepta el contrato nuevo y convierte el formato anterior solo si sus campos
    son exactamente los esperados. Campos extra siguen siendo inválidos.
    """
    if not isinstance(payload, dict):
        raise ValueError("Session evaluation must be a JSON object")

    if set(payload.keys()) == {"summary", "decisions"}:
        return payload

    if set(payload.keys()) != {"evaluacion", "ejercicios"}:
        raise ValueError("Unexpected session evaluation fields")

    decisions = []
    for item in payload["ejercicios"]:
        if not isinstance(item, dict):
            raise ValueError("Progression item must be an object")
        if set(item.keys()) != {
            "exercise",
            "next_weight",
            "next_reps",
            "next_sets",
            "basis",
        }:
            raise ValueError("Unexpected progression item fields")
        reps_min, reps_max = _parse_reps_range(str(item["next_reps"]))
        decisions.append(
            {
                "exercise_id": item["exercise"],
                "next_weight": item["next_weight"],
                "next_sets": item["next_sets"],
                "next_reps_min": reps_min,
                "next_reps_max": reps_max,
                "reason": ProgressionReason.CONSOLIDATE,
                "basis": item["basis"],
            }
        )

    return {
        "summary": payload["evaluacion"],
        "decisions": decisions,
    }


def _format_next_reps(decision: ProgressionDecision) -> str:
    if decision.next_reps_min == decision.next_reps_max:
        return str(decision.next_reps_min)
    return f"{decision.next_reps_min}-{decision.next_reps_max}"


def _suggestions_from_evaluation(
    evaluation: SessionEvaluation,
    today_sets: list[dict],
) -> list[dict]:
    allowed_exercises = {s["exercise"] for s in today_sets}
    seen_exercises: set[str] = set()
    suggestions = []

    for decision in evaluation.decisions:
        if decision.exercise_id not in allowed_exercises:
            raise ValueError(f"Unknown exercise in progression: {decision.exercise_id}")
        if decision.exercise_id in seen_exercises:
            raise ValueError(f"Duplicate progression decision: {decision.exercise_id}")
        if (decision.next_weight * 10) % 5 != 0:
            raise ValueError("next_weight must use 0.5 kg increments")

        seen_exercises.add(decision.exercise_id)
        suggestions.append(
            {
                "exercise": decision.exercise_id,
                "next_weight": decision.next_weight,
                "next_reps": _format_next_reps(decision),
                "next_sets": decision.next_sets,
                "reason": decision.reason.value,
                "basis": decision.basis,
            }
        )

    return suggestions


def _parse_session_evaluation(
    raw: str, today_sets: list[dict]
) -> tuple[str, list[dict]]:
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    import json as _json

    payload = _json.loads(raw)
    normalized = _normalize_session_evaluation_payload(payload)
    evaluation = SessionEvaluation.model_validate(normalized)
    return evaluation.summary, _suggestions_from_evaluation(evaluation, today_sets)


def _group_sets_by_exercise(today_sets: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in today_sets:
        grouped.setdefault(item["exercise"], []).append(item)
    return grouped


def _completed_sets_from_rows(rows: list[dict]) -> list[CompletedSet]:
    completed: list[CompletedSet] = []
    for row in rows:
        sets_count = int(row.get("sets") or 1)
        for _ in range(sets_count):
            completed.append(
                CompletedSet(
                    reps=int(row["reps"]),
                    weight=Decimal(str(row.get("weight_kg") or 0)),
                    rpe=row.get("rpe"),
                )
            )
    return completed


def _prescription_from_plan_exercise(
    exercise_name: str,
    plan_exercise: dict | None,
    rows: list[dict],
) -> Prescription:
    first_row = rows[0]
    actual_sets = sum(int(row.get("sets") or 1) for row in rows)
    current_weight = Decimal(str(first_row.get("weight_kg") or 0))

    target_sets = int((plan_exercise or {}).get("target_sets") or actual_sets)
    reps_min = int((plan_exercise or {}).get("reps_min") or first_row["reps"])
    reps_max = int((plan_exercise or {}).get("reps_max") or first_row["reps"])
    max_sets = max(target_sets, 4)

    return Prescription(
        exercise_id=exercise_name,
        weight=current_weight,
        sets=target_sets,
        reps_min=reps_min,
        reps_max=reps_max,
        max_sets=max_sets,
        weight_increment=Decimal("2.5"),
    )


def _basis_for_result(result: ProgressionResult) -> str:
    basis_by_action = {
        ProgressionAction.BUILD_REPS: "Subir reps antes de peso",
        ProgressionAction.ADD_SET: "Techo completo -> +1 serie",
        ProgressionAction.ADD_WEIGHT: "Techo completo -> +2.5 kg",
        ProgressionAction.CONSOLIDATE: "Consolidar antes de progresar",
        ProgressionAction.INSUFFICIENT_DATA: "Faltan series registradas",
    }
    return basis_by_action[result.action]


def _decimal_to_float(value: Decimal) -> float:
    return float(value)


def _suggestion_from_progression_result(result: ProgressionResult) -> dict:
    next_reps = str(result.next_reps_min)
    if result.next_reps_min != result.next_reps_max:
        next_reps = f"{result.next_reps_min}-{result.next_reps_max}"
    return {
        "exercise": result.exercise_id,
        "next_weight": _decimal_to_float(result.next_weight),
        "next_reps": next_reps,
        "next_sets": result.next_sets,
        "reason": result.action.value,
        "basis": _basis_for_result(result),
    }


def _calculate_deterministic_suggestions(
    user: dict,
    today_sets: list[dict],
    today: datetime.date,
) -> list[dict]:
    plan = _build_session_plan_payload(user, today=today)
    planned_by_name = {
        exercise["name"]: exercise for exercise in plan.get("exercises", [])
    }

    suggestions = []
    for exercise_name, rows in _group_sets_by_exercise(today_sets).items():
        prescription = _prescription_from_plan_exercise(
            exercise_name,
            planned_by_name.get(exercise_name),
            rows,
        )
        has_pain = any(text_reports_pain(row.get("notes")) for row in rows)
        if has_pain:
            result = ProgressionResult(
                exercise_id=prescription.exercise_id,
                next_weight=prescription.weight,
                next_sets=prescription.sets,
                next_reps_min=prescription.reps_min,
                next_reps_max=prescription.reps_max,
                action=ProgressionAction.CONSOLIDATE,
            )
        else:
            result = calculate_progression(
                prescription,
                _completed_sets_from_rows(rows),
            )
        suggestion = _suggestion_from_progression_result(result)
        if has_pain:
            suggestion["basis"] = "Molestia reportada -> no progresar"
        suggestions.append(suggestion)
    return suggestions


def _fallback_suggestion_for_exercise(
    fallback_suggestions: list[dict], exercise_name: str
) -> dict | None:
    for suggestion in fallback_suggestions:
        if suggestion.get("exercise") == exercise_name:
            return suggestion
    return None


def _validate_progression_guardrails(
    suggestion: dict,
    prescription: Prescription,
    completed_sets: list[CompletedSet],
    has_pain: bool,
) -> None:
    next_weight = Decimal(str(suggestion["next_weight"]))
    next_sets = int(suggestion["next_sets"])
    reps_min, reps_max = _parse_reps_range(str(suggestion["next_reps"]))
    weight_delta = next_weight - prescription.weight

    if (next_weight * Decimal("10")) % Decimal("5") != 0:
        raise ValueError("next_weight must use 0.5 kg increments")
    if next_sets > min(8, prescription.sets + 1):
        raise ValueError("next_sets can increase by at most one set")
    if reps_min > reps_max:
        raise ValueError("next_reps range is invalid")
    if reps_max > prescription.reps_max + 4:
        raise ValueError("next_reps is outside the allowed range")

    if prescription.weight == 0 and next_weight != 0:
        raise ValueError("bodyweight exercise cannot add external load automatically")

    if has_pain and (weight_delta > 0 or next_sets > prescription.sets):
        raise ValueError("pain report blocks load or volume increases")

    below_min = any(s.reps < prescription.reps_min for s in completed_sets)
    high_rpe = any(s.rpe is not None and s.rpe >= 9 for s in completed_sets)
    if (below_min or high_rpe) and weight_delta > 0:
        raise ValueError("performance or high RPE blocks weight increases")

    if weight_delta > prescription.weight_increment:
        raise ValueError("weight increase exceeds available increment")

    if weight_delta < 0 and prescription.weight > 0:
        max_drop = max(
            prescription.weight * Decimal("0.20"),
            prescription.weight_increment,
        )
        if abs(weight_delta) > max_drop:
            raise ValueError("weight reduction exceeds safety limit")


def _apply_agent_guardrails(
    user: dict,
    today_sets: list[dict],
    today: datetime.date,
    agent_suggestions: list[dict],
    fallback_suggestions: list[dict],
) -> list[dict]:
    plan = _build_session_plan_payload(user, today=today)
    planned_by_name = {
        exercise["name"]: exercise for exercise in plan.get("exercises", [])
    }
    rows_by_name = _group_sets_by_exercise(today_sets)
    accepted_by_name: dict[str, dict] = {}

    for suggestion in agent_suggestions:
        exercise_name = suggestion.get("exercise", "")
        rows = rows_by_name.get(exercise_name)
        if not rows or exercise_name in accepted_by_name:
            continue

        prescription = _prescription_from_plan_exercise(
            exercise_name,
            planned_by_name.get(exercise_name),
            rows,
        )
        completed_sets = _completed_sets_from_rows(rows)
        has_pain = any(text_reports_pain(row.get("notes")) for row in rows)
        try:
            _validate_progression_guardrails(
                suggestion, prescription, completed_sets, has_pain
            )
        except ValueError:
            fallback = _fallback_suggestion_for_exercise(
                fallback_suggestions, exercise_name
            )
            if fallback is not None:
                accepted_by_name[exercise_name] = fallback
            continue
        accepted_by_name[exercise_name] = suggestion

    validated = []
    for exercise_name in rows_by_name:
        suggestion = accepted_by_name.get(exercise_name) or _fallback_suggestion_for_exercise(
            fallback_suggestions, exercise_name
        )
        if suggestion is not None:
            validated.append(suggestion)
    return validated


async def _calculate_agent_session_evaluation(
    user: dict,
    today_sets: list[dict],
    today: datetime.date,
    fallback_suggestions: list[dict],
) -> tuple[str, list[dict]]:
    from langchain_openai import ChatOpenAI

    exercise_names = list(_group_sets_by_exercise(today_sets).keys())
    history = _store.get_history_for_exercises(
        user["telegram_id"], exercise_names, per_exercise=5
    )
    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_key=settings.DEEPSEEK_API_KEY,
        openai_api_base="https://api.deepseek.com",
        temperature=0.2,
    )
    response = await llm.ainvoke(
        [HumanMessage(content=_build_progression_prompt(user, today_sets, history))]
    )
    evaluation, agent_suggestions = _parse_session_evaluation(
        response.content, today_sets
    )
    suggestions = _apply_agent_guardrails(
        user, today_sets, today, agent_suggestions, fallback_suggestions
    )
    return evaluation, suggestions


def _build_summary_prompt(
    user: dict, today_sets: list[dict], suggestions: list[dict]
) -> str:
    rows = "\n".join(
        f"• {s['exercise']}: {s['reps']} reps @ {s['weight_kg']} kg"
        + (f" RPE{s['rpe']}" if s.get("rpe") is not None else "")
        for s in today_sets
    )
    decisions = "\n".join(
        f"• {s['exercise']}: {s['next_sets']}x{s['next_reps']} @ {s['next_weight']} kg ({s['basis']})"
        for s in suggestions
    )
    return f"""Eres Heracles, entrenador experto en fuerza e hipertrofia.

Redacta solo un resumen breve en español neutro, de 2-3 frases, en segunda
persona. No cambies los números ni inventes decisiones.

Usuario: {user.get("name", "Atleta")}
Objetivo: {user.get("goal", "")}

Sesión registrada:
{rows or "Sin series registradas"}

Decisiones calculadas por el backend:
{decisions or "Sin decisiones"}
"""


def _local_session_summary(suggestions: list[dict]) -> str:
    if not suggestions:
        return (
            "Sesión registrada. No hubo datos suficientes para calcular progresiones."
        )
    progressed = [
        s
        for s in suggestions
        if s.get("reason")
        in {ProgressionAction.ADD_SET.value, ProgressionAction.ADD_WEIGHT.value}
    ]
    if progressed:
        return "Sesión completada. Hubo rendimiento suficiente para progresar en algunos objetivos."
    return "Sesión completada. Mantén el foco en consolidar técnica, reps y esfuerzo antes de subir carga."


@router.post("/api/session/finish")
async def finish_session(
    user: dict = Depends(get_current_user),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    routine = _store.get_active_routine(user["telegram_id"])
    session = _store.get_or_create_training_session(
        user["telegram_id"],
        today.strftime("%Y-%m-%d"),
        routine["id"] if routine else None,
    )
    return await _finish_training_session(user, session["id"], idempotency_key)


@router.post("/api/sessions/{session_id}/finish")
async def finish_training_session(
    session_id: str,
    user: dict = Depends(get_bearer_user),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict:
    return await _finish_training_session(user, session_id, idempotency_key)


async def _finish_training_session(
    user: dict,
    session_id: str,
    idempotency_key: str | None = None,
) -> dict:
    """
    Calcula y persiste la progresión de carga para la próxima sesión.

    Flujo:
    1. Series completadas hoy → agrupadas por ejercicio
    2. Historial de las últimas 5 sesiones por ejercicio
    3. Agente LLM propone la progresión como entrenador
    4. Backend valida guardrails; si falla, usa fallback determinístico
    5. Persistir en progression_targets — próxima sesión ya lleva el objetivo
    6. Devolver sugerencias al frontend para mostrar en el resumen

    [CONCEPTO: LLM directo vs LangGraph para tareas de análisis]
    Para análisis de una sola pasada sin tool calls ni memoria conversacional,
    invocar el LLM directamente es más rápido y limpio que pasarlo por el grafo.
    LangGraph aporta valor cuando hay ciclos razonamiento ↔ herramientas.
    """
    uid = user["telegram_id"]
    session = _store.get_training_session(session_id)
    if not session or session["user_id"] != uid:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    if session["status"] == "evaluated" and session.get("evaluation_json"):
        cached = json.loads(session["evaluation_json"])
        cached["session_id"] = session_id
        cached["idempotent"] = True
        return cached

    try:
        session = _store.begin_session_evaluation(session_id, idempotency_key)
    except ValueError as exc:
        if "already in progress" in str(exc):
            raise HTTPException(
                status_code=409, detail="La sesión ya se está evaluando"
            )
        raise
    if session["status"] == "evaluated" and session.get("evaluation_json"):
        cached = json.loads(session["evaluation_json"])
        cached["session_id"] = session_id
        cached["idempotent"] = True
        return cached

    today_str = session["scheduled_date"]
    today = datetime.date.fromisoformat(today_str)
    _store.attach_workouts_to_session(uid, session_id)
    today_sets = _store.get_workouts_for_date(uid, today_str)
    if not today_sets:
        result = {"suggestions": [], "evaluation": "", "session_id": session_id}
        _store.complete_session_evaluation(
            session_id, json.dumps(result, ensure_ascii=False)
        )
        return result

    fallback_suggestions = _calculate_deterministic_suggestions(
        user, today_sets, today=today
    )
    suggestions = fallback_suggestions
    evaluation = _local_session_summary(suggestions)
    if settings.DEEPSEEK_API_KEY:
        try:
            evaluation, suggestions = await _calculate_agent_session_evaluation(
                user,
                today_sets,
                today,
                fallback_suggestions,
            )
            if not suggestions:
                suggestions = fallback_suggestions
        except Exception:
            suggestions = fallback_suggestions
            evaluation = _local_session_summary(suggestions)

    # Persistir cada sugerencia
    for item in suggestions:
        ex = item.get("exercise", "").strip()
        nw = item.get("next_weight")
        if ex and nw is not None:
            next_sets = item.get("next_sets")
            _store.save_progression_target(
                user_id=uid,
                exercise=ex,
                next_weight=float(nw),
                basis=item.get("basis", ""),
                session_date=today_str,
                next_reps=item.get("next_reps") or None,
                next_sets=int(next_sets) if next_sets else None,
            )

    # Reflejar la progresión calculada en la rutina general persistida,
    # para que /rutina y la app web muestren el mismo peso sin pasar por el chat.
    routine = _store.get_active_routine(uid)
    if routine:
        updated_text = apply_progression_to_routine_text(routine["routine_text"], uid)
        if updated_text != routine["routine_text"]:
            _store.update_active_routine_text(uid, updated_text)

    # Enviar la evaluación al chat de Telegram del usuario.
    # Si Telegram falla (usuario bloqueó el bot, red, etc.) no rompemos la
    # respuesta web: la progresión ya quedó persistida.
    try:
        await _send_evaluation_to_telegram(uid, evaluation, suggestions)
    except Exception:
        pass

    result = {
        "suggestions": suggestions,
        "evaluation": evaluation,
        "session_id": session_id,
    }
    _store.complete_session_evaluation(
        session_id,
        json.dumps(result, ensure_ascii=False),
    )
    return result


def _fmt_kg(weight: float) -> str:
    """Formatea kg sin decimales innecesarios: 35.0 → '35', 32.5 → '32.5'."""
    return str(int(weight)) if float(weight).is_integer() else str(weight)


async def _send_evaluation_to_telegram(
    uid: str, evaluation: str, suggestions: list[dict]
) -> None:
    """
    Envía la evaluación post-sesión al chat de Telegram del usuario.

    [CONCEPTO: Bot standalone para mensajes proactivos]
    Igual que en n8n_webhook.py: creamos un Bot sin Application para enviar
    un mensaje desde fuera de un handler de Telegram. El telegram_id del
    usuario es a la vez su chat_id en conversaciones privadas.
    """
    from telegram import Bot

    if not evaluation and not suggestions:
        return

    lines = ["🏁 Sesión completada — evaluación de hoy", ""]
    if evaluation:
        lines += [evaluation, ""]
    if suggestions:
        lines.append("Próximos objetivos:")
        for s in suggestions:
            ex = s.get("exercise", "").strip()
            if not ex:
                continue
            sets_reps = (
                f"{s['next_sets']}x{s['next_reps']}"
                if s.get("next_sets") and s.get("next_reps")
                else ""
            )
            weight = s.get("next_weight")
            peso = (
                f" @ {_fmt_kg(weight)}kg" if weight else ""
            )  # 0 = peso corporal, se omite
            basis = f" — {s['basis']}" if s.get("basis") else ""
            lines.append(f"• {ex}: {sets_reps}{peso}{basis}")

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=uid, text="\n".join(lines))
