# =====================================================================
# [CONCEPTO: ConversationHandler — máquina de estados finitos (FSM)]
#
# Un ConversationHandler implementa el patrón FSM (Finite State Machine):
# - ESTADOS: números enteros que identifican el paso actual del usuario
# - TRANSICIONES: los handlers registrados en cada estado
# - BRANCHING CONDICIONAL: un handler puede devolver estados DISTINTOS
#   según la respuesta del usuario (ver received_equipment más abajo)
#
# La misma lógica subyace en LangGraph (StateGraph) y en flujos de UI
# complejos. Dominar FSM es esencial en AI Engineering y backend.
#
# Flujo completo (4 secciones + rama condicional):
#
#   /start
#     └─▶ SECCIÓN 1: Logística
#           ├─ ASK_DAYS          → ¿cuántos días/semana?
#           ├─ ASK_SESSION_TIME  → ¿cuánto tiempo por sesión?
#           └─ ASK_EQUIPMENT     → ¿dónde y con qué?
#                 ├─ gym / calistenia  ──────────────────────────────────┐
#                 └─ casa con material → ASK_HOME_EQUIPMENT (texto libre)┘
#                                             ↓
#     └─▶ SECCIÓN 2: Perfil                  ↓ (ambas ramas convergen aquí)
#           ├─ ASK_EXPERIENCE    → ¿nivel de experiencia?
#           ├─ ASK_DAILY_ACTIVITY→ ¿actividad diaria?
#           └─ ASK_LIMITATIONS   → ¿lesiones o molestias? (texto libre)
#     └─▶ SECCIÓN 3: Objetivo
#           └─ ASK_GOAL         → ¿meta principal?
#     └─▶ SECCIÓN 4: Prueba de nivel (opcional)
#           └─ ASK_LEVEL_TEST   → ¿quieres test de valoración inicial?
#     └─▶ END
#
# [CONCEPTO: InlineKeyboardMarkup]
# Botones embebidos en el mensaje → generan callback_query al pulsarlos.
# No aparecen en el historial → UX más limpia que ReplyKeyboard.
# Max 64 bytes por callback_data (límite de la API de Telegram).
#
# Aprende más: https://docs.python-telegram-bot.org/en/stable/telegram.ext.conversationhandler.html
# =====================================================================

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from bot.storage.user_store import UserStore
from bot.config import settings

logger = logging.getLogger(__name__)
_store = UserStore()


class _NeedsOnboardingFilter(filters.MessageFilter):
    """
    Filtro que devuelve True solo para usuarios activos con onboarding incompleto.

    [CONCEPTO: Custom MessageFilter en PTB]
    Subclasear filters.MessageFilter permite crear condiciones de enrutamiento
    arbitrarias basadas en el contenido del mensaje O en estado externo (DB).
    El filtro se evalúa en check_update(), antes de ejecutar el handler.
    Aquí lo usamos para que el ConversationHandler intercepte mensajes de
    usuarios que no terminaron su perfil, sin afectar a los que sí lo hicieron.
    """
    def filter(self, message) -> bool:
        if not message.from_user:
            return False
        user = _store.get_user(str(message.from_user.id))
        if not user:
            return False
        return (
            user.get("status") == "active"
            and not bool(user.get("onboarding_done"))
        )


_needs_onboarding = _NeedsOnboardingFilter()


