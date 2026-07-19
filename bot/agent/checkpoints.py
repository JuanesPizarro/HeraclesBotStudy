from langgraph.checkpoint.memory import MemorySaver

from bot.config import settings


def build_checkpointer():
    """
    Devuelve un checkpointer persistente cuando DATABASE_URL apunta a Postgres.

    El import es diferido para que desarrollo local y tests sigan funcionando
    aunque las dependencias PostgreSQL no estén instaladas todavía.
    """
    if settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        from langgraph.checkpoint.postgres import PostgresSaver

        checkpointer = PostgresSaver.from_conn_string(settings.DATABASE_URL)
        checkpointer.setup()
        return checkpointer
    return MemorySaver()
