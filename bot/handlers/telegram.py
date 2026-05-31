from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from langchain_core.messages import HumanMessage

from bot.agent.graph import agent_graph
from bot.storage.user_store import UserStore
from bot.config import settings
from bot.handlers.onboarding import build_onboarding_handler

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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /ayuda."""
    help_text = (
        "*Comandos disponibles:*\n"
        "/start — Registrarte o reiniciar el bot\n"
        "/ayuda — Ver este menú\n\n"
        "_O simplemente escríbeme en lenguaje natural._\n\n"
        "Ejemplos:\n"
        "• \"Hoy hice sentadilla 4x8 con 100kg\"\n"
        "• \"¿Cuándo debería subir el peso en press de banca?\"\n"
        "• \"¿Cuál fue mi último entrenamiento?\""
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Maneja todos los mensajes de texto normales.
    Delega al agente LangGraph para generar la respuesta.
    """
    user = update.effective_user
    user_id = str(user.id)

    # Asegurar que el usuario esté registrado antes de procesar
    _store.upsert_user(user_id, user.first_name)

    # Mostrar "escribiendo..." mientras el agente procesa
    # (buena UX — el usuario sabe que el bot está trabajando)
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    # =====================================================================
    # [CONCEPTO: Invocar el grafo con config — thread_id para memoria]
    #
    # El campo "configurable.thread_id" le dice al checkpointer qué
    # historial de conversación cargar y guardar.
    #
    # Usamos el user_id de Telegram como thread_id:
    # → Cada usuario tiene su propia conversación independiente
    # → El bot "recuerda" el historial completo con el mismo usuario
    #
    # Si usaras el mismo thread_id para todos → todos comparten historial (¡bug!)
    # Si usaras un UUID nuevo en cada mensaje → bot no recordaría nada
    # =====================================================================
    config = {"configurable": {"thread_id": user_id}}

    # Invocar el grafo de forma asíncrona
    # ainvoke() es la versión async de invoke() — no bloquea el event loop
    result = await agent_graph.ainvoke(
        input={
            "messages": [HumanMessage(content=update.message.text)],
            "user_id": user_id,
        },
        config=config,
    )

    # El último mensaje del estado es la respuesta final del agente
    response_text = result["messages"][-1].content

    await update.message.reply_text(response_text)


def create_telegram_app() -> Application:
    """
    Construye y configura la Application de Telegram.

    [CONCEPTO: Builder Pattern]
    Application.builder() usa el patrón Builder para configurar la app
    con un estilo fluido (method chaining).
    Permite agregar rate limiting, persistence, callbacks de error, etc.

    Aprende más: https://docs.python-telegram-bot.org/en/stable/telegram.ext.applicationbuilder.html
    """
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # [CONCEPTO: Orden de registro de handlers]
    # python-telegram-bot evalúa los handlers en el orden en que se registran.
    # El ConversationHandler debe ir PRIMERO para interceptar /start y los
    # mensajes durante el onboarding antes de que lleguen al handler general.
    # Si el ConversationHandler termina (END), el siguiente mensaje va al
    # MessageHandler general de abajo — así funciona la transición limpia.
    app.add_handler(build_onboarding_handler())

    app.add_handler(CommandHandler("ayuda", help_command))

    # [CONCEPTO: Filtros en handlers]
    # filters.TEXT & ~filters.COMMAND:
    #   - filters.TEXT: solo mensajes de texto (no fotos, archivos, etc.)
    #   - ~filters.COMMAND: excluir mensajes que empiecen con /
    # El operador & es AND, | es OR, ~ es NOT
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return app
