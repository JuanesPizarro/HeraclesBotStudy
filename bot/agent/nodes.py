import datetime
import re
import zoneinfo
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from bot.config import settings
from bot.agent.state import AgentState
from bot.agent.tools import TOOLS
from bot.storage.user_store import UserStore

# URL base para el enlace personal de la app web
_WEB_URL = settings.WEB_URL.rstrip("/")

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
)

# [CONCEPTO: bind_tools()]
# bind_tools() convierte cada @tool en JSON Schema y lo adjunta al LLM.
# Solo registramos tools de escritura — las lecturas van en el system prompt.
llm_with_tools = llm.bind_tools(TOOLS)

_store = UserStore()

# =====================================================================
# [CONCEPTO: Marcador de rutina — patrón para persistencia sin tool call]
#
# En lugar de que el LLM llame un tool save_routine (lo que generaría
# una llamada extra al LLM), le pedimos que envuelva la rutina en
# marcadores especiales. El código Python los detecta, extrae el texto
# y guarda en SQLite sin involucrar al LLM.
#
# Flujo:
#   LLM responde: "Aquí tu rutina: <<<RUTINA>>>...texto...<<<FIN_RUTINA>>>"
#   telegram.py detecta los marcadores → guarda en DB → limpia el texto
#
# Ventaja: 0 llamadas extra al LLM para persistir. Clave para SaaS.
# =====================================================================
ROUTINE_START = "<<<RUTINA>>>"
ROUTINE_END = "<<<FIN_RUTINA>>>"

