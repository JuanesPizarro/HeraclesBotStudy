from typing import Annotated, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# =====================================================================
# [CONCEPTO: State en LangGraph — El más importante de entender]
#
# El "State" es el objeto que fluye entre los nodos del grafo.
# Cada nodo recibe el estado completo y devuelve los campos que modifica.
# LangGraph fusiona esos cambios con el estado existente.
#
# Tipos de anotación en el State:
#   - Sin anotación extra: el nuevo valor REEMPLAZA al anterior
#   - Annotated[tipo, reducer]: el reducer define cómo fusionar
#
# TypedDict vs Pydantic:
#   - TypedDict: solo type hints estáticos, sin validación en runtime
#   - Pydantic BaseModel: valida tipos en runtime (más seguro en producción)
#
# Aprende más: https://langchain-ai.github.io/langgraph/concepts/low_level/#state
# Curso gratuito: "Introduction to LangGraph" en LangChain Academy
# =====================================================================


class AgentState(TypedDict):
    # [CONCEPTO: Reducer — add_messages]
    # Annotated[..., add_messages] registra un "reducer":
    # cuando el nodo devuelve {"messages": [nuevo_mensaje]}, LangGraph
    # AGREGA ese mensaje a la lista existente en lugar de reemplazarla.
    #
    # Sin reducer sería: state["messages"] = [nuevo_mensaje]  ← borra el historial
    # Con add_messages:  state["messages"].append(nuevo_mensaje) ← conserva el historial
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # ID de Telegram del usuario — para persistir datos y personalizar respuestas
    # Este campo se reemplaza (sin reducer) porque siempre es el mismo por thread
    user_id: str
