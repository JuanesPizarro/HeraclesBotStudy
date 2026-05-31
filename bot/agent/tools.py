from langchain_core.tools import tool
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


# [CONCEPTO: Lista de tools mínima]
# 3 tools — todos de escritura. Las lecturas (perfil, rutina, historial,
# overrides activos) se inyectan en el system prompt sin costo extra.
TOOLS = [save_workout, update_goal, log_session_override]
