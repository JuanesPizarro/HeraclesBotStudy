from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from telegram import Bot

from bot.config import settings
from bot.storage.user_store import UserStore

# =====================================================================
# [CONCEPTO: APIRouter en FastAPI]
# Dividir la app en routers mantiene el código organizado y modular.
# Cada router tiene su propio prefijo de URL y conjunto de endpoints.
# Similar a: Blueprints (Flask), Routers (Express.js), Controllers (NestJS)
#
# Aprende más: https://fastapi.tiangolo.com/tutorial/bigger-applications/
# =====================================================================

router = APIRouter(prefix="/webhook", tags=["webhooks"])
_store = UserStore()


class ReminderPayload(BaseModel):
    """
    Modelo de datos para el body del webhook de n8n.

    [CONCEPTO: Pydantic BaseModel + FastAPI = validación automática]
    FastAPI usa Pydantic para parsear y validar el JSON del request.
    Si el body no cumple el schema, FastAPI devuelve 422 Unprocessable Entity.
    Esto elimina validación manual y errores de tipo en runtime.

    Además, FastAPI genera documentación automática en /docs usando este modelo.

    Aprende más: https://docs.pydantic.dev/latest/concepts/models/
    """
    message: str                          # Texto del recordatorio
    user_ids: Optional[list[str]] = None  # None = enviar a TODOS los usuarios


@router.post("/n8n/reminder")
async def receive_reminder(
    payload: ReminderPayload,
    # [CONCEPTO: Inyección de Headers en FastAPI]
    # FastAPI inyecta automáticamente el header HTTP como parámetro.
    # Header("X-Webhook-Secret") se convierte a snake_case: x_webhook_secret
    x_webhook_secret: Optional[str] = Header(None),
) -> dict:
    """
    Endpoint que recibe recordatorios programados desde n8n.

    n8n llama a este endpoint según su schedule y nosotros
    reenviamos el mensaje a los usuarios de Telegram.

    [CONCEPTO: Seguridad en Webhooks]
    Validamos un secreto compartido en el header para que solo
    n8n (con el secret correcto) pueda disparar este endpoint.

    En producción también considera:
    - Validar IP de origen (solo aceptar IPs de tu instancia n8n)
    - Rate limiting (evitar flood de mensajes)
    - HTTPS obligatorio (sin esto el secret viaja en texto plano)
    - HMAC signature (más seguro que secret simple)
    Aprende más: "webhook security best practices"
    """
    if x_webhook_secret != settings.WEBHOOK_SECRET:
        # 401 Unauthorized: el cliente no está autenticado
        raise HTTPException(status_code=401, detail="Webhook secret inválido")

    # Si no se especifican users, enviar a todos los registrados
    target_ids = payload.user_ids or _store.get_all_user_ids()

    if not target_ids:
        return {"status": "ok", "sent": 0, "message": "No hay usuarios registrados"}

    # [CONCEPTO: Bot standalone para enviar mensajes proactivos]
    # Creamos un Bot directamente (sin Application) para enviar mensajes
    # desde un contexto que no es un handler de Telegram.
    # async with bot: abre y cierra la sesión HTTP correctamente.
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    sent_count = 0
    failed_count = 0

    async with bot:
        for user_id in target_ids:
            try:
                await bot.send_message(chat_id=user_id, text=payload.message)
                sent_count += 1
            except Exception:
                # Un usuario puede haber bloqueado el bot — continuamos con los demás
                # En producción: loggea el error con ID de usuario para limpieza posterior
                failed_count += 1

    return {
        "status": "ok",
        "sent": sent_count,
        "failed": failed_count,
    }