async def _notify_admin_new_user(
    context: ContextTypes.DEFAULT_TYPE, user_id: str, user_name: str
) -> None:
    """
    Envía al admin una notificación con botones para aprobar o bloquear.

    [CONCEPTO: Mensajes proactivos del bot]
    El bot normalmente responde a mensajes entrantes. Pero también puede
    enviar mensajes sin que nadie le hable, usando context.bot.send_message().
    Esto es lo mismo que hace el webhook de n8n para recordatorios.
    """
    if not settings.ADMIN_TELEGRAM_ID:
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"access_approve_{user_id}"),
            InlineKeyboardButton("❌ Bloquear", callback_data=f"access_block_{user_id}"),
        ]
    ])
    await context.bot.send_message(
        chat_id=settings.ADMIN_TELEGRAM_ID,
        text=(
            "⚠️ *Nueva solicitud de acceso*\n\n"
            f"👤 {user_name}\n"
            f"🆔 `{user_id}`"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

# Estados — un entero por paso.
# [CONCEPTO: range() para constantes secuenciales]
# Equivale a ASK_DAYS=0, ASK_SESSION_TIME=1, ..., ASK_LEVEL_TEST=8.
(
    ASK_DAYS,
    ASK_SESSION_TIME,
    ASK_EQUIPMENT,
    ASK_HOME_EQUIPMENT,
    ASK_EXPERIENCE,
    ASK_DAILY_ACTIVITY,
    ASK_LIMITATIONS,
    ASK_GOAL,
    ASK_LEVEL_TEST,
) = range(9)

# ── Días de la semana ─────────────────────────────────────────────────
# Usamos claves ASCII en callback_data (máx 64 bytes, sin tildes)
# pero guardamos el nombre completo en español en la DB.
#
# [CONCEPTO: Multi-select con InlineKeyboard]
# Los botones normales de Telegram son single-select (cada tap avanza).
# Para multi-select usamos context.user_data como estado intermedio:
#   1. El usuario toca días → toggleamos en context.user_data["selected_days"]
#   2. Reconstruimos el teclado con ✅ en los seleccionados
#   3. Un botón "Confirmar" finaliza la selección y avanza al siguiente paso
DAYS_ORDER = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# callback_data → nombre completo (ASCII key, valor con tilde)
DAYS_CALLBACK: dict[str, str] = {
    "day_lun": "lunes",
    "day_mar": "martes",
    "day_mie": "miércoles",
    "day_jue": "jueves",
    "day_vie": "viernes",
    "day_sab": "sábado",
    "day_dom": "domingo",
}
# Inverso para toggle
DAYS_CALLBACK_BY_NAME: dict[str, str] = {v: k for k, v in DAYS_CALLBACK.items()}


def _build_days_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    """
    Construye el teclado de días con checkmarks en los seleccionados.
    Se llama cada vez que el usuario toca un día para reconstruirlo.

    [CONCEPTO: UI reactiva sin framework]
    En lugar de un framework (React, Vue), Alpine.js o similar, usamos
    query.edit_message_reply_markup() para actualizar el teclado in-place.
    El estado vive en context.user_data (lado servidor), no en el cliente.
    """
    rows = []
    pairs = list(DAYS_CALLBACK.items())
    for i in range(0, len(pairs), 2):
        row = []
        for cb, name in pairs[i:i + 2]:
            label = f"✅ {name.capitalize()}" if name in selected else name.capitalize()
            row.append(InlineKeyboardButton(label, callback_data=cb))
        rows.append(row)
    count = len(selected)
    confirm_label = f"Confirmar ({count} día{'s' if count != 1 else ''})" if count else "Selecciona al menos 2 días"
    rows.append([InlineKeyboardButton(confirm_label, callback_data="days_confirm")])
    return InlineKeyboardMarkup(rows)


SESSION_TIME_MAP: dict[str, int] = {
    "time_30": 30,
    "time_60": 60,
    "time_90": 90,
}
SESSION_TIME_LABELS: dict[str, str] = {
    "time_30": "30 minutos (express)",
    "time_60": "1 hora",
    "time_90": "1 hora 30 min o más",
}

EQUIPMENT_MAP: dict[str, str] = {
    "equip_gym":      "gym completo",
    "equip_casa":     "casa con material",
    "equip_corporal": "peso corporal / calistenia",
}

EXPERIENCE_MAP: dict[str, str] = {
    "exp_principiante": "principiante",
    "exp_intermedio":   "intermedio",
    "exp_avanzado":     "avanzado",
}

ACTIVITY_MAP: dict[str, str] = {
    "act_sedentario": "sedentario (escritorio, poco movimiento)",
    "act_moderado":   "moderadamente activo (de pie parte del día)",
    "act_activo":     "muy activo (trabajo físico, mucho movimiento)",
}

GOAL_MAP: dict[str, str] = {
    "goal_hipertrofia": "ganar masa muscular (hipertrofia)",
    "goal_grasa":       "perder grasa corporal",
    "goal_fuerza":      "ganar fuerza pura",
    "goal_salud":       "mejorar salud, condición física y movilidad",
}

# ── Teclados inline ───────────────────────────────────────────────────

SESSION_TIME_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⚡ 30 minutos (express)",   callback_data="time_30")],
    [InlineKeyboardButton("🕐 1 hora",                 callback_data="time_60")],
    [InlineKeyboardButton("🕑 1 hora 30 min o más",    callback_data="time_90")],
])

EQUIPMENT_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🏋️ Gimnasio completo",           callback_data="equip_gym")],
    [InlineKeyboardButton("🏠 En casa con material",         callback_data="equip_casa")],
    [InlineKeyboardButton("🤸 Peso corporal / Calistenia",   callback_data="equip_corporal")],
])