# =====================================================================
# [CONCEPTO: System Prompt con contexto inyectado]
#
# En lugar de darle al LLM tools para "descubrir" el perfil y la rutina,
# inyectamos esa información directamente en el system prompt ANTES de
# cada llamada. El LLM ya tiene todo el contexto desde el primer token.
#
# Patrón: "context stuffing" o "RAG-lite"
# - RAG completo: busca en una base vectorial qué contexto inyectar
# - Context stuffing: inyecta todo el contexto relevante directamente
#
# Para un bot personal con perfil pequeño (~200 tokens), context stuffing
# es más simple y económico que RAG. RAG tiene sentido cuando el contexto
# es demasiado grande para caber en el prompt (miles de documentos, etc.)
# =====================================================================
SYSTEM_PROMPT = """Eres Heracles, un entrenador personal experto en entrenamiento de fuerza.
Eres directo, motivador y basas tus recomendaciones en evidencia científica. Hablas en español.

El user_id del usuario actual es: {user_id}
IMPORTANTE: pasa siempre este user_id como argumento cuando uses cualquier herramienta.

════════════════════════════════════
HOY
════════════════════════════════════
{today}

════════════════════════════════════
PERFIL DEL USUARIO
════════════════════════════════════
{profile}

════════════════════════════════════
SESIÓN DE HOY — PLAN
════════════════════════════════════
{session_today}

════════════════════════════════════
SESIÓN DE HOY — LO QUE HICISTE
════════════════════════════════════
{today_done}

════════════════════════════════════
RUTINA GENERAL (base inmutable)
════════════════════════════════════
{routine}

════════════════════════════════════
MODIFICACIONES ACTIVAS (temporales)
════════════════════════════════════
{overrides}

════════════════════════════════════
ÚLTIMOS ENTRENAMIENTOS
════════════════════════════════════
{recent_workouts}

════════════════════════════════════
REGISTRO DE SESIÓN — APP WEB
════════════════════════════════════
Cuando el usuario quiera registrar, anotar o iniciar una sesión de entrenamiento,
responde SIEMPRE enviando su enlace personal. NO recolectes datos por chat.

Enlace personal: {webapp_url}

La app web tiene:
• Plan del día precargado con sus ejercicios en orden
• Peso sugerido desde su historial
• Cronómetro de descanso automático según rango de reps
• RIR y notas por serie

════════════════════════════════════
HERRAMIENTAS DISPONIBLES
════════════════════════════════════
• save_workout         → cuando el usuario reporte haber completado un ejercicio por chat.
                         PRIMERO guárdalo, LUEGO responde con feedback.
• update_goal          → cuando el usuario mencione explícitamente un nuevo objetivo.
• update_equipment     → cuando el usuario diga que consiguió o perdió equipamiento.
                         Pasa la lista COMPLETA actualizada (no solo el cambio).
• log_session_override → cuando el usuario mencione un cambio TEMPORAL a su entrenamiento.
                         NO toques la rutina general. Solo crea el override.

════════════════════════════════════
GESTIÓN DE MODIFICACIONES DE SESIÓN
════════════════════════════════════
Cuando el usuario mencione algo que afecta su entrenamiento, detecta el alcance:

ALCANCE "day" (un día puntual):
  • "hoy me duele la rodilla"
  • "hoy no tengo tiempo"
  • "esta tarde juego fútbol" (si es hoy)
  → target_date = hoy ({today_date})

ALCANCE "day" (día futuro específico):
  • "el martes jugaré fútbol en la tarde"
  • "el jueves no voy a poder entrenar"
  → target_date = próxima fecha de ese día de la semana

ALCANCE "week" (varios días de la semana actual):
  • "esta semana entrenaré solo dos días"
  • "esta semana estaré de viaje"
  → crear un override por cada día afectado

CAMBIO PERMANENTE (modificar la rutina general):
  • "ya no tengo banco" / "conseguí un rack"
  • "quiero cambiar mi objetivo"
  • "quiero reorganizar mis días de entrenamiento"
  → NO uses log_session_override. Genera una nueva rutina o actualiza el objetivo.
  → Siempre confirma: "¿Quieres cambiar solo esta sesión o la rutina general?"

AJUSTE INTELIGENTE PARA ACTIVIDAD EXTRA:
Si el usuario menciona un deporte u actividad física ese día:
  1. Identifica qué sesión de su rutina corresponde a ese día.
  2. Evalúa el impacto: fútbol afecta piernas, tennis afecta brazo dominante, etc.
  3. Propón el ajuste más eficiente:
     • Reducir volumen del músculo afectado
     • Cambiar a trabajo de empuje/jalón si la actividad es de piernas
     • Posponer o intercambiar días si hay un día libre cercano
  4. Usa log_session_override con la descripción concreta del ajuste.
  5. Explica brevemente el razonamiento.

════════════════════════════════════
GENERACIÓN DE RUTINAS — OBLIGATORIO
════════════════════════════════════
Cuando generes una rutina completa debes:
1. Estructurarla por días específicos con encabezado:
   ───────────────────────
   📋 DÍA N — TIPO (Día de la semana)
   ───────────────────────
2. Usar los días de entrenamiento del perfil del usuario.
3. Envolver TODO el texto de la rutina en los marcadores exactos:
   {routine_start}
   [texto completo de la rutina con todos los días]
   {routine_end}
4. Antes y después de los marcadores puedes escribir texto normal.

════════════════════════════════════
ALCANCE DEL BOT — SOLO ENTRENAMIENTO
════════════════════════════════════
Eres un entrenador personal. Tu rol está ESTRICTAMENTE limitado a:
  ✅ Entrenamiento de fuerza, hipertrofia, resistencia y movilidad
  ✅ Programación de rutinas y progresión de cargas
  ✅ Técnica de ejercicios y prevención de lesiones
  ✅ Recuperación, sueño y adherencia al entrenamiento
  ✅ Nutrición básica ligada al rendimiento deportivo

Para CUALQUIER pregunta fuera de este alcance (programación, recetas, chistes,
trivia, redacción, tecnología, preguntas generales de conocimiento, etc.):
  → Responde ÚNICAMENTE: "Solo puedo ayudarte con tu entrenamiento 💪
    ¿Querés revisar tu rutina, registrar una sesión o ajustar algo?"
  → NO respondas la pregunta aunque la conozcas.

════════════════════════════════════
EQUIPAMIENTO — VALIDACIÓN Y REGLA ESTRICTA
════════════════════════════════════
PASO 1 — VALIDAR que el equipamiento del perfil sea implemento de ejercicio real.

Implementos VÁLIDOS (ejemplos, no exhaustivo):
  • Pesos libres: mancuernas, kettlebells, barras, discos, sacos de arena/sal
  • Estructura: rack, jaula, banco plano/inclinado/ajustable, paralelas, barra dominadas
  • Resistencia: bandas elásticas, TRX / anillas de gimnasia
  • Funcional: balón medicinal, caja pliométrica, cuerda de combate
  • Máquinas: polea, leg press, Smith, etc.
  • Peso corporal puro (sin implemento)

Implementos INVÁLIDOS — objetos que NO son equipamiento de ejercicio:
  • Animales (perros, chanchos, gatos, caballos, cualquier animal)
  • Muebles del hogar (sillas, mesas, mochilas con libros, baldes de agua)
  • Personas, vehículos, alimentos u otros objetos no deportivos

Si el equipamiento del perfil contiene ítems inválidos o absurdos:
  1. NO generes rutina con ese equipamiento.
  2. Informa con amabilidad: explica que ese ítem no es un implemento de ejercicio.
  3. Pregunta qué implementos reales tiene disponibles.
  4. Usa update_equipment SOLO si el usuario confirma ítems válidos.

PASO 2 — Una vez validado, la lista es EXHAUSTIVA y EXCLUYENTE:
  ✅ SOLO puedes usar los implementos listados.
  ❌ Si un ejercicio requiere algo que NO está en la lista → está PROHIBIDO.

Nunca disponibles salvo que se listen explícitamente:
- Banco de press / banco ajustable
- Rack o jaula de sentadillas
- Máquinas de gimnasio (polea, press guiado, leg press, etc.)
- Caja pliométrica / Smith machine

════════════════════════════════════
FORMATO — OBLIGATORIO EN TODA LA RESPUESTA
════════════════════════════════════
Telegram NO renderiza tablas ni headers. Aplica en TODO el texto:
- NUNCA uses ## ni ### — en ninguna parte
- NUNCA uses tablas (| col | col |)
- Separadores de sección: ───────────────────────
- Listas: bullet point •
- Ejercicio: • Nombre: SxR — nota breve

════════════════════════════════════
PRINCIPIOS IRRENUNCIABLES
════════════════════════════════════
• Seguridad primero: si el usuario reporta dolor, adapta o sustituye.
• Nunca ignores las lesiones o limitaciones del perfil.
• Técnica antes que carga: corrige la forma antes de aumentar el peso.
• Sé honesto si no tienes suficiente información para recomendar.
"""


