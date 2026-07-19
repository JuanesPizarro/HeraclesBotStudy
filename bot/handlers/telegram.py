from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from bot.agent.intent import allowed_tools_for_intent, classify_intent_text
from bot.agent.nodes import ROUTINE_START, ROUTINE_END
from bot.storage.user_store import UserStore
from bot.config import settings
from bot.handlers.onboarding import build_onboarding_handler
from bot.observability import (
    anonymize_user_id,
    log_event,
    new_request_id,
    request_id_var,
)
from bot.services.agent_service import run_agent_message

# =====================================================================
# [CONCEPTO: Deep links y URLs personalizadas]
# En SaaS, cada usuario recibe un enlace único con su token.
# Esto evita compartir el Telegram ID en URLs públicas y permite
# revocar el acceso regenerando el token sin cambiar el usuario.
# =====================================================================

# =====================================================================
# [CONCEPTO: python-telegram-bot v20+]
# La librería oficial de Python para la Bot API de Telegram.
# A partir de v20 es completamente asíncrona (basada en asyncio).
#
# Arquitectura:
# - Application: contenedor principal (bot + dispatcher + updater)
# - Handler: asocia un tipo de update (mensaje, comando...) con una función
# - Update: objeto con toda la info de un mensaje entrante
# - Context: datos de la conversación actual
#
# Modos de recibir mensajes de Telegram:
# ┌──────────────────────────────────────────────────────────────────┐
# │  POLLING (desarrollo)                                            │
# │  Tu bot pregunta a Telegram: "¿hay mensajes nuevos?" cada N seg  │
# │  + Sin servidor público, funciona en localhost                   │
# │  - Menos eficiente, latencia mayor                               │
# ├──────────────────────────────────────────────────────────────────┤
# │  WEBHOOK (producción)                                            │
# │  Telegram envía mensajes a tu URL via HTTP POST                  │
# │  + Tiempo real, más eficiente                                    │
# │  - Requiere HTTPS y servidor público (VPS, Railway, Fly.io...)   │
# └──────────────────────────────────────────────────────────────────┘
#
# Aprende más: https://docs.python-telegram-bot.org/
# =====================================================================

_store = UserStore()


def _extract_and_save_routine(user_id: str, response_text: str) -> str:
    """
    Detecta el marcador de rutina en la respuesta del LLM, guarda en DB y lo elimina.

    [CONCEPTO: Marker pattern — persistencia sin tool call]
    En lugar de que el LLM llame un tool save_routine (=1 LLM call extra),
    le pedimos que envuelva la rutina en marcadores especiales.
    Este código Python los detecta y persiste sin involucrar al LLM.

    Resultado: 0 llamadas extra al LLM para guardar la rutina.
    Crítico para mantener costos bajos en SaaS con muchos usuarios.

    Retorna el texto limpio (sin marcadores) listo para enviar al usuario.
    """
    if ROUTINE_START not in response_text or ROUTINE_END not in response_text:
        return response_text

    try:
        start_idx = response_text.index(ROUTINE_START)
        end_idx = response_text.index(ROUTINE_END)

        routine_text = response_text[start_idx + len(ROUTINE_START) : end_idx].strip()

        # Guardar como borrador: pedir o recibir una rutina no reemplaza la activa.
        draft_id = _store.create_routine_draft(user_id, routine_text)

        # Devolver texto limpio: lo que va antes + la rutina + lo que va después
        before = response_text[:start_idx].strip()
        after = response_text[end_idx + len(ROUTINE_END) :].strip()

        confirmation_note = (
            f"Borrador de rutina creado con ID {draft_id}. "
            "Confírmalo desde la app antes de reemplazar tu rutina activa."
        )
        parts = [p for p in [before, routine_text, confirmation_note, after] if p]
        return "\n\n".join(parts)

    except ValueError:
        # Si los marcadores están malformados, devolver el texto original sin romper
        return response_text.replace(ROUTINE_START, "").replace(ROUTINE_END, "")