EXPERIENCE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🌱 Principiante  (menos de 1 año)", callback_data="exp_principiante")],
    [InlineKeyboardButton("📈 Intermedio  (1 a 3 años)",        callback_data="exp_intermedio")],
    [InlineKeyboardButton("🏆 Avanzado  (más de 3 años)",       callback_data="exp_avanzado")],
])

ACTIVITY_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("💻 Sedentario (escritorio)",       callback_data="act_sedentario")],
    [InlineKeyboardButton("🚶 Moderadamente activo",          callback_data="act_moderado")],
    [InlineKeyboardButton("⚒️ Muy activo (trabajo físico)",   callback_data="act_activo")],
])

GOAL_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("💪 Ganar masa muscular (hipertrofia)", callback_data="goal_hipertrofia")],
    [InlineKeyboardButton("🔥 Perder grasa corporal",             callback_data="goal_grasa")],
    [InlineKeyboardButton("🏋️ Ganar fuerza pura",                callback_data="goal_fuerza")],
    [InlineKeyboardButton("🌿 Mejorar salud y movilidad",         callback_data="goal_salud")],
])

LEVEL_TEST_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Sí, asígname una prueba de nivel", callback_data="test_si")],
    [InlineKeyboardButton("🚀 No, empecemos directamente",       callback_data="test_no")],
])


# ─────────────────────────────────────────────────────────────────────
# Entrada — /start
# ─────────────────────────────────────────────────────────────────────

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point: valida acceso y lanza el onboarding o saluda.
    [DEBUG] Log temporal para diagnosticar inicio de onboarding.

    [CONCEPTO: Control de acceso en el entry point]
    Verificamos el status ANTES de cualquier lógica de onboarding.
    El admin siempre pasa — se auto-aprueba en el primer contacto.
    Los usuarios nuevos quedan en 'pending' hasta que el admin los apruebe.
    """
    user = update.effective_user
    user_id = str(user.id)
    logger.warning("DEBUG start_onboarding: user=%s via=%s", user_id, type(update.effective_message).__name__)
    is_new = _store.upsert_user(user_id, user.first_name)

    # El admin se auto-aprueba siempre
    if settings.ADMIN_TELEGRAM_ID and user_id == settings.ADMIN_TELEGRAM_ID:
        _store.update_user_status(user_id, "active")

    status = _store.get_user_status(user_id)

    if status == "pending":
        await update.message.reply_text(
            "⏳ *Tu solicitud de acceso está en revisión.*\n\n"
            "El administrador te notificará cuando sea aprobada.",
            parse_mode="Markdown",
        )
        if is_new:
            await _notify_admin_new_user(context, user_id, user.first_name)
        return ConversationHandler.END

    if status == "blocked":
        await update.message.reply_text(
            "❌ Tu acceso está bloqueado. Contacta al administrador."
        )
        return ConversationHandler.END

    if _store.is_onboarding_done(user_id):
        await update.message.reply_text(
            f"¡Hola de nuevo, {user.first_name}! 💪\n\n"
            "Tu perfil ya está listo. Pídeme que te genere una rutina "
            "o cuéntame tu entrenamiento de hoy.",
        )
        return ConversationHandler.END

    if is_new:
        intro = (
            f"¡Hola, {user.first_name}! 👋 Soy *Heracles*, tu entrenador personal.\n\n"
            "Para diseñarte la mejor rutina necesito conocerte bien. "
            "Vamos a repasar *4 puntos clave* — solo toma un par de minutos ⚡"
        )
    else:
        intro = (
            f"Hola {user.first_name}, todavía no terminaste tu perfil.\n\n"
            "Necesito estos datos para poder ayudarte 💪 "
            "Completemos los *4 puntos clave* — toma un par de minutos ⚡"
        )
    await update.message.reply_text(intro, parse_mode="Markdown")
    context.user_data["selected_days"] = []  # Inicializar selección vacía
    await update.message.reply_text(
        "─────────────────────────\n"
        "*📦 Sección 1 de 4 — Logística y disponibilidad*\n"
        "─────────────────────────\n\n"
        "1️⃣  ¿*Qué días de la semana* puedes entrenar?\n\n"
        "_Toca los días y luego confirma. Sé realista: mejor cumplir 3 que planificar 6 y fallar 3._",
        parse_mode="Markdown",
        reply_markup=_build_days_keyboard(set()),
    )
    return ASK_DAYS


# ─────────────────────────────────────────────────────────────────────
# Sección 1 — Logística
# ─────────────────────────────────────────────────────────────────────

async def toggle_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Alterna la selección de un día. Reconstruye el teclado con el nuevo estado.
    [DEBUG] Log temporal para diagnosticar callbacks de días.

    [CONCEPTO: callback_query.edit_message_reply_markup]
    A diferencia de edit_message_text (que reescribe todo el mensaje),
    edit_message_reply_markup solo actualiza los botones. Más eficiente
    y preserva el texto original.
    """
    logger.warning("DEBUG toggle_day: data=%s user=%s", update.callback_query.data, update.effective_user.id)
    query = update.callback_query
    await query.answer()

    day_name = DAYS_CALLBACK[query.data]
    selected = set(context.user_data.get("selected_days", []))

    if day_name in selected:
        selected.discard(day_name)
    else:
        selected.add(day_name)
    context.user_data["selected_days"] = list(selected)

    await query.edit_message_reply_markup(reply_markup=_build_days_keyboard(selected))
    return ASK_DAYS  # Permanece en el mismo estado hasta que confirme


