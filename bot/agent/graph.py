from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from bot.agent.state import AgentState
from bot.agent.nodes import agent_node, tools_node, should_continue

# =====================================================================
# [CONCEPTO: StateGraph — El corazón de LangGraph]
#
# Un StateGraph es un grafo dirigido donde:
# - NODOS: funciones Python que reciben y modifican el estado
# - ARISTAS (edges): conexiones entre nodos, pueden ser condicionales
# - STATE: el objeto que fluye y se transforma a través del grafo
#
# Visualización del grafo de este bot:
#
#    ┌─────────┐
#    │  START  │
#    └────┬────┘
#         │
#    ┌────▼────┐
#    │  agent  │◄──────────────────┐
#    └────┬────┘                   │
#         │                        │
#    should_continue()             │
#         │                        │
#    ┌────┴──────┐           ┌─────┴─────┐
#    │  "tools"  │──────────►│   tools   │
#    └───────────┘           └───────────┘
#         │
#    ┌────▼────┐
#    │   END   │
#    └─────────┘
#
# Este patrón implementa el ciclo ReAct: el agente razona y actúa
# alternando entre llamar al LLM y ejecutar herramientas.
#
# Casos de uso de LangGraph en la industria:
# - Agentes de código (como Cursor/Copilot)
# - Pipelines de análisis multi-paso
# - Chatbots con memoria y herramientas
# - Orquestación de múltiples LLMs
#
# Aprende más: https://langchain-ai.github.io/langgraph/
# Curso gratuito: LangChain Academy → "Introduction to LangGraph"
# =====================================================================


def build_graph():
    # 1. Crear el builder con el tipo de estado
    graph_builder = StateGraph(AgentState)

    # 2. Agregar nodos (nombre → función)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", tools_node)

    # 3. Definir las aristas del grafo
    # START siempre es el primer nodo
    graph_builder.add_edge(START, "agent")

    # Arista condicional desde "agent":
    # should_continue() decide si ir a "tools" o a END
    graph_builder.add_conditional_edges(
        source="agent",
        path=should_continue,
        path_map={
            "tools": "tools",  # Si should_continue devuelve "tools" → nodo tools
            "end": END,        # Si should_continue devuelve "end" → terminar
        },
    )

    # Después de ejecutar tools, siempre volvemos al agente
    # para que procese los resultados y decida qué hacer
    graph_builder.add_edge("tools", "agent")

    # =====================================================================
    # [CONCEPTO: Checkpointing — Memoria persistente por usuario]
    #
    # El checkpointer guarda el estado completo del grafo (incluyendo el
    # historial de mensajes) después de cada step, identificado por thread_id.
    #
    # MemorySaver: guarda en RAM — rápido pero se pierde al reiniciar
    # SqliteSaver: guarda en SQLite — persiste entre reinicios
    #
    # Para producción con múltiples workers, necesitas un checkpointer
    # compartido (PostgreSQL, Redis) para que todos los procesos accedan
    # al mismo historial.
    #
    # Ejemplo de SqliteSaver (descomenta para usar):
    # from langgraph.checkpoint.sqlite import SqliteSaver
    # checkpointer = SqliteSaver.from_conn_string("data/checkpoints.db")
    #
    # Aprende más: https://langchain-ai.github.io/langgraph/concepts/persistence/
    # =====================================================================
    checkpointer = MemorySaver()

    # 4. Compilar el grafo — lo convierte en un Runnable invocable
    # [CONCEPTO: Runnable Interface]
    # El grafo compilado implementa la interfaz Runnable de LangChain:
    # .invoke() → ejecución síncrona
    # .ainvoke() → ejecución asíncrona (async/await)
    # .stream() → streaming de respuestas token a token
    return graph_builder.compile(checkpointer=checkpointer)


# [CONCEPTO: Singleton del grafo]
# Compilamos una sola vez al importar el módulo.
# El grafo es stateless — el estado vive en el checkpointer por thread_id.
# Múltiples usuarios pueden usar el mismo grafo concurrentemente.
agent_graph = build_graph()