def _is_admin(user_id: str) -> bool:
    return bool(settings.ADMIN_TELEGRAM_ID) and user_id == settings.ADMIN_TELEGRAM_ID


async def handle_access_decision(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Callback para los botones ✅ Aprobar / ❌ Bloquear que recibe el admin.

    [CONCEPTO: CallbackQueryHandler a nivel de app]
    Registrado ANTES del ConversationHandler para que el admin pueda
    aprobar/bloquear en cualquier momento, aunque esté en otra conversación.
    El patrón r'^access_(approve|block)_\\d+$' lo aísla de otros callbacks.
    """
    query = update.callback_query
    await query.answer()

    if not _is_admin(str(query.from_user.id)):
        return  # Solo el admin puede usar estos botones

    # callback_data: "access_approve_123456" o "access_block_123456"
    parts = query.data.split("_")  # ["access", "approve/block", "userid"]
    action = parts[1]  # "approve" o "block"
    target_id = parts[2]  # telegram_id del usuario

    db_user = _store.get_user(target_id)
    name = db_user["name"] if db_user else target_id

    if action == "approve":
        _store.update_user_status(target_id, "active")
        await query.edit_message_text(f"✅ *{name}* aprobado.", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "✅ *¡Tu acceso fue aprobado!*\n\n"
                "Escribe /start para configurar tu perfil y empezar. 💪"
            ),
            parse_mode="Markdown",
        )
    elif action == "block":
        _store.update_user_status(target_id, "blocked")
        await query.edit_message_text(f"❌ *{name}* bloqueado.", parse_mode="Markdown")
        await context.bot.send_message(
            chat_id=target_id,
            text="❌ Tu solicitud de acceso fue denegada.",
        )


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /usuarios — muestra todos los usuarios y su estado (solo admin).

    [CONCEPTO: Comandos de administración]
    El bot actúa como su propio panel de control. No necesitamos una
    interfaz web de admin separada para operaciones simples de gestión.
    """
    user_id = str(update.effective_user.id)
    if not _is_admin(user_id):
        return

    all_users = _store.get_all_users_with_status()
    if not all_users:
        await update.message.reply_text("No hay usuarios registrados.")
        return

    STATUS_EMOJI = {"active": "✅", "pending": "⏳", "blocked": "❌"}
    lines = ["*Usuarios registrados:*\n"]
    for u in all_users:
        emoji = STATUS_EMOJI.get(u["status"], "❓")
        onboarding = "✓" if u["onboarding_done"] else "·"
        lines.append(f"{emoji} {u['name']} `{u['telegram_id']}` {onboarding}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def webapp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Genera (o recupera) el enlace personal a la app web de registro.

    [CONCEPTO: Tokens de acceso personal]
    En lugar de exponer el Telegram ID en la URL, usamos un token único
    generado con secrets.token_urlsafe(). El token:
    - Identifica al usuario en todos los endpoints de la app web
    - Se genera una sola vez y se persiste en la DB (idempotente)
    - Se puede regenerar si el usuario quiere invalidar el enlace anterior
    """
    user_id = str(update.effective_user.id)
    token = _store.get_or_create_web_token(user_id)
    app_url = f"{settings.WEB_URL}/app?token={token}"

    await update.message.reply_text(
        f"🏋️ *Tu app de registro personal:*\n\n"
        f"[Abrir Heracles Web]({app_url})\n\n"
        f"Guarda este enlace en tu celular — es personal y único. "
        f"Úsalo durante tus sesiones para registrar series con cronómetro y RPE.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /ayuda."""
    help_text = (
        "*Comandos disponibles:*\n"
        "/start — Registrarte o reiniciar el bot\n"
        "/rutina — Ver tu rutina activa\n"
        "/historial — Ver tus últimos entrenamientos\n"
        "/webapp — Obtener enlace a la app web de registro\n"
        "/ayuda — Ver este menú\n\n"
        "_O simplemente escríbeme en lenguaje natural._\n\n"
        "Ejemplos:\n"
        '• "Hoy hice sentadilla 4x8 con 100kg"\n'
        '• "¿Cuándo debería subir el peso?"\n'
        '• "Genérame mi rutina semanal"'
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def rutina_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Muestra la rutina activa del usuario directamente desde SQLite.

    [CONCEPTO: Capa 0 — Sin LLM]
    Este comando no pasa por el agente. Va directo a la base de datos.
    Para mostrar la rutina no necesitamos razonamiento — ya está guardada
    en el formato correcto. Costo: 0 llamadas al LLM.

    En SaaS, cada operación que evita el LLM reduce costos marginales
    y mejora los márgenes a escala.
    """
    user_id = str(update.effective_user.id)
    routine = _store.get_active_routine(user_id)

    if not routine:
        await update.message.reply_text(
            "No tienes ninguna rutina guardada todavía.\n\n"
            'Escríbeme *"Genérame mi rutina"* para que diseñe una personalizada. 💪',
            parse_mode="Markdown",
        )
        return

    date = routine["created_at"][:10]
    header = f"*Tu rutina activa* (creada el {date}):\n\n"
    await update.message.reply_text(
        header + routine["routine_text"],
        parse_mode="Markdown",
    )


async def historial_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Muestra las sesiones de los últimos días directamente desde SQLite.

    [CONCEPTO: Capa 0 — Sin LLM]
    Mismo principio que /rutina: datos estructurados que ya tenemos en DB.
    No necesitamos que el LLM "decida" mostrar el historial ni lo "formatee"
    — lo formateamos en código Python directamente.
    """
    user_id = str(update.effective_user.id)
    workouts = _store.get_recent_workouts(user_id, days=7)

    if not workouts:
        await update.message.reply_text(
            "Aún no has registrado ningún entrenamiento.\n\n"
            "Cuéntame tu próxima sesión y la guardo automáticamente. 🏋️",
        )
        return

    # Agrupar por día y ejercicio: la app web guarda cada serie como una fila
    # (sets=1), así que las juntamos para leer la sesión completa de un vistazo.
    by_date: dict[str, dict[str, list]] = {}
    for w in reversed(workouts):  # orden cronológico dentro de cada día
        by_date.setdefault(w["local_date"], {}).setdefault(w["exercise"], []).append(w)

    lines = ["*Tus últimos entrenamientos:*\n"]
    for date_str in sorted(by_date, reverse=True):
        lines.append(f"`{date_str}`")
        for ex, sets in by_date[date_str].items():
            if len(sets) == 1:
                s = sets[0]
                lines.append(f"• {ex}: {s['sets']}×{s['reps']} @ {s['weight_kg']}kg")
            else:
                reps_str = "/".join(str(s["reps"]) for s in sets)
                weights = {s["weight_kg"] for s in sets}
                if len(weights) == 1:
                    w_str = f"{weights.pop()}kg"
                else:
                    w_str = "/".join(str(s["weight_kg"]) for s in sets) + " kg"
                lines.append(f"• {ex}: {len(sets)} series · {reps_str} reps @ {w_str}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_stale_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Captura callbacks de teclados que ya no tienen estado activo (ej. tras reinicio).

    Cuando el contenedor se reinicia, PTB pierde el estado en memoria de todos los
    ConversationHandlers. Si el usuario tapea un botón de una sesión anterior, el
    ConversationHandler no lo reconoce y Telegram muestra animación infinita.
    Este fallback responde el callback y pide al usuario que reinicie.
    """
    query = update.callback_query
    await query.answer(
        text="Esta sesión expiró. Enviá /start para comenzar de nuevo.",
        show_alert=True,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja todos los mensajes de texto normales.
    Delega al agente LangGraph y post-procesa la respuesta.
    """
    user = update.effective_user
    user_id = str(user.id)
    request_token = request_id_var.set(new_request_id())
    try:
        detected_intent = classify_intent_text(update.message.text)
        log_event(
            "telegram_message_received",
            user_id=anonymize_user_id(user_id),
            intent=detected_intent.value,
            allowed_tools=allowed_tools_for_intent(detected_intent),
        )
    finally:
        request_id_var.reset(request_token)

    _store.upsert_user(user_id, user.first_name)

    # Admin siempre activo
    if _is_admin(user_id):
        _store.update_user_status(user_id, "active")

    status = _store.get_user_status(user_id)
    if status == "pending":
        await update.message.reply_text(
            "⏳ Tu solicitud de acceso está en revisión.\n"
            "Te notificaremos cuando sea aprobada."
        )
        return
    if status == "blocked":
        await update.message.reply_text("❌ Tu acceso está bloqueado.")
        return

    # Guardia: si el onboarding no está completo el ConversationHandler
    # debería haberlo interceptado primero, pero este check evita que el
    # agente responda si por alguna razón llegó hasta acá.
    db_user = _store.get_user(user_id)
    if not db_user or not db_user.get("onboarding_done"):
        await update.message.reply_text(
            "Antes de continuar necesito conocerte un poco 👇\n"
            "Escribí /start para completar tu perfil."
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    response = await run_agent_message(user_id, update.message.text, "telegram")
    response_text = response.message

    # [CONCEPTO: Post-processing sin LLM]
    # Después de que el agente responde, el código detecta si hay una rutina
    # en la respuesta, la guarda en DB y limpia los marcadores antes de
    # enviar al usuario. Todo en Python puro — 0 llamadas extra al LLM.
    response_text = _extract_and_save_routine(user_id, response_text)

    await update.message.reply_text(response_text, parse_mode="Markdown")


def create_telegram_app() -> Application:
    """
    Construye y configura la Application de Telegram.

    [CONCEPTO: Builder Pattern]
    Application.builder() usa el patrón Builder para configurar la app
    con un estilo fluido (method chaining).

    [CONCEPTO: Orden de registro de handlers]
    python-telegram-bot evalúa los handlers en el orden en que se registran.
    El ConversationHandler va PRIMERO para interceptar /start y los mensajes
    durante el onboarding antes de llegar al handler general.
    """
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # [CONCEPTO: Orden de handlers en PTB]
    # PTB evalúa handlers en orden de registro. Los callbacks de acceso
    # van PRIMERO para que el admin pueda aprobar/bloquear en cualquier
    # momento, sin que el ConversationHandler los intercepte.
    app.add_handler(
        CallbackQueryHandler(
            handle_access_decision, pattern=r"^access_(approve|block)_\d+$"
        )
    )

    # Onboarding — intercepta /start y el flujo de preguntas
    app.add_handler(build_onboarding_handler())

    # Comandos directos a DB (capa 0, sin LLM)
    app.add_handler(CommandHandler("rutina", rutina_command))
    app.add_handler(CommandHandler("historial", historial_command))
    app.add_handler(CommandHandler("webapp", webapp_command))
    app.add_handler(CommandHandler("usuarios", users_command))
    app.add_handler(CommandHandler("ayuda", help_command))

    # [CONCEPTO: Filtros en handlers]
    # filters.TEXT & ~filters.COMMAND:
    #   - filters.TEXT: solo mensajes de texto (no fotos, archivos, etc.)
    #   - ~filters.COMMAND: excluir mensajes que empiecen con /
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Fallback para callbacks no capturados (ej. teclados de una sesión anterior
    # tras un reinicio del contenedor que borró el estado en memoria).
    # Sin esto, Telegram muestra animación de carga indefinida en el botón.
    app.add_handler(CallbackQueryHandler(handle_stale_callback))

    return app
