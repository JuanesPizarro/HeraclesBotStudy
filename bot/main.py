"""
Heracles Bot — Punto de entrada principal.

Arranca dos servicios concurrentemente:
  1. Bot de Telegram (polling) — escucha mensajes de usuarios
  2. Servidor FastAPI (uvicorn) — recibe webhooks de n8n
"""
import asyncio
import uvicorn
from fastapi import FastAPI

from bot.config import settings
from bot.handlers.telegram import create_telegram_app
from bot.handlers.n8n_webhook import router as n8n_router

# =====================================================================
# [CONCEPTO: FastAPI]
# El framework web Python más popular actualmente (2024-2025).
# Ventajas sobre Flask/Django para APIs:
# - Async nativo (basado en Starlette/ASGI)
# - Documentación automática en /docs y /redoc (Swagger UI)
# - Validación automática con Pydantic
# - Tipado estático — mejor experiencia de desarrollo
#
# Aprende más: https://fastapi.tiangolo.com/
# Curso recomendado: "FastAPI - The Complete Course" (Udemy/YouTube)
# =====================================================================
app = FastAPI(
    title="Heracles Bot API",
    description="Bot de acompañamiento en entrenamiento con LangGraph + DeepSeek",
    version="0.1.0",
)

# Registrar los routers
app.include_router(n8n_router)


@app.get("/health")
async def health_check() -> dict:
    """
    [CONCEPTO: Health Check Endpoint]
    Endpoint estándar de cualquier servicio en producción.
    Docker, Kubernetes y load balancers lo usan para verificar
    que el servicio está vivo y listo para recibir tráfico.
    Responde 200 OK = todo bien.
    """
    return {"status": "ok", "service": "heracles-bot"}


async def run_telegram_bot() -> None:
    """Inicia el bot de Telegram en modo polling."""
    telegram_app = create_telegram_app()

    # [CONCEPTO: Context Manager async (async with)]
    # "async with telegram_app" inicializa y limpia recursos async del bot.
    # Equivale a: await telegram_app.initialize() ... await telegram_app.shutdown()
    async with telegram_app:
        await telegram_app.start()

        # [CONCEPTO: Polling vs Webhook]
        # start_polling() para desarrollo (sin servidor público).
        # Para producción con dominio + HTTPS:
        #   await telegram_app.updater.start_webhook(
        #       listen="0.0.0.0",
        #       port=8443,
        #       url_path=settings.TELEGRAM_BOT_TOKEN,
        #       webhook_url=f"https://tu-dominio.com/{settings.TELEGRAM_BOT_TOKEN}",
        #   )
        await telegram_app.updater.start_polling()

        # Esperar indefinidamente hasta que se detenga la tarea
        # asyncio.Event().wait() es la forma idiomática de "esperar para siempre"
        await asyncio.Event().wait()

        await telegram_app.updater.stop()
        await telegram_app.stop()


async def run_web_server() -> None:
    """Inicia el servidor FastAPI con uvicorn."""
    # =====================================================================
    # [CONCEPTO: Uvicorn — Servidor ASGI]
    # Uvicorn es el servidor ASGI estándar para FastAPI.
    # ASGI (Async Server Gateway Interface) es el protocolo para apps Python async.
    #
    # En desarrollo: uvicorn con un solo worker es suficiente.
    # En producción: Gunicorn + múltiples workers Uvicorn para aprovechar múltiples CPUs:
    #   gunicorn bot.main:app -w 4 -k uvicorn.workers.UvicornWorker
    #
    # Aprende más: https://www.uvicorn.org/
    # =====================================================================
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    """
    Función principal: valida config y arranca ambos servicios.

    [CONCEPTO: asyncio.gather() — Concurrencia con async/await]
    asyncio.gather() ejecuta múltiples coroutines CONCURRENTEMENTE
    dentro del mismo event loop (un solo hilo).

    Diferencia importante:
    - CONCURRENCIA async: un hilo alterna entre tareas cuando esperan I/O
      → Ideal para HTTP requests, DB queries, leer archivos (I/O-bound)
    - PARALELISMO con threads/processes: múltiples hilos/procesos simultáneos
      → Ideal para cálculo intensivo (CPU-bound)

    Como nuestro bot principalmente espera respuestas HTTP (Telegram API,
    DeepSeek API, SQLite), la concurrencia async es perfecta y eficiente.

    Aprende más: "Python asyncio tutorial", "async vs threading python"
    Recurso: https://docs.python.org/3/library/asyncio.html
    """
    settings.validate()  # Falla rápido si faltan credenciales

    print("🏛️  Heracles Bot arrancando...")
    print(f"    Servidor web en: http://localhost:{settings.PORT}")
    print(f"    Documentación API: http://localhost:{settings.PORT}/docs")
    print("    Bot de Telegram: modo polling activo")

    # Ejecutar ambos servicios concurrentemente
    await asyncio.gather(
        run_telegram_bot(),
        run_web_server(),
    )


if __name__ == "__main__":
    # [CONCEPTO: asyncio.run() — Entry point para código async]
    # asyncio.run() crea el event loop, ejecuta la coroutine main(),
    # y lo cierra limpiamente al terminar.
    # Es el equivalente de "main()" para código asíncrono.
    asyncio.run(main())
