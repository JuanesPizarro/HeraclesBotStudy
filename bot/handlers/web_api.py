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
import zoneinfo
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from bot.storage.user_store import UserStore
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
            item.update({
                "is_circuit": True,
                "circuit_rounds": circuit_rounds,
                "circuit_rest": circuit_rest,
                "circuit_position": pos,
                "circuit_size": size,
                "target_sets": circuit_rounds,
                # Descanso solo después del último ejercicio de cada ronda
                "suggested_rest": circuit_rest if pos == size - 1 else 0,
            })
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
                note = "" if unit_note.lower() in ("reps", "rep", "repeticiones") else unit_note
                nums = re.findall(r"\d+", reps_raw)
                reps_min = reps_max = int(nums[0]) if nums else 8
                if len(nums) >= 2:
                    reps_min, reps_max = int(nums[0]), int(nums[1])
                circuit_items.append({
                    "name": name,
                    "target_reps": reps_raw + (" " + note if note else ""),
                    "reps_min": reps_min,
                    "reps_max": reps_max,
                    "note": note,
                    "suggested_weight": 0.0,
                })
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

        exercises.append({
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
        })

    _flush_circuit()  # flush si la sección termina dentro de un circuito
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
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    today_day = _DAYS_ES[today.weekday()]

    training_days = [
        d.strip() for d in (user.get("training_days") or "").split(",") if d.strip()
    ]
    is_training_day = today_day in training_days

    # Verificar overrides ANTES de decidir si es día de descanso.
    # Un override puede mover una sesión a un día que normalmente es descanso
    # (ej: bot pasa la sesión del viernes al sábado). En ese caso la app debe
    # mostrar la sesión aunque sábado no esté en training_days.
    today_str = today.strftime("%Y-%m-%d")
    overrides = _store.get_active_overrides(uid)
    today_override = next(
        (ov for ov in overrides if ov["target_date"] == today_str), None
    )

    # Un override con ejercicios estructurados convierte cualquier día en día de
    # entrenamiento; un override de texto (sin bullets SxR) no lo hace.
    override_exercises: list[dict] = []
    if today_override:
        override_exercises = _parse_session_exercises(today_override["modification"])

    has_override_session = bool(override_exercises)

    if not is_training_day and not has_override_session:
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

    # Día de entrenamiento: extraer plan de la rutina base
    routine = _store.get_active_routine(uid)
    exercises: list[dict] = []
    day_name = ""

    if routine and is_training_day:
        section = _extract_day_section(routine["routine_text"], today_day)
        if section:
            # Extraer nombre del bloque (primera línea: "📋 DÍA 2 — TRACCIÓN (Martes)")
            first_line = section.split("\n")[0].strip()
            day_name = re.sub(r"^[^\w]+", "", first_line).strip()  # quitar emojis/separadores
            exercises = _parse_session_exercises(section)
            _apply_progression_targets(uid, exercises)

    # Si el override tiene ejercicios estructurados, reemplaza el plan base.
    # Aplica tanto en días normales (sesión modificada) como en días de descanso
    # (sesión movida desde otro día).
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

    [CONCEPTO: Agente como experto — sin reglas hardcodeadas]
    Le pasamos datos crudos (series, RIR, historial) y el perfil del usuario.
    El agente usa su conocimiento de entrenamiento para decidir la carga,
    pudiendo aplicar periodización, gestión de fatiga u otras consideraciones
    que reglas determinísticas no capturarían.
    """
    today_by_ex: dict[str, list[dict]] = {}
    for s in today_sets:
        today_by_ex.setdefault(s["exercise"], []).append(s)

    lines_today = []
    for ex, sets in today_by_ex.items():
        series_str = "  ".join(
            f"S{i+1}: {s['reps']}r @{s['weight_kg']}kg"
            + (f" RIR{s['rir']}" if s.get("rir") is not None else "")
            for i, s in enumerate(sets)
        )
        lines_today.append(f"• {ex}: {series_str}")

    lines_hist = []
    for ex, records in history.items():
        if not records:
            continue
        rec_str = " | ".join(
            f"{r['reps']}r @{r['weight_kg']}kg"
            + (f" RIR{r['rir']}" if r.get("rir") is not None else "")
            + f" [{r['session_date']}]"
            for r in records
        )
        lines_hist.append(f"• {ex}: {rec_str}")

    return f"""Eres Heracles, entrenador experto en fuerza e hipertrofia.