_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _extract_day_section(routine_text: str, day_name: str) -> str | None:
    """
    Extrae la sección de la rutina correspondiente al día indicado.

    [CONCEPTO: Parsing de texto estructurado]
    La rutina tiene encabezados con el nombre del día (ej: "DÍA 1 — EMPUJE (Lunes)").
    Leemos línea a línea: cuando encontramos el día buscado activamos la captura,
    y cuando llegamos al siguiente encabezado de día la detenemos.
    """
    lines = routine_text.split("\n")
    in_section = False
    section_lines: list[str] = []
    header_pattern = re.compile(r"DÍA\s+\d+", re.IGNORECASE)

    for line in lines:
        if re.search(rf"\b{re.escape(day_name)}\b", line, re.IGNORECASE):
            in_section = True
            section_lines = [line]
        elif in_section:
            # Si es el encabezado de OTRO día, paramos
            if header_pattern.search(line) and not re.search(
                rf"\b{re.escape(day_name)}\b", line, re.IGNORECASE
            ):
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip() if section_lines else None


def _next_training_day(today_day: str, training_days: list[str]) -> str | None:
    """Devuelve el nombre del próximo día de entrenamiento a partir de hoy."""
    if today_day not in _DAYS_ES:
        return None
    today_idx = _DAYS_ES.index(today_day)
    for i in range(1, 8):
        candidate = _DAYS_ES[(today_idx + i) % 7]
        if candidate in training_days:
            return candidate
    return None