async def confirm_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Valida la selección (mínimo 2 días) y avanza al paso de tiempo de sesión."""
    query = update.callback_query
    selected = set(context.user_data.get("selected_days", []))

    if len(selected) < 2:
        await query.answer("Selecciona al menos 2 días para continuar", show_alert=True)
        return ASK_DAYS

    await query.answer()

    # Ordenar según el orden natural de la semana
    days_sorted = [d for d in DAYS_ORDER if d in selected]
    context.user_data["training_days"] = ",".join(days_sorted)

    days_label = " • ".join(d.capitalize() for d in days_sorted)
    await query.edit_message_text(
        f"1️⃣  Días de entrenamiento: *{days_label}* ✅",
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="2️⃣  ¿De cuánto *tiempo dispones por sesión*?",
        parse_mode="Markdown",
        reply_markup=SESSION_TIME_KEYBOARD,
    )
    return ASK_SESSION_TIME


async def received_session_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data["session_time_minutes"] = SESSION_TIME_MAP[query.data]

    await query.edit_message_text(
        f"2️⃣  Tiempo/sesión: *{SESSION_TIME_LABELS[query.data]}* ✅",
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "3️⃣  ¿*Dónde vas a entrenar* y con qué equipamiento cuentas?\n\n"
            "_Si entrenas en casa con material propio, podrás detallar qué tienes._"
        ),
        parse_mode="Markdown",
        reply_markup=EQUIPMENT_KEYBOARD,
    )
    return ASK_EQUIPMENT


async def received_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Guarda el equipamiento.
    Si el usuario eligió 'casa con material', abre el estado ASK_HOME_EQUIPMENT
    para que detalle qué tiene. En los otros casos salta directamente a la Sección 2.

    [CONCEPTO: Branching condicional en ConversationHandler]
    Un handler puede devolver DISTINTOS estados según la lógica de negocio.
    Aquí implementamos una bifurcación sin necesidad de frameworks extra —
    solo un if/else en Python con valores de estado distintos.
    """
    query = update.callback_query
    await query.answer()

    equipment = EQUIPMENT_MAP[query.data]
    context.user_data["equipment"] = equipment

    await query.edit_message_text(
        f"3️⃣  Equipamiento: *{equipment}* ✅",
        parse_mode="Markdown",
    )

    if query.data == "equip_casa":
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "🏠  ¿Qué *material tienes en casa*? Lista todo lo que tengas.\n\n"
                "_Ejemplos: mancuernas ajustables de 2-20 kg, barra de dominadas, "
                "bandas elásticas de resistencia, barra olímpica con discos, "
                "TRX, banco, kettlebells..._\n\n"
                "Cuanto más detallado, mejor podré adaptar tu rutina."
            ),
            parse_mode="Markdown",
        )
        return ASK_HOME_EQUIPMENT

    # gym completo o calistenia: no hace falta más detalle
    context.user_data["home_equipment_detail"] = None
    return await _ask_experience(update.effective_chat.id, context)


