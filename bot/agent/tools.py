import datetime
import zoneinfo

from langchain_core.tools import tool

from bot.config import settings
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


@tool
def save_workout(
    user_id: str, exercise: str, sets: int, reps: int, weight_kg: float
) -> str:
    """
    Guarda un ejercicio completado en el historial del usuario.
    Úsala cuando el usuario reporte haber completado series de un ejercicio.

    Args:
        user_id: ID de Telegram del usuario (disponible en el sistema)
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
    workout_id = _store.save_workout(user_id, exercise, sets, reps, weight_kg)
    return (
        f"Entrenamiento guardado correctamente.\n"
        f"Ejercicio: {exercise} | {sets} series x {reps} reps @ {weight_kg}kg\n"
        f"ID de registro: {workout_id}"
    )


@tool
def update_goal(user_id: str, new_goal: str) -> str:
    """
    Actualiza el objetivo de entrenamiento del usuario.
    Úsala cuando el usuario mencione explícitamente un nuevo objetivo
    (perder grasa, ganar masa, mejorar resistencia, preparar competencia, etc.).

    Args:
        user_id: ID de Telegram del usuario
        new_goal: Descripción del nuevo objetivo en palabras del usuario
    """
    _store.update_goal(user_id, new_goal)
    return f"Objetivo actualizado: {new_goal}"


@tool
def update_equipment(user_id: str, equipment_detail: str) -> str:
    """
    Actualiza la lista de implementos disponibles del usuario.
    Úsala cuando el usuario mencione que consiguió equipamiento nuevo
    o que ya no tiene algún implemento.

    IMPORTANTE: el argumento debe ser la lista COMPLETA actualizada,
    no solo los cambios. Combina lo actual con las modificaciones antes de llamar.

    Args:
        user_id: ID de Telegram del usuario
        equipment_detail: Lista completa de implementos separados por coma
                          (ej: "barra olímpica, mancuernas 2-20 kg, banco ajustable, paralelas")
    """
    _store.update_equipment(user_id, equipment_detail)
    return f"Equipamiento actualizado correctamente: {equipment_detail}"


@tool
def save_routine(
    user_id: str,
    routine_text: str,
    training_days: str | None = None,
) -> str:
    """
    Guarda o reemplaza la rutina principal del usuario en la base de datos.
    Úsala cuando el usuario pida guardar, confirmar o establecer una rutina
    como su rutina principal (frases como "guárdala", "es mi nueva rutina",
    "quédate con esa", "actualiza mi rutina", etc.).

    IMPORTANTE: routine_text debe ser el texto COMPLETO de la rutina con todos
    los días, ejercicios y detalles. Copia exactamente la rutina que le mostraste
    al usuario — no la resumas ni la acortes.

    Args:
        user_id: ID de Telegram del usuario (disponible en el sistema)
        routine_text: Texto completo de la rutina con todos los días y ejercicios
        training_days: Días de entrenamiento separados por coma en español y minúsculas
                       (ej: "lunes,martes,jueves,viernes,sábado"). Solo proporciona
                       este argumento si la nueva rutina cambia los días de entrenamiento.
    """
    _store.save_routine(user_id, routine_text)
    if training_days:
        _store.update_training_days(user_id, training_days)
        days_msg = f"\nDías de entrenamiento actualizados: {training_days}"
    else:
        days_msg = ""
    return f"Rutina guardada correctamente como rutina principal.{days_msg}"


@tool
def log_session_override(
    user_id: str,
    target_date: str,
    modification: str,
    scope: str,
    reason: str,
) -> str:
    """
    Registra una modificación TEMPORAL a la sesión de entrenamiento de una fecha específica.
    NO modifica la rutina general — solo crea una excepción para esa fecha.

    Úsala cuando el usuario mencione un cambio que NO es permanente:
    - Actividad extra ese día (fútbol, partido, caminata larga...)
    - Molestia o dolor puntual
    - Falta de equipamiento ese día
    - Cambio de día de entrenamiento esa semana

    Args:
        user_id: ID de Telegram del usuario
        target_date: Fecha afectada en formato YYYY-MM-DD (ej: "2026-06-03")
        modification: Descripción concreta del ajuste para esa sesión
                      (ej: "Reducir volumen piernas al 50%. Cambiar sentadilla por peso muerto ligero.
                            Agregar 10 min de movilidad de cadera post-sesión.")
        scope: "day" = solo ese día | "week" = toda esa semana
        reason: Motivo breve (ej: "fútbol martes tarde", "dolor rodilla izquierda")
    """
    override_id = _store.save_session_override(
        user_id=user_id,
        target_date=target_date,
        scope=scope,
        modification=modification,
        reason=reason,
    )
    return (
        f"Modificación registrada para {target_date} (alcance: {scope}).\n"
        f"Ajuste: {modification}\n"
        f"Motivo: {reason}\n"
        f"ID: {override_id}"
    )


@tool
def save_progression_target(
    user_id: str,
    exercise: str,
    next_weight: float,
    next_reps: str,
    next_sets: int,
    basis: str,
) -> str:
    """
    Persiste el objetivo de progresión (peso, reps, series) de UN ejercicio
    para la próxima sesión. Úsala cuando evalúes una sesión o dictes ajustes
    de carga, repeticiones, series o tiempos — una llamada por ejercicio.

    El objetivo queda guardado en progression_targets (la app web precarga
    estos valores) y se reescribe en la rutina general persistida, igual que
    la progresión calculada al finalizar una sesión web.

    Args:
        user_id: ID de Telegram del usuario (disponible en el sistema)
        exercise: Nombre EXACTO del ejercicio tal como aparece en la rutina
        next_weight: Peso en kg para la próxima sesión (0 para peso corporal sin lastre)
        next_reps: Rango de reps objetivo (ej: "8-10"). Para ejercicios por
                   tiempo usa los segundos (ej: "40-45 seg")
        next_sets: Número de series para la próxima sesión (ej: 3)
        basis: Justificación breve en ≤10 palabras (ej: "RPE 10 en S3 → consolidar")
    """
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    session_date = datetime.datetime.now(tz).date().strftime("%Y-%m-%d")

    _store.save_progression_target(
        user_id=user_id,
        exercise=exercise,
        next_weight=next_weight,
        basis=basis,
        session_date=session_date,
        next_reps=next_reps or None,
        next_sets=next_sets or None,
    )

    # [CONCEPTO: Import diferido para evitar import circular]
    # nodes.py importa TOOLS desde este módulo; si aquí importáramos nodes
    # al inicio del archivo, Python fallaría al cargar (A importa B importa A).
    # Al importar dentro de la función, el import ocurre en tiempo de
    # ejecución, cuando ambos módulos ya están completamente cargados.
    from bot.agent.nodes import apply_progression_to_routine_text

    routine = _store.get_active_routine(user_id)
    if routine:
        updated_text = apply_progression_to_routine_text(routine["routine_text"], user_id)
        if updated_text != routine["routine_text"]:
            _store.update_active_routine_text(user_id, updated_text)

    weight_str = f"{next_weight} kg" if next_weight else "peso corporal"
    return (
        f"Progresión guardada para {exercise}: "
        f"{next_sets}x{next_reps} @ {weight_str} ({basis}). "
        f"La próxima sesión ya carga estos valores."
    )


# [CONCEPTO: Lista de tools mínima]
# 6 tools — todos de escritura. Las lecturas (perfil, rutina, historial,
# overrides activos) se inyectan en el system prompt sin costo extra.
TOOLS = [
    save_workout,
    update_goal,
    update_equipment,
    log_session_override,
    save_routine,
    save_progression_target,
]