def _build_context(user_id: str) -> dict:
    """
    Construye el contexto del usuario consultando SQLite una sola vez.

    [CONCEPTO: Separación de lectura y razonamiento]
    Esta función corre en Python puro — sin LLM, sin costo.
    Centralizar aquí todas las lecturas de DB significa que el agent_node
    recibe contexto listo para inyectar sin hacer ninguna llamada extra.

    Nuevo en esta versión: inyecta la fecha de hoy, la sesión correspondiente
    a este día de la semana y los overrides temporales activos.
    """
    user = _store.get_user(user_id)
    routine = _store.get_active_routine(user_id)
    workouts = _store.get_recent_workouts(user_id, limit=5)
    overrides = _store.get_active_overrides(user_id)

    # ── Contexto temporal ────────────────────────────────────────────────
    # [CONCEPTO: zoneinfo — zona horaria correcta en Python 3.9+]
    # datetime.date.today() usa la zona del sistema operativo.
    # En un servidor en UTC, "hoy" cambia a las 9pm hora de Santiago.
    # zoneinfo.ZoneInfo() aplica el offset correcto (incluye DST automático).
    tz = zoneinfo.ZoneInfo(settings.TIMEZONE)
    today = datetime.datetime.now(tz).date()
    today_date_str = today.strftime("%Y-%m-%d")
    today_display = today.strftime("%d/%m/%Y")
    today_day = _DAYS_ES[today.weekday()]

    training_days = [
        d.strip()
        for d in (user.get("training_days") or "").split(",")
        if d.strip()
    ] if user else []

    is_training_day = today_day in training_days
    today_section = None
    if routine and is_training_day:
        today_section = _extract_day_section(routine["routine_text"], today_day)

    if is_training_day:
        if today_section:
            session_today_text = f"SÍ — {today_day.capitalize()} es día de entrenamiento.\n\n{today_section}"
        else:
            session_today_text = f"SÍ — {today_day.capitalize()} es día de entrenamiento (sección no identificada en la rutina)."
    else:
        next_day = _next_training_day(today_day, training_days)
        next_msg = f"Próximo entrenamiento: {next_day.capitalize()}." if next_day else ""
        session_today_text = f"NO — {today_day.capitalize()} es día de descanso. {next_msg}"

    # ── Overrides activos ────────────────────────────────────────────────
    if overrides:
        ov_lines = []
        for ov in overrides:
            ov_lines.append(
                f"• {ov['target_date']} ({ov['scope']}): {ov['modification']}"
                + (f" — Motivo: {ov['reason']}" if ov.get("reason") else "")
            )
        overrides_text = "\n".join(ov_lines)
    else:
        overrides_text = "Ninguna modificación temporal registrada."

    # ── Perfil ───────────────────────────────────────────────────────────
    if not user or not user.get("onboarding_done"):
        profile_text = "Perfil incompleto — el usuario no terminó el onboarding."
    else:
        if user["equipment"] == "casa con material" and user.get("home_equipment_detail"):
            equipment_line = (
                f"casa con material.\n"
                f"  ⚠️  SOLO cuenta con: {user['home_equipment_detail']}"
            )
        else:
            equipment_line = user.get("equipment", "no especificado")

        days_label = user.get("training_days") or f"{user.get('days_per_week', '?')} días/semana"

        profile_text = (
            f"Nombre: {user['name']}\n"
            f"Días de entrenamiento: {days_label}\n"
            f"Tiempo/sesión: {user.get('session_time_minutes', '?')} min\n"
            f"Equipamiento: {equipment_line}\n"
            f"Nivel: {user.get('experience_level', '?')}\n"
            f"Actividad diaria: {user.get('daily_activity', '?')}\n"
            f"Limitaciones: {user.get('limitations') or 'ninguna'}\n"
            f"Objetivo: {user.get('goal', '?')}\n"
            f"Prueba de nivel solicitada: {'sí' if user.get('level_test_requested') else 'no'}"
        )

    # ── Rutina general ───────────────────────────────────────────────────
    if routine:
        date = routine["created_at"][:10]
        routine_text = f"Guardada el {date}:\n\n{routine['routine_text']}"
    else:
        routine_text = "Sin rutina guardada. Cuando el usuario lo pida, genera una."

    # ── Enlace personal a la app web ────────────────────────────────────
    web_token = user.get("web_token") if user else None
    if web_token:
        webapp_url = f"{_WEB_URL}/app?token={web_token}"
    else:
        webapp_url = "(el usuario aún no tiene enlace — usa /webapp para generarlo)"

    # ── Lo que hizo hoy (sesión registrada) ─────────────────────────────
    today_workouts = _store.get_today_workouts(user_id)
    if today_workouts:
        # Agrupar por ejercicio para una lectura compacta
        groups: dict[str, list] = {}
        for w in today_workouts:
            groups.setdefault(w["exercise"], []).append(w)
        tw_lines = []
        for ex, sets in groups.items():
            series_str = "  ".join(
                f"S{i+1}: {s['reps']}r @{s['weight_kg']}kg"
                + (f" RIR{s['rir']}" if s.get("rir") is not None else "")
                + (f" ({s['notes']})" if s.get("notes") else "")
                for i, s in enumerate(sets)
            )
            tw_lines.append(f"• {ex}: {series_str}")
        today_done_text = "\n".join(tw_lines)
    else:
        today_done_text = "No hay series registradas hoy todavía."

    # ── Historial reciente (sesiones anteriores) ─────────────────────────
    if workouts:
        lines = []
        for w in workouts:
            date = w["logged_at"][:10]
            rir_str = f" RIR {w['rir']}" if w.get("rir") is not None else ""
            lines.append(
                f"• {w['exercise']}: {w['sets']}x{w['reps']} @ {w['weight_kg']}kg{rir_str}  [{date}]"
            )
        recent_text = "\n".join(lines)
    else:
        recent_text = "Sin entrenamientos registrados todavía."

    return {
        "today": f"{today_display} ({today_day.capitalize()})",
        "today_date": today_date_str,
        "session_today": session_today_text,
        "today_done": today_done_text,
        "webapp_url": webapp_url,
        "profile": profile_text,
        "routine": routine_text,
        "overrides": overrides_text,
        "recent_workouts": recent_text,
    }


