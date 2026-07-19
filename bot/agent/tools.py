from langchain_core.tools import tool

from bot.agent.runtime import require_agent_context
from bot.storage.user_store import UserStore

# =====================================================================
# [CONCEPTO: Tool Use / Function Calling — Clave en AI Engineering]
#
# Un "tool" es una función Python que el LLM puede decidir invocar.
# Flujo completo:
#   1. Le enviamos al LLM la lista de tools como JSON Schema
#   2. El LLM analiza el mensaje y decide si necesita llamar algún tool
#   3. Si lo necesita, devuelve un "tool_call" con nombre + argumentos
#      (el LLM NO ejecuta nada — solo describe qué quiere llamar)
#   4. Nuestro código ejecuta la función real
#   5. El resultado vuelve al LLM como un ToolMessage
#   6. El LLM usa ese resultado para formular su respuesta final
#
# [CONCEPTO: Principio de mínimos tools — clave para SaaS]
# Solo registramos tools para operaciones de ESCRITURA que el LLM
# debe decidir cuándo ejecutar. Las operaciones de LECTURA (perfil,
# rutina, historial) se inyectan en el system prompt ANTES de llamar
# al LLM — así el LLM ya tiene todo el contexto en la primera llamada
# y no necesita "pedir" datos con tool calls extra.
#
# Regla: tool = acción con efecto secundario decidida por el LLM
#         contexto = datos que el código inyecta sin involucrar al LLM
#
# Aprende más:
# - Paper: "ReAct: Synergizing Reasoning and Acting in Language Models" (2022)
# - Docs: https://python.langchain.com/docs/concepts/tools/
# =====================================================================

_store = UserStore()

_DAY_ALIASES = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miércoles",
    "miércoles": "miércoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sábado",
    "sábado": "sábado",
    "domingo": "domingo",
}


@tool
def save_workout(exercise: str, sets: int, reps: int, weight_kg: float) -> str:
    """
    Guarda un ejercicio completado en el historial del usuario.
    Úsala cuando el usuario reporte haber completado series de un ejercicio.

    Args:
        exercise: Nombre del ejercicio (ej: "Press de banca", "Sentadilla", "Peso muerto")
        sets: Número de series completadas
        reps: Repeticiones por serie
        weight_kg: Peso en kilogramos (usa 0 para ejercicios de peso corporal)
    """
    # [CONCEPTO: Docstrings como instrucciones para el LLM]
    # El LLM lee el docstring para entender CUÁNDO y CÓMO usar el tool.
    # Un docstring bien escrito = el LLM usa el tool en el momento correcto
    # con los argumentos correctos. Trata el docstring como si le explicaras
    # el tool a un asistente humano que no conoce tu sistema.
    user_id = require_agent_context().user_id
    workout_id = _store.save_workout(user_id, exercise, sets, reps, weight_kg)
    return (
        f"Entrenamiento guardado correctamente.\n"
        f"Ejercicio: {exercise} | {sets} series x {reps} reps @ {weight_kg}kg\n"
        f"ID de registro: {workout_id}"
    )


@tool
def create_profile_change_draft(field: str, new_value: str, reason: str = "") -> str:
    """
    Crea un borrador de cambio de perfil pendiente de confirmación.
    Úsala para cambios permanentes como objetivo o equipamiento.

    Args:
        field: Campo a cambiar. Usa solo "goal" o "home_equipment_detail".
        new_value: Nuevo valor propuesto.
        reason: Motivo breve del cambio.
    """
    user_id = require_agent_context().user_id
    if field not in {"goal", "home_equipment_detail"}:
        raise ValueError("Unsupported profile field")
    draft_id = _store.create_profile_change_draft(
        user_id, field, new_value, reason or None
    )
    return (
        f"Borrador de cambio de perfil creado con ID {draft_id}. Requiere confirmación."
    )


