import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from bot.agent.contracts import Intent
from bot.agent import policies
from bot.config import settings


class IntentClassification(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=240)


_llm = ChatOpenAI(
    model="deepseek-chat",
    openai_api_key=settings.DEEPSEEK_API_KEY,
    openai_api_base="https://api.deepseek.com",
    temperature=0,
)

_CLASSIFIER_SYSTEM_PROMPT = """Eres un clasificador de intención para un bot de entrenamiento.
Devuelve SOLO JSON válido, sin markdown.

Intenciones permitidas:
- today_plan: el usuario pregunta qué toca hoy o si entrena hoy.
- routine: el usuario pide ver su rutina actual.
- history: el usuario pide historial o últimos entrenamientos.
- log_workout: el usuario reporta series/reps/peso ya realizadas.
- modify_session: cambio temporal para hoy, una sesión o esta semana por equipamiento, tiempo, dolor leve, agenda, deporte extra o lugar de entrenamiento.
- create_routine: crear/cambiar la rutina general o calendario permanente.
- evaluate_session: evaluar cómo estuvo una sesión.
- update_profile: cambiar datos permanentes del perfil, objetivo, equipamiento habitual o disponibilidad estable.
- limitation: dolor, lesión o molestia que requiere adaptar entrenamiento.
- out_of_scope: fuera de entrenamiento.

Reglas:
- Si el mensaje dice o implica "hoy", "esta sesión", "esta semana", "entreno en casa hoy" o una limitación puntual, prefiere modify_session sobre update_profile.
- Si el cambio es permanente o de equipamiento habitual, usa update_profile.
- Si no estás seguro, baja confidence.

Formato exacto:
{"intent":"modify_session","confidence":0.87,"reason":"limitación temporal de equipamiento"}
"""


def classify_intent_text(message: str) -> Intent:
    text = message.lower().strip()
    mentions_today = any(
        phrase in text
        for phrase in (
            "hoy",
            "entrenamiento de hoy",
            "entreno de hoy",
            "sesión de hoy",
            "sesion de hoy",
        )
    )

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
        for phrase in (
            "mi rutina",
            "rutina actual",
            "ver rutina",
            "muéstrame la rutina",
            "muestrame la rutina",
            "cuál es mi rutina",
            "cual es mi rutina",
        )
    ):
        return Intent.ROUTINE
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
    if mentions_today and any(
        phrase in text
        for phrase in (
            "solo tengo",
            "sólo tengo",
            "solo cuento con",
            "sólo cuento con",
            "tengo solo",
            "tengo sólo",
            "solo hay",
            "sólo hay",
            "únicamente tengo",
            "unicamente tengo",
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
            "cambio de rutina",
            "rutina general",
            "cambio entero a la rutina",
            "cambio de días",
            "cambio de dias",
            "cambiar días",
            "cambiar dias",
            "días de entrenamiento",
            "dias de entrenamiento",
            "aplica esa rutina",
            "confirma esa rutina",
            "confirmo esa rutina",
            "confirmo el cambio",
            "te confirmo el cambio",
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


def _has_temporal_signal(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "hoy",
            "esta sesión",
            "esta sesion",
            "sesión de hoy",
            "sesion de hoy",
            "entrenamiento de hoy",
            "entreno de hoy",
            "esta semana",
            "por hoy",
            "solo por hoy",
            "sólo por hoy",
        )
    )


def _should_review_with_llm(rule_intent: Intent, message: str) -> bool:
    text = message.lower().strip()
    if rule_intent == Intent.OUT_OF_SCOPE:
        return True
    if rule_intent == Intent.UPDATE_PROFILE and _has_temporal_signal(text):
        return True
    return False


def _parse_llm_classification(content: str) -> IntentClassification:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    return IntentClassification.model_validate(data)


def classify_intent_with_llm(message: str) -> IntentClassification | None:
    response = _llm.invoke(
        [
            SystemMessage(content=_CLASSIFIER_SYSTEM_PROMPT),
            HumanMessage(content=message),
        ]
    )
    content = response.content
    if isinstance(content, list):
        content = "".join(str(item) for item in content)
    try:
        return _parse_llm_classification(str(content))
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None


def classify_intent(message: str) -> Intent:
    rule_intent = classify_intent_text(message)
    if not _should_review_with_llm(rule_intent, message):
        return rule_intent

    try:
        llm_result = classify_intent_with_llm(message)
    except Exception:
        return rule_intent

    if llm_result is None or llm_result.confidence < 0.65:
        return rule_intent
    return llm_result.intent


def allowed_tools_for_intent(intent: Intent) -> list[str]:
    return policies.allowed_tools_for_intent(intent)
