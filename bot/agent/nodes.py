from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from bot.config import settings
from bot.agent.state import AgentState
from bot.agent.tools import TOOLS

# =====================================================================
# [CONCEPTO: Compatibilidad OpenAI → DeepSeek]
# DeepSeek expone la misma API REST que OpenAI (chat completions).
# Cambiando base_url y api_key podemos usar el mismo cliente de LangChain.
#
# Modelos disponibles en DeepSeek:
# - "deepseek-chat"     → DeepSeek-V3 (rápido, barato, muy capaz)
# - "deepseek-reasoner" → DeepSeek-R1 (razonamiento step-by-step, más caro)
#
# Costos aproximados (2025):
# - DeepSeek-V3: ~$0.14/M tokens input, $0.28/M tokens output
# - GPT-4o:      ~$2.50/M tokens input, $10/M tokens output
#
# Aprende más: https://api-docs.deepseek.com/
# =====================================================================
llm = ChatOpenAI(
    model="deepseek-chat",
    openai_api_key=settings.DEEPSEEK_API_KEY,
    openai_api_base="https://api.deepseek.com",
    temperature=0.7,
    # max_tokens=1024,  # Descomenta para limitar el tamaño de respuesta y costos
)

# [CONCEPTO: bind_tools()]
# bind_tools() convierte cada @tool en JSON Schema y lo adjunta al LLM.
# Cuando el LLM recibe el mensaje, sabe qué tools tiene disponibles.
# Internamente usa el campo "tools" de la API de chat completions.
llm_with_tools = llm.bind_tools(TOOLS)

# Prompt del sistema: define la personalidad y contexto de Heracles
# {user_id} se rellena dinámicamente en cada invocación
SYSTEM_PROMPT = """Eres Heracles, un entrenador personal experto en entrenamiento de fuerza y diseño de rutinas.
Eres directo, motivador y basas tus recomendaciones en evidencia científica. Hablas en español.

El user_id del usuario actual es: {user_id}
IMPORTANTE: pasa siempre este user_id como argumento cuando uses cualquier herramienta.

════════════════════════════════════
USO DE HERRAMIENTAS
════════════════════════════════════
• get_user_profile    → SIEMPRE antes de generar o ajustar una rutina.
                        El perfil contiene toda la información que necesitas:
                        disponibilidad, equipamiento, nivel, actividad diaria,
                        limitaciones físicas y objetivo. Sin él, no puedes
                        tomar decisiones informadas.
• save_workout        → Cuando el usuario reporte haber completado un ejercicio.
                        PRIMERO guárdalo, LUEGO responde con feedback.
• get_recent_workouts → Cuando necesites revisar el historial para sugerir
                        progresión o analizar la carga acumulada reciente.
• update_goal         → Cuando el usuario mencione explícitamente un nuevo objetivo.

════════════════════════════════════
PRINCIPIOS IRRENUNCIABLES
════════════════════════════════════
• Seguridad primero: si el usuario reporta dolor, adapta o sustituye el ejercicio.
• Nunca ignores las lesiones o limitaciones del perfil.
• Técnica antes que carga: corrige la forma antes de aumentar el peso.
• Equipamiento: si el usuario entrena en casa, diseña la rutina EXCLUSIVAMENTE
  con los implementos que listó. Si un ejercicio requiere algo que no mencionó
  (banco, rack, máquina, etc.), sustitúyelo por la alternativa sin ese implemento.
  No asumas que tiene algo porque no lo negó explícitamente.
• Sé honesto si no tienes suficiente información para hacer una recomendación sólida.
"""


def agent_node(state: AgentState) -> dict:
    """
    Nodo principal: llama al LLM con el historial de mensajes y los tools disponibles.

    [CONCEPTO: Nodos en LangGraph]
    Un nodo es simplemente una función Python que:
      - Recibe: el estado completo (AgentState)
      - Procesa: lo que sea (llamar LLM, ejecutar código, consultar DB...)
      - Devuelve: dict con SOLO los campos del estado que quiere actualizar
    LangGraph fusiona ese dict con el estado usando los reducers definidos.

    Aprende más: https://langchain-ai.github.io/langgraph/concepts/low_level/#nodes
    """
    # Construimos el system prompt personalizado con el user_id
    system = SystemMessage(
        content=SYSTEM_PROMPT.format(user_id=state["user_id"])
    )

    # Llamamos al LLM con el historial completo
    # [CONCEPTO: Message History = "memoria" del LLM]
    # El LLM es stateless (no recuerda nada entre llamadas).
    # La "memoria" se logra enviando TODOS los mensajes previos en cada llamada.
    # LangGraph gestiona esto automáticamente con el checkpointer.
    response = llm_with_tools.invoke([system] + list(state["messages"]))

    # Solo devolvemos "messages" — LangGraph hace append con add_messages
    return {"messages": [response]}


# [CONCEPTO: ToolNode (prebuilt de LangGraph)]
# ToolNode es un nodo listo para usar que:
#   1. Lee los tool_calls del último mensaje del LLM
#   2. Ejecuta cada función correspondiente
#   3. Agrega los resultados como ToolMessages al estado
#
# Equivale a escribir manualmente:
#   for tool_call in last_message.tool_calls:
#       result = tools_map[tool_call.name](**tool_call.args)
#       messages.append(ToolMessage(result, tool_call_id=tool_call.id))
#
# Aprende más: https://langchain-ai.github.io/langgraph/reference/prebuilt/#toolnode
tools_node = ToolNode(TOOLS)


def should_continue(state: AgentState) -> str:
    """
    Función de routing: decide a qué nodo ir después del agente.

    [CONCEPTO: Conditional Edges — El poder de LangGraph]
    Las "conditional edges" son funciones que inspeccionan el estado
    y devuelven el nombre del siguiente nodo.
    Esto permite ciclos, branching, y flujos dinámicos en el grafo.

    En este caso implementa el ciclo ReAct:
      agent → tools → agent → tools → ... → agent → END

    Aprende más: https://langchain-ai.github.io/langgraph/concepts/low_level/#conditional-edges
    """
    last_message = state["messages"][-1]

    # Si el LLM pidió ejecutar tools, ir al nodo de tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # Si no hay tool_calls, el agente terminó — ir al final
    return "end"
