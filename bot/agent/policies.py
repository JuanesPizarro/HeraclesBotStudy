from bot.agent.contracts import Intent


TOOLS_BY_INTENT: dict[Intent, list[str]] = {
    Intent.TODAY_PLAN: [],
    Intent.ROUTINE: [],
    Intent.HISTORY: [],
    Intent.LOG_WORKOUT: ["save_workout"],
    Intent.MODIFY_SESSION: ["create_session_override_draft"],
    Intent.CREATE_ROUTINE: [
        "create_routine_draft",
        "update_training_days",
        "update_training_schedule",
    ],
    Intent.EVALUATE_SESSION: [],
    Intent.UPDATE_PROFILE: [
        "create_profile_change_draft",
        "update_training_days",
        "update_training_schedule",
    ],
    Intent.LIMITATION: ["create_session_override_draft"],
    Intent.OUT_OF_SCOPE: [],
}


PAIN_SIGNALS = (
    "dolor",
    "duele",
    "molestia",
    "pinchazo",
    "punzada",
    "lesión",
    "lesion",
)


def allowed_tools_for_intent(intent: Intent) -> list[str]:
    return TOOLS_BY_INTENT[intent]


def text_reports_pain(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(signal in lowered for signal in PAIN_SIGNALS)
