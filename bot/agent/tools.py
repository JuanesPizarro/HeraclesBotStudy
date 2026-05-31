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
# Este es el patrón ReAct (Reasoning + Acting):
# "El agente razona y actúa alternando entre pensar y usar herramientas"
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
def get_recent_workouts(user_id: str, limit: int = 5) -> str:
    """
    Recupera el historial reciente de entrenamientos del usuario.
    Úsala cuando necesites ver qué ejercicios hizo el usuario para
    sugerir progresión de cargas o revisar su historial.

    Args:
        user_id: ID de Telegram del usuario
        limit: Cuántos registros mostrar (entre 1 y 10)
    """
    workouts = _store.get_recent_workouts(user_id, min(limit, 10))

    if not workouts:
        return "El usuario no tiene entrenamientos registrados todavía."

    lines = ["Historial reciente de entrenamientos:"]
    for w in workouts:
        date = w["logged_at"][:10]  # Solo la fecha (YYYY-MM-DD)
        lines.append(
            f"  • {w['exercise']}: {w['sets']}x{w['reps']} @ {w['weight_kg']}kg  [{date}]"
        )
    return "\n".join(lines)


@tool
def get_user_profile(user_id: str) -> str:
    """
    Obtiene el perfil completo de entrenamiento del usuario.
    Úsala SIEMPRE antes de generar una rutina o recomendación personalizada.
    El perfil contiene toda la información necesaria para tomar decisiones:
    disponibilidad, equipamiento, nivel, limitaciones físicas y objetivo.

    Args:
        user_id: ID de Telegram del usuario
    """
    # [CONCEPTO: Docstrings como instrucciones para el LLM]
    # El LLM lee este texto para decidir cuándo invocar el tool.
    # "SIEMPRE antes de generar una rutina" le da una regla clara y explícita.
    user = _store.get_user(user_id)
    if not user:
        return "Usuario no encontrado."

    if not user.get("onboarding_done"):
        return (
            f"Nombre: {user['name']}\n"
            "Perfil incompleto: el usuario no ha completado el onboarding. "
            "Pídele que envíe /start para configurar su perfil antes de generar una rutina."
        )

    # Construir la línea de equipamiento dejando explícito que la lista es exhaustiva.
    # Si el usuario entrena en casa, el detalle es la única fuente de verdad —
    # cualquier implemento no mencionado debe asumirse como NO disponible.
    if user["equipment"] == "casa con material" and user.get("home_equipment_detail"):
        equipment_line = (
            f"casa con material.\n"
            f"  ⚠️  SOLO cuenta con los siguientes implementos "
            f"(no asumir ningún otro):\n"
            f"  {user['home_equipment_detail']}"
        )
    elif user["equipment"] == "casa con material":
        equipment_line = "casa con material (sin detalle registrado)"
    else:
        equipment_line = user["equipment"]

    limitations = user.get("limitations") or "ninguna"

    return (
        f"=== PERFIL DE ENTRENAMIENTO ===\n"
        f"Nombre: {user['name']}\n"
        f"\n--- Logística ---\n"
        f"Días/semana disponibles: {user['days_per_week']}\n"
        f"Tiempo por sesión: {user['session_time_minutes']} minutos\n"
        f"Equipamiento: {equipment_line}\n"
        f"\n--- Perfil físico ---\n"
        f"Nivel de experiencia: {user['experience_level']}\n"
        f"Actividad diaria: {user['daily_activity']}\n"
        f"Lesiones / limitaciones: {limitations}\n"
        f"\n--- Objetivo ---\n"
        f"Meta principal: {user['goal']}\n"
        f"Prueba de nivel solicitada: {'sí' if user.get('level_test_requested') else 'no'}\n"
        f"==============================="
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


# [CONCEPTO: Lista de tools que le pasamos al LLM]
# Agrupamos todos los tools en una lista para pasarlos al modelo.
# LangChain convierte cada @tool en un JSON Schema que el LLM entiende.
# En proyectos grandes, organiza los tools por dominio (workout_tools, nutrition_tools, etc.)
TOOLS = [save_workout, get_recent_workouts, get_user_profile, update_goal]