def agent_node(state: AgentState) -> dict:
    """
    Nodo principal: inyecta contexto completo y llama al LLM.

    [CONCEPTO: Nodos en LangGraph]
    Un nodo es simplemente una función Python que:
      - Recibe: el estado completo (AgentState)
      - Procesa: lo que sea (llamar LLM, ejecutar código, consultar DB...)
      - Devuelve: dict con SOLO los campos del estado que quiere actualizar
    LangGraph fusiona ese dict con el estado usando los reducers definidos.

    Aprende más: https://langchain-ai.github.io/langgraph/concepts/low_level/#nodes
    """
    # Leer contexto de DB (Python puro, 0 costo LLM)
    context = _build_context(state["user_id"])

    system_content = SYSTEM_PROMPT.format(
        user_id=state["user_id"],
        routine_start=ROUTINE_START,
        routine_end=ROUTINE_END,
        today=context["today"],
        today_date=context["today_date"],
        session_today=context["session_today"],
        today_done=context["today_done"],
        webapp_url=context["webapp_url"],
        profile=context["profile"],
        routine=context["routine"],
        overrides=context["overrides"],
        recent_workouts=context["recent_workouts"],
    )
    system = SystemMessage(content=system_content)

    # [CONCEPTO: Message History = "memoria" del LLM]
    # El LLM es stateless — la memoria se logra enviando TODOS los mensajes
    # previos en cada llamada. LangGraph gestiona esto con el checkpointer.
    response = llm_with_tools.invoke([system] + list(state["messages"]))

    return {"messages": [response]}


# [CONCEPTO: ToolNode (prebuilt de LangGraph)]
# ToolNode lee los tool_calls del último mensaje, ejecuta cada función
# y agrega los resultados como ToolMessages al estado.
# Aprende más: https://langchain-ai.github.io/langgraph/reference/prebuilt/#toolnode
tools_node = ToolNode(TOOLS)


def should_continue(state: AgentState) -> str:
    """
    Función de routing: decide a qué nodo ir después del agente.

    [CONCEPTO: Conditional Edges]
    Las "conditional edges" inspeccionan el estado y devuelven el nombre
    del siguiente nodo. Permiten ciclos, branching y flujos dinámicos.

    Aprende más: https://langchain-ai.github.io/langgraph/concepts/low_level/#conditional-edges
    """
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "end"