async def received_home_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Guarda el detalle del material en casa y continúa con la Sección 2."""
    context.user_data["home_equipment_detail"] = update.message.text.strip()
    await update.message.reply_text("🏠  Material registrado ✅")
    return await _ask_experience(update.effective_chat.id, context)


# Helper interno: evita duplicar el mensaje de transición a Sección 2
async def _ask_experience(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "─────────────────────────\n"
            "*🧍 Sección 2 de 4 — Tu perfil y estado actual*\n"
            "─────────────────────────\n\n"
            "4️⃣  ¿Cuál es tu *nivel de experiencia* en entrenamiento de fuerza?"
        ),
        parse_mode="Markdown",
        reply_markup=EXPERIENCE_KEYBOARD,
    )
    return ASK_EXPERIENCE


# ─────────────────────────────────────────────────────────────────────
# Sección 2 — Perfil
# ─────────────────────────────────────────────────────────────────────

async def received_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data["experience_level"] = EXPERIENCE_MAP[query.data]

    await query.edit_message_text(
        f"4️⃣  Experiencia: *{EXPERIENCE_MAP[query.data]}* ✅",
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "5️⃣  ¿*A qué te dedicas* en tu día a día?\n\n"
            "_Esto afecta cuánta energía llevas al entreno "
            "y cuánto tiempo de recuperación necesitas._"
        ),
        parse_mode="Markdown",
        reply_markup=ACTIVITY_KEYBOARD,
    )
    return ASK_DAILY_ACTIVITY


async def received_daily_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data["daily_activity"] = ACTIVITY_MAP[query.data]

    await query.edit_message_text(
        f"5️⃣  Actividad diaria: *{ACTIVITY_MAP[query.data]}* ✅",
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "6️⃣  ¿Tienes alguna *lesión, molestia o limitación física*?\n\n"
            "_Cualquier dolor de rodilla, espalda, hombro, etc., es vital para "
            "elegir los ejercicios correctos._\n\n"
            "Si no tienes ninguna, escribe: *ninguna*"
        ),
        parse_mode="Markdown",
    )
    # A partir de aquí el estado ASK_LIMITATIONS espera texto libre,
    # no callback_query → por eso registramos un MessageHandler en ese estado.
    return ASK_LIMITATIONS


async def received_limitations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["limitations"] = update.message.text.strip()

    await update.message.reply_text(
        "6️⃣  Limitaciones registradas ✅\n\n"
        "─────────────────────────\n"
        "*🎯 Sección 3 de 4 — Tu objetivo*\n"
        "─────────────────────────\n\n"
        "7️⃣  ¿Cuál es tu *meta principal* en este momento?",
        parse_mode="Markdown",
        reply_markup=GOAL_KEYBOARD,
    )
    return ASK_GOAL


# ─────────────────────────────────────────────────────────────────────
# Sección 3 — Objetivo
# ─────────────────────────────────────────────────────────────────────

async def received_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data["goal"] = GOAL_MAP[query.data]

    await query.edit_message_text(
        f"7️⃣  Objetivo: *{GOAL_MAP[query.data]}* ✅",
        parse_mode="Markdown",
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "─────────────────────────\n"
            "*🔬 Sección 4 de 4 — Prueba de nivel (opcional)*\n"
            "─────────────────────────\n\n"
            "8️⃣  Para ajustar la intensidad desde el primer día, puedo asignarte "
            "una *prueba de valoración inicial* en tu próxima sesión.\n\n"
            "Consiste en medir tu fuerza base en movimientos clave "
            "(flexiones, sentadillas, plancha, etc.).\n\n"
            "¿Te gustaría hacerla?"
        ),
        parse_mode="Markdown",
        reply_markup=LEVEL_TEST_KEYBOARD,
    )
    return ASK_LEVEL_TEST


# ─────────────────────────────────────────────────────────────────────
# Sección 4 — Prueba de nivel y cierre
# ─────────────────────────────────────────────────────────────────────

async def received_level_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Persiste el perfil completo en un solo UPDATE atómico y cierra el flujo."""
    query = update.callback_query
    await query.answer()

    level_test = query.data == "test_si"
    user_id = str(update.effective_user.id)

    _store.save_onboarding(
        telegram_id=user_id,
        training_days=context.user_data["training_days"],
        session_time_minutes=context.user_data["session_time_minutes"],
        equipment=context.user_data["equipment"],
        home_equipment_detail=context.user_data.get("home_equipment_detail"),
        experience_level=context.user_data["experience_level"],
        daily_activity=context.user_data["daily_activity"],
        limitations=context.user_data["limitations"],
        goal=context.user_data["goal"],
        level_test_requested=level_test,
    )

    # [CONCEPTO: context.user_data.clear()]
    # Limpiamos el dict temporal una vez guardado en SQLite.
    # Sin esto, los datos del onboarding quedarían en memoria indefinidamente
    # y podrían confundir una futura sesión si el usuario resetea su perfil.
    context.user_data.clear()

    await query.edit_message_text("8️⃣  Preferencia guardada ✅", parse_mode="Markdown")

    nivel_test_texto = (
        "En tu próxima sesión te daré una *prueba de valoración* para calibrar tu nivel. 🔬"
        if level_test
        else "Empezamos directamente con tu rutina. 🚀"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "✅ *¡Perfil completo!*\n\n"
            f"{nivel_test_texto}\n\n"
            "Escríbeme *\"Genérame mi rutina\"* cuando quieras empezar, "
            "o cuéntame tu entrenamiento de hoy 🏋️"
        ),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────
