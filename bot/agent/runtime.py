from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRuntimeContext:
    user_id: str
    channel: str


current_agent_context: ContextVar[AgentRuntimeContext | None] = ContextVar(
    "current_agent_context",
    default=None,
)


def require_agent_context() -> AgentRuntimeContext:
    context = current_agent_context.get()
    if context is None:
        raise RuntimeError("Agent runtime context is missing")
    return context