PERFIL DEL USUARIO:
• Nombre: {user.get('name', '?')}
• Objetivo: {user.get('goal', '?')}
• Nivel: {user.get('experience_level', '?')}
• Equipamiento: {user.get('home_equipment_detail') or user.get('equipment', '?')}

ESCALA RIR (Repeticiones en Recámara) — IMPORTANTE:
RIR 0 = fallo total (0 reps restantes, máximo esfuerzo)
RIR 1 = 1 rep restante, muy cerca del fallo
RIR 2 = 2 reps restantes, buena intensidad
RIR 3 = 3 reps restantes
RIR 4 = 4 reps restantes
RIR 5 = 5+ reps restantes, muy fácil/liviano
→ RIR bajo (0-2) = peso desafiante. RIR alto (4-5) = peso demasiado liviano, subir carga.

SESIÓN COMPLETADA HOY:
{chr(10).join(lines_today) or 'Sin series registradas'}

HISTORIAL RECIENTE (últimas sesiones registradas por ejercicio):
{chr(10).join(lines_hist) or 'Sin historial previo'}

Basándote en tu criterio como entrenador experto, el perfil del usuario,
el rendimiento de hoy (series, repeticiones y RIR) y la tendencia del historial,
calcula el peso que debería usar en la PRÓXIMA sesión para cada ejercicio.

Responde ÚNICAMENTE con JSON válido, sin texto adicional ni markdown:
[
  {{"exercise": "nombre exacto del ejercicio", "next_weight": 32.5, "next_reps": "8-10", "basis": "justificación breve en ≤10 palabras"}},
  ...
]
next_reps es el rango de reps recomendado para la próxima sesión (ej: "8-10", "10-12", "3x8").
Si el rango actual es correcto, repite el mismo valor."""


@router.post("/api/session/finish")
async def finish_session(user: dict = Depends(get_current_user)) -> dict:
    """
    Calcula y persiste la progresión de carga para la próxima sesión.

    Flujo:
    1. Series completadas hoy → agrupadas por ejercicio
    2. Historial de las últimas 5 sesiones por ejercicio
    3. Agente LLM analiza y devuelve JSON con next_weight por ejercicio
    4. Persistir en progression_targets — próxima sesión ya lleva el peso progresado
    5. Devolver sugerencias al frontend para mostrar en el resumen

    [CONCEPTO: LLM directo vs LangGraph para tareas de análisis]
    Para análisis de una sola pasada sin tool calls ni memoria conversacional,
    invocar el LLM directamente es más rápido y limpio que pasarlo por el grafo.
    LangGraph aporta valor cuando hay ciclos razonamiento ↔ herramientas.
    """
    from langchain_openai import ChatOpenAI
    import json as _json

    uid = user["telegram_id"]
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today_str = datetime.datetime.now(tz).date().strftime("%Y-%m-%d")

    today_sets = _store.get_today_workouts(uid)
    if not today_sets:
        return {"suggestions": []}

    exercise_names = list({s["exercise"] for s in today_sets})
    history = _store.get_history_for_exercises(uid, exercise_names, per_exercise=5)

    prompt = _build_progression_prompt(user, today_sets, history)

    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_key=settings.DEEPSEEK_API_KEY,
        openai_api_base="https://api.deepseek.com",
        temperature=0.2,  # baja temperatura para respuestas consistentes en cálculos
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    # Limpiar posible bloque ```json ... ``` que el LLM a veces agrega
    try:
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        suggestions: list[dict] = _json.loads(raw)
    except Exception:
        return {"suggestions": [], "error": "No se pudo parsear la respuesta del agente"}

    # Persistir cada sugerencia
    for item in suggestions:
        ex = item.get("exercise", "").strip()
        nw = item.get("next_weight")
        if ex and nw is not None:
            _store.save_progression_target(
                user_id=uid,
                exercise=ex,
                next_weight=float(nw),
                basis=item.get("basis", ""),
                session_date=today_str,
                next_reps=item.get("next_reps") or None,
            )

    return {"suggestions": suggestions}
