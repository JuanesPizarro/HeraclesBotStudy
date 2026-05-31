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
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bot.storage.user_store import UserStore

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

    [CONCEPTO: Regex con grupos nombrados para parsing robusto]
    El formato de la rutina es: '• Nombre: SxR[unidad] — nota'
    Ejemplos:
      • Sentadilla goblet: 3x10-12 — Sujeta una mancuerna
      • Plancha antebrazos: 3x30-45 seg — Cero presión en muñeca
      • Dominadas: 3x5-8 — Asistidas con banda

    Circuitos y encabezados (líneas con ─ o 📋) se saltan automáticamente.
    """
    exercises = []
    for line in section_text.split("\n"):
        stripped = line.strip()
        # Solo líneas que empiezan con bullet de primer nivel (no sub-items de circuito)
        if not stripped.startswith("•") or line.startswith("  "):
            continue
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

        # Extraer valores numéricos de "10-12", "30-45 seg", "30"
        nums = re.findall(r"\d+", reps_raw)
        if len(nums) >= 2:
            reps_min, reps_max = int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            reps_min = reps_max = int(nums[0])
        else:
            reps_min = reps_max = 8

        exercises.append({
            "name": name,
            "target_sets": sets,
            "target_reps": reps_raw,
            "reps_min": reps_min,
            "reps_max": reps_max,
            "note": note,
            "suggested_rest": _suggest_rest(reps_min, reps_max),
            "suggested_weight": 0.0,  # se rellena desde el historial después
        })
    return exercises


def _extract_day_section(routine_text: str, day_name: str) -> str | None:
    """Extrae la sección de la rutina correspondiente a un día específico."""
    lines = routine_text.split("\n")
    in_section = False
    section_lines: list[str] = []
    header_pattern = re.compile(r"DÍA\s+\d+", re.IGNORECASE)

    for line in lines:
        if re.search(rf"\b{re.escape(day_name)}\b", line, re.IGNORECASE):
            in_section = True
            section_lines = [line]
        elif in_section:
            if header_pattern.search(line) and not re.search(
                rf"\b{re.escape(day_name)}\b", line, re.IGNORECASE
            ):
                break
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


def get_current_user(token: str = Query(..., description="web_token personal del usuario")) -> dict:
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
    return FileResponse(os.path.join(_TEMPLATES, "workout.html"), media_type="text/html")


@router.get("/api/session/me")
async def get_profile(user: dict = Depends(get_current_user)) -> dict:
    """
    Devuelve el perfil del usuario y los ejercicios de su rutina activa.
    Alpine.js llama esto al iniciar la página para personalizar la interfaz.
    """
    uid = user["telegram_id"]
    routine = _store.get_active_routine(uid)
    exercises = _parse_exercises(routine["routine_text"]) if routine else []

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
    rir: Optional[int] = None   # Repeticiones en Recámara: 0=fallo, 5=muy cómodo
    notes: Optional[str] = None


@router.post("/api/session/set")
async def log_set(payload: SetPayload) -> dict:
    """
    Registra una serie individual. Se llama después de cada set completado.

    Diferencia vs el bot de Telegram:
    - Bot: el LLM infiere "4x8 80kg" → un registro con sets=4
    - App web: el usuario registra serie por serie → un registro con sets=1
    Mayor granularidad permite tracking de RPE/RIR por serie individual.
    """
    # Validar token desde el body (no usamos Depends aquí porque el token va en el body)
    user = _store.get_user_by_token(payload.token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido")

    uid = user["telegram_id"]
    workout_id = _store.save_workout(
        user_id=uid,
        exercise=payload.exercise,
        sets=1,
        reps=payload.reps,
        weight_kg=payload.weight_kg,
        rir=payload.rir,
        notes=payload.notes,
    )

    # Devolvemos el registro completo para que Alpine.js actualice el log
    # sin un GET adicional — evita un round-trip de red.
    return {
        "id": workout_id,
        "exercise": payload.exercise,
        "sets": 1,
        "reps": payload.reps,
        "weight_kg": payload.weight_kg,
        "rir": payload.rir,
        "notes": payload.notes,
    }


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
    uid = user["telegram_id"]
    today = datetime.date.today()
    today_day = _DAYS_ES[today.weekday()]

    training_days = [
        d.strip() for d in (user.get("training_days") or "").split(",") if d.strip()
    ]
    is_training_day = today_day in training_days

    if not is_training_day:
        # Calcular próximo día de entrenamiento
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

    # Día de entrenamiento: extraer plan
    routine = _store.get_active_routine(uid)
    exercises: list[dict] = []
    day_name = ""

    if routine:
        section = _extract_day_section(routine["routine_text"], today_day)
        if section:
            # Extraer nombre del bloque (primera línea: "📋 DÍA 2 — TRACCIÓN (Martes)")
            first_line = section.split("\n")[0].strip()
            day_name = re.sub(r"^[^\w]+", "", first_line).strip()  # quitar emojis/separadores
            exercises = _parse_session_exercises(section)
            # Pre-llenar último peso registrado para cada ejercicio
            for ex in exercises:
                last = _store.get_last_weight_for_exercise(uid, ex["name"])
                if last is not None:
                    ex["suggested_weight"] = last

    # Override activo para hoy
    today_str = today.strftime("%Y-%m-%d")
    overrides = _store.get_active_overrides(uid)
    today_override = next(
        (ov for ov in overrides if ov["target_date"] == today_str), None
    )

    return {
        "is_rest_day": False,
        "today_day": today_day,
        "day_name": day_name,
        "exercises": exercises,
        "override": today_override,
    }


@router.get("/api/session/today")
async def get_today_session(user: dict = Depends(get_current_user)) -> list:
    """
    Devuelve todas las series registradas hoy, en orden cronológico.
    Alpine.js llama esto al iniciar para mostrar la sesión en curso.
    """
    return _store.get_today_workouts(user["telegram_id"])
