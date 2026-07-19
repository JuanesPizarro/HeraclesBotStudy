from bot.agent.contracts import Intent
from bot.agent import policies


def classify_intent_text(message: str) -> Intent:
    text = message.lower().strip()

    if any(
        phrase in text
        for phrase in (
            "qué me corresponde hoy",
            "que me corresponde hoy",
            "plan de hoy",
            "rutina de hoy",
            "entreno hoy",
        )
    ):
        return Intent.TODAY_PLAN
    if any(
        phrase in text
        for phrase in ("historial", "últimos entrenamientos", "ultimos entrenamientos")
    ):
        return Intent.HISTORY
    if any(
        phrase in text
        for phrase in (
            "evalúa",
            "evalua",
            "cómo estuvo mi entrenamiento",
            "como estuvo mi entrenamiento",
        )
    ):
        return Intent.EVALUATE_SESSION
    if any(phrase in text for phrase in ("me duele", "dolor", "molestia")):
        return Intent.LIMITATION
    if any(
        phrase in text
        for phrase in (
            "no tengo acceso",
            "no tengo tiempo",
            "juego fútbol",
            "juego futbol",
        )
    ):
        return Intent.MODIFY_SESSION
    if any(
        phrase in text
        for phrase in (
            "nueva rutina",
            "crea una rutina",
            "hacer una rutina",
            "cambiar rutina",
            "aplica esa rutina",
            "confirma esa rutina",
        )
    ):
        return Intent.CREATE_ROUTINE
    if any(
        phrase in text
        for phrase in (
            "mi objetivo",
            "objetivo",
            "equipamiento",
            "mancuernas",
            "barra",
            "banco",
        )
    ):
        return Intent.UPDATE_PROFILE
    if any(char.isdigit() for char in text) and any(
        word in text for word in ("kg", "reps", "series", "x")
    ):
        return Intent.LOG_WORKOUT
    return Intent.OUT_OF_SCOPE


def allowed_tools_for_intent(intent: Intent) -> list[str]:
    return policies.allowed_tools_for_intent(intent)