# Fallback — input fuera del flujo durante el onboarding
# ─────────────────────────────────────────────────────────────────────

async def onboarding_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Rechaza cualquier mensaje que no sea la respuesta esperada en el paso actual.
    Aísla el flujo de onboarding del agente general hasta que el perfil esté completo.
    """
    await update.message.reply_text(
        "Estoy recopilando tu perfil de entrenamiento. 📋\n"
        "Responde con los botones de la pregunta anterior para continuar. "
        "Una vez terminemos podrás pedirme cualquier cosa."
    )


# ─────────────────────────────────────────────────────────────────────
# Factory — único símbolo público relevante para telegram.py
# ─────────────────────────────────────────────────────────────────────

def build_onboarding_handler() -> ConversationHandler:
    """
    Construye el ConversationHandler listo para registrar en la Application.

    [CONCEPTO: allow_reentry=True]
    Si el usuario envía /start en medio del onboarding, el handler
    reinicia el flujo en lugar de ignorar el comando.
    Esto evita que el usuario quede atrapado si cambia de opinión a mitad.
    """
    # [CONCEPTO: per_message=False en ConversationHandler]
    # Con per_message=False (default), el estado de la conversación se rastrea
    # por chat_id (y opcionalmente user_id), no por cada mensaje individual.
    # Es el comportamiento correcto para onboarding: un flujo por usuario,
    # no uno por mensaje. per_message=True se usa en conversaciones donde
    # múltiples flujos paralelos pueden estar activos simultáneamente.
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_onboarding),
            # Cualquier texto de un usuario activo con onboarding incompleto
            # lo redirige al flujo de onboarding en lugar del agente.
            # [CONCEPTO: entry_point con filtro de DB]
            # El filtro consulta SQLite en check_update() — solo True cuando
            # onboarding_done=0 y status='active', así los usuarios con perfil
            # completo caen al handle_message normal sin overhead extra.
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & _needs_onboarding,
                start_onboarding,
            ),
        ],
        states={
            ASK_DAYS: [
                CallbackQueryHandler(toggle_day, pattern="^day_(?!s_)"),  # day_lun, day_mar... (no days_confirm)
                CallbackQueryHandler(confirm_days, pattern="^days_confirm$"),
            ],
            ASK_SESSION_TIME: [
                CallbackQueryHandler(received_session_time, pattern="^time_"),
            ],
            ASK_EQUIPMENT: [
                CallbackQueryHandler(received_equipment, pattern="^equip_"),
            ],
            ASK_HOME_EQUIPMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_home_equipment),
            ],
            ASK_EXPERIENCE: [
                CallbackQueryHandler(received_experience, pattern="^exp_"),
            ],
            ASK_DAILY_ACTIVITY: [
                CallbackQueryHandler(received_daily_activity, pattern="^act_"),
            ],
            ASK_LIMITATIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_limitations),
            ],
            ASK_GOAL: [
                CallbackQueryHandler(received_goal, pattern="^goal_"),
            ],
            ASK_LEVEL_TEST: [
                CallbackQueryHandler(received_level_test, pattern="^test_"),
            ],
        },
        fallbacks=[
            # /start en medio del flujo reinicia el onboarding desde el principio
            CommandHandler("start", start_onboarding),
            MessageHandler(filters.TEXT & ~filters.COMMAND, onboarding_fallback),
        ],
        # allow_reentry=False (default): con la conversación activa, los entry_points
        # NO se evalúan. Esto evita que _needs_onboarding reinicie el flujo cuando el
        # usuario escribe texto en ASK_HOME_EQUIPMENT o ASK_LIMITATIONS.
        # /start sigue funcionando como re-entrada vía el CommandHandler en fallbacks.
        allow_reentry=False,
        per_message=False,
    )