@tool
def update_training_days(training_days: str, reason: str = "") -> str:
    """
    Actualiza directamente los días permanentes de entrenamiento ya confirmados.

    Úsala SOLO cuando el usuario confirme explícitamente un cambio de calendario
    o distribución semanal y los ejercicios de la rutina se mantienen. No crea
    borrador porque no reemplaza la rutina activa.

    NO la uses si el cambio altera ejercicios, series, repeticiones, pesos o la
    estructura completa de la rutina; en ese caso usa create_routine_draft.

    Args:
        training_days: Días de entrenamiento separados por coma en español
                       (ej: "domingo,lunes,miércoles,jueves,viernes").
        reason: Motivo breve del cambio.
    """
    user_id = require_agent_context().user_id
    normalized_days = []
    for raw_day in training_days.split(","):
        key = raw_day.strip().lower()
        if not key:
            continue
        day = _DAY_ALIASES.get(key)
        if not day:
            raise ValueError(f"Unsupported training day: {raw_day}")
        if day not in normalized_days:
            normalized_days.append(day)
    if not normalized_days:
        raise ValueError("At least one training day is required")

    normalized = ",".join(normalized_days)
    _store.update_training_days(user_id, normalized)
    suffix = f" Motivo: {reason}" if reason else ""
    return f"Días de entrenamiento actualizados: {normalized}.{suffix}"


@tool
def create_routine_draft(
    routine_text: str,
    training_days: str | None = None,
) -> str:
    """
    Guarda una rutina como borrador pendiente de confirmación explícita.
    Úsala cuando el usuario pida preparar, guardar o establecer una rutina.

    IMPORTANTE: routine_text debe ser el texto COMPLETO de la rutina con todos
    los días, ejercicios y detalles. Copia exactamente la rutina que le mostraste
    al usuario — no la resumas ni la acortes.

    Args:
        routine_text: Texto completo de la rutina con todos los días y ejercicios
        training_days: Días de entrenamiento separados por coma en español y minúsculas
                       (ej: "lunes,martes,jueves,viernes,sábado"). Solo proporciona
                       este argumento si la nueva rutina cambia los días de entrenamiento.
    """
    user_id = require_agent_context().user_id
    draft_id = _store.create_routine_draft(user_id, routine_text)
    return (
        f"Borrador de rutina creado con ID {draft_id}. "
        "Requiere confirmación para activarse."
    )


@tool
def create_session_override_draft(
    target_date: str,
    modification: str,
    scope: str,
    reason: str,
) -> str:
    """
    Crea un borrador de modificación temporal de sesión.
    NO modifica la rutina general ni activa el cambio sin confirmación.

    Úsala cuando el usuario mencione un cambio que NO es permanente:
    - Actividad extra ese día (fútbol, partido, caminata larga...)
    - Molestia o dolor puntual
    - Falta de equipamiento ese día
    - Cambio de día de entrenamiento esa semana

    Args:
        target_date: Fecha afectada en formato YYYY-MM-DD (ej: "2026-06-03")
        modification: Descripción concreta del ajuste para esa sesión
                      (ej: "Reducir volumen piernas al 50%. Cambiar sentadilla por peso muerto ligero.
                            Agregar 10 min de movilidad de cadera post-sesión.")
        scope: "day" = solo ese día | "week" = toda esa semana
        reason: Motivo breve (ej: "fútbol martes tarde", "dolor rodilla izquierda")
    """
    user_id = require_agent_context().user_id
    override_id = _store.create_session_override_draft(
        user_id=user_id,
        target_date=target_date,
        scope=scope,
        modification=modification,
        reason=reason,
    )
    return (
        f"Borrador de modificación creado para {target_date} (alcance: {scope}).\n"
        f"Ajuste: {modification}\n"
        f"Motivo: {reason}\n"
        f"ID: {override_id}. Requiere confirmación."
    )


# [CONCEPTO: Lista de tools mínima]
# Tools de escritura. Las lecturas (perfil, rutina, historial,
# overrides activos) se inyectan en el system prompt sin costo extra.
TOOLS = [
    save_workout,
    create_profile_change_draft,
    update_training_days,
    create_session_override_draft,
    create_routine_draft,
]
