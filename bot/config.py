import os
from dataclasses import dataclass
from dotenv import load_dotenv

# [CONCEPTO: python-dotenv]
# load_dotenv() lee el archivo ".env" y carga sus valores como variables de entorno.
# Solo afecta al proceso actual — no modifica el sistema operativo.
# En producción (Docker, AWS, Heroku) las env vars se configuran a nivel de servicio.
load_dotenv()


@dataclass
class Settings:
    """
    [CONCEPTO: Dataclass para configuración]
    @dataclass genera automáticamente __init__, __repr__ y otros métodos.
    Es más limpio que un dict o variables globales sueltas.
    Para validación avanzada, usa Pydantic BaseSettings:
      from pydantic_settings import BaseSettings  # pip install pydantic-settings
    """
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "changeme")
    PORT: int = int(os.getenv("PORT", "8000"))
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/heracles.db")
    # URL pública del servidor (usada para generar el enlace /webapp en Telegram)
    # Con Cloudflare Tunnel: https://tu-dominio.com
    # Sin dominio (solo local): http://localhost:8000
    WEB_URL: str = os.getenv("WEB_URL", f"http://localhost:{os.getenv('PORT', '8000')}")
    # ID de Telegram del administrador — recibe notificaciones y puede aprobar/bloquear usuarios
    ADMIN_TELEGRAM_ID: str = os.getenv("ADMIN_TELEGRAM_ID", "")
    # Zona horaria del servidor — afecta qué día es "hoy" para el plan y el historial
    TIMEZONE: str = os.getenv("TIMEZONE", "America/Santiago")

    def validate(self) -> None:
        """Valida que las variables críticas estén presentes antes de arrancar."""
        errors = []
        if not self.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN")
        if not self.DEEPSEEK_API_KEY:
            errors.append("DEEPSEEK_API_KEY")
        if errors:
            raise ValueError(
                f"Variables de entorno requeridas no configuradas: {', '.join(errors)}\n"
                "Copia .env.example a .env y rellena los valores."
            )


# Instancia global — importada por todos los módulos
settings = Settings()
