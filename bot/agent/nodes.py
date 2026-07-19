import datetime
import re
import zoneinfo
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from bot.agent.contracts import AgentResponse, Intent
from bot.agent.intent import allowed_tools_for_intent, classify_intent_text
from bot.agent.prompts import build_system_prompt
from bot.config import settings
from bot.agent.runtime import AgentRuntimeContext, current_agent_context
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

_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _extract_day_section(routine_text: str, day_name: str) -> str | None:
    """
    Extrae la sección de la rutina correspondiente al día indicado.

    [CONCEPTO: Parsing de texto estructurado]
    La rutina tiene encabezados con el nombre del día (ej: "DÍA 1 — EMPUJE (Lunes)").
    Leemos línea a línea: activamos la captura SOLO cuando la línea es un
    encabezado "DÍA N" que menciona el día buscado, y la detenemos al llegar
    al encabezado de otro día. Si solo buscáramos el nombre del día en
    cualquier línea (sin exigir que sea un encabezado), una nota como
    "puedes moverlo al {day}" dentro de OTRO día cortaría o reiniciaría
    la sección equivocada — la causa real de que el agente respondiera
    con el bloque de un día distinto al que preguntaba el usuario.
    """
    lines = routine_text.split("\n")
    in_section = False
    section_lines: list[str] = []
    header_pattern = re.compile(r"DÍA\s+\d+", re.IGNORECASE)
    day_pattern = re.compile(rf"\b{re.escape(day_name)}\b", re.IGNORECASE)

    for line in lines:
        if header_pattern.search(line):
            if day_pattern.search(line):
                in_section = True
                section_lines = [line]
            elif in_section:
                break
        elif in_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip() if section_lines else None


_EXERCISE_LINE_RE = re.compile(r"^([•\-\*]\s+)([^:]+?)(:.*)$")


def _annotate_routine_with_weights(routine_text: str, user_id: str) -> str:
    """
    Anota cada línea de ejercicio con la progresión calculada más reciente.

    El texto de routine_text es una FOTO tomada cuando se guardó la rutina
    (con save_routine o el patrón de marcadores). Cada sesión web termina
    recalculando next_weight/next_reps en progression_targets, pero eso nunca
    reescribe la rutina guardada — por eso el mismo ejercicio podía verse con
    pesos o rangos de reps distintos entre lo que decía la rutina general y lo
    que la app web ya estaba sugiriendo. Anotamos aquí en tiempo real (misma
    fuente que usa la web, get_progression_target / get_last_weight_for_exercise)
    para que el bloque "RUTINA GENERAL" del prompt siempre hable con la
    progresión vigente sin depender de que el LLM reescriba el texto guardado.
    """
    annotated_lines = []
    for line in routine_text.split("\n"):
        stripped = line.strip()
        match = _EXERCISE_LINE_RE.match(stripped)
        if match:
            name = match.group(2).strip()
            if 2 < len(name) < 50 and not name.lower().startswith("circuito"):
                indent = line[: len(line) - len(line.lstrip())]
                target = _store.get_progression_target(user_id, name)
                if target is not None:
                    reps_part = (
                        f", {target['next_reps']} reps"
                        if target.get("next_reps")
                        else ""
                    )
                    sets_part = (
                        f", {target['next_sets']} series"
                        if target.get("next_sets")
                        else ""
                    )
                    annotated_lines.append(
                        f"{indent}{stripped}  → progresión calculada: {target['next_weight']} kg{reps_part}{sets_part}"
                        + (f" ({target['basis']})" if target.get("basis") else "")
                    )
                    continue
                weight = _store.get_last_weight_for_exercise(user_id, name)
                if weight is not None:
                    annotated_lines.append(
                        f"{indent}{stripped}  → peso sugerido: {weight} kg"
                    )
                    continue
        annotated_lines.append(line)
    return "\n".join(annotated_lines)


_SETSREPS_RE = re.compile(r"(\d+)x([\d\-]+)")
_WEIGHT_RE = re.compile(r"@\s*[\d.]+(?:-[\d.]+)?\s*kg", re.IGNORECASE)


def _format_weight(weight: float) -> str:
    return str(int(weight)) if weight == int(weight) else str(weight)


def apply_progression_to_routine_text(routine_text: str, user_id: str) -> str:
    """
    Reescribe series, reps y peso de cada línea de ejercicio con la progresión
    que el agente acaba de calcular al terminar la sesión.

    A diferencia de _annotate_routine_with_weights (que solo anota al vuelo
    para el contexto del chat), esto persiste el ajuste en el texto guardado
    de la rutina general — así /rutina y la app web muestran las mismas
    series/reps/peso sin depender de que el usuario pregunte por chat.
    """
    updated_lines = []
    for line in routine_text.split("\n"):
        stripped = line.strip()
        match = _EXERCISE_LINE_RE.match(stripped)
        if match:
            bullet, name, tail = match.group(1), match.group(2).strip(), match.group(3)
            if 2 < len(name) < 50 and not name.lower().startswith("circuito"):
                target = _store.get_progression_target(user_id, name)
                if target is not None:
                    next_sets = target.get("next_sets")
                    next_reps = target.get("next_reps")
                    if next_sets or next_reps:

                        def _replace_setsreps(m: re.Match) -> str:
                            sets = str(next_sets) if next_sets else m.group(1)
                            reps = next_reps if next_reps else m.group(2)
                            # Si next_reps trae unidad ("40-45 seg") y la línea
                            # original ya la tiene después del match ("3x40 seg"),
                            # quitarla del reemplazo para no duplicar "seg seg".
                            following = m.string[m.end() :].lstrip()
                            if " " in reps:
                                unit = reps.rsplit(" ", 1)[1]
                                if following.lower().startswith(unit.lower()):
                                    reps = reps.rsplit(" ", 1)[0]
                            return f"{sets}x{reps}"

                        tail = _SETSREPS_RE.sub(_replace_setsreps, tail, count=1)
                    next_weight = target.get("next_weight")
                    if next_weight and _WEIGHT_RE.search(tail):
                        tail = _WEIGHT_RE.sub(
                            f"@ {_format_weight(next_weight)} kg", tail, count=1
                        )
                    indent = line[: len(line) - len(line.lstrip())]
                    updated_lines.append(f"{indent}{bullet}{name}{tail}")
                    continue
        updated_lines.append(line)
    return "\n".join(updated_lines)


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


def _format_series_line(sets: list[dict]) -> str:
    """
    Formatea las series de un ejercicio en una línea compacta para el prompt.

    Maneja los dos orígenes de datos:
    • App web: cada serie es una fila con sets=1 → se numeran S1, S2, S3...
    • Chat (save_workout): una fila agregada con sets>1 → se muestra "4x10r".
    """
    parts = []
    serie_n = 0
    for s in sets:
        if (s.get("sets") or 1) > 1:
            part = f"{s['sets']}x{s['reps']}r @{s['weight_kg']}kg"
        else:
            serie_n += 1
            part = f"S{serie_n}: {s['reps']}r @{s['weight_kg']}kg"
        if s.get("rpe") is not None:
            part += f" RPE{s['rpe']}"
        if s.get("notes"):
            part += f" ({s['notes']})"
        parts.append(part)
    return "  ".join(parts)


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
    workouts = _store.get_recent_workouts(user_id, days=5)
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

    training_days = (
        [d.strip() for d in (user.get("training_days") or "").split(",") if d.strip()]
        if user
        else []
    )

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
        next_msg = (
            f"Próximo entrenamiento: {next_day.capitalize()}." if next_day else ""
        )
        session_today_text = (
            f"NO — {today_day.capitalize()} es día de descanso. {next_msg}"
        )

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
        if user["equipment"] == "casa con material" and user.get(
            "home_equipment_detail"
        ):
            equipment_line = (
                f"casa con material.\n"
                f"  ⚠️  SOLO cuenta con: {user['home_equipment_detail']}"
            )
        else:
            equipment_line = user.get("equipment", "no especificado")

        days_label = (
            user.get("training_days") or f"{user.get('days_per_week', '?')} días/semana"
        )

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
        annotated_routine = _annotate_routine_with_weights(
            routine["routine_text"], user_id
        )
        routine_text = f"Guardada el {date}:\n\n{annotated_routine}"
    else:
        routine_text = "Sin rutina guardada. Cuando el usuario lo pida, genera una."

    # ── Enlace personal a la app web ────────────────────────────────────
    if user:
        web_token = _store.get_or_create_web_token(user_id)
        webapp_url = f"{_WEB_URL}/app?token={web_token}"
    else:
        webapp_url = "(enlace no disponible hasta que el usuario complete su perfil)"

    # ── Lo que hizo hoy (sesión registrada) ─────────────────────────────
    today_workouts = _store.get_today_workouts(user_id)
    if today_workouts:
        # Agrupar por ejercicio para una lectura compacta
        groups: dict[str, list] = {}
        for w in today_workouts:
            groups.setdefault(w["exercise"], []).append(w)
        tw_lines = [
            f"• {ex}: {_format_series_line(sets)}" for ex, sets in groups.items()
        ]
        today_done_text = "\n".join(tw_lines)
    else:
        today_done_text = "No hay series registradas hoy todavía."

    # ── Historial reciente (sesiones anteriores) ─────────────────────────
    # Las filas ya traen 'local_date' convertida a la timezone del negocio.
    # Se agrupa por fecha + ejercicio para que cada sesión pasada se lea como
    # un bloque completo (con RPE y notas), igual que la sesión de hoy.
    # Hoy se excluye: ya está en "SESIÓN DE HOY — LO QUE HICISTE".
    past = [w for w in workouts if w["local_date"] != today_date_str]
    if past:
        by_date: dict[str, dict[str, list]] = {}
        for w in reversed(past):  # orden cronológico para numerar S1, S2...
            by_date.setdefault(w["local_date"], {}).setdefault(
                w["exercise"], []
            ).append(w)
        lines = []
        for date_str in sorted(by_date, reverse=True):
            lines.append(f"📅 {date_str}:")
            for ex, sets in by_date[date_str].items():
                lines.append(f"• {ex}: {_format_series_line(sets)}")
        recent_text = "\n".join(lines)
    else:
        recent_text = "Sin entrenamientos registrados en días anteriores."

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


def _latest_human_message(state: AgentState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return str(state["messages"][-1].content)


def classify_intent_node(state: AgentState) -> dict:
    intent = classify_intent_text(_latest_human_message(state))
    return {"intent": intent}


def direct_response_node(state: AgentState) -> dict:
    context = _build_context(state["user_id"])
    intent = state.get("intent", Intent.OUT_OF_SCOPE)
    if intent == Intent.TODAY_PLAN:
        response = AgentResponse(message=context["session_today"])
    elif intent == Intent.ROUTINE:
        response = AgentResponse(message=context["routine"])
    elif intent == Intent.HISTORY:
        response = AgentResponse(message=context["recent_workouts"])
    else:
        response = AgentResponse(
            message="Solo puedo ayudarte con tu entrenamiento. ¿Quieres revisar tu rutina, registrar una sesión o ajustar algo?"
        )
    return {"messages": [AIMessage(content=response.message)], "response": response}


def route_after_intent(state: AgentState) -> str:
    if state.get("intent") in {
        Intent.TODAY_PLAN,
        Intent.ROUTINE,
        Intent.HISTORY,
    }:
        return "direct_response"
    return "agent"


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

    system_content = build_system_prompt(context)
    system = SystemMessage(content=system_content)

    # [CONCEPTO: Message History = "memoria" del LLM]
    # El LLM es stateless — la memoria se logra enviando TODOS los mensajes
    # previos en cada llamada. LangGraph gestiona esto con el checkpointer.
    allowed_tool_names = allowed_tools_for_intent(
        state.get("intent", Intent.OUT_OF_SCOPE)
    )
    allowed_tools = [tool for tool in TOOLS if tool.name in allowed_tool_names]
    runnable = llm.bind_tools(allowed_tools) if allowed_tools else llm
    response = runnable.invoke([system] + list(state["messages"]))

    return {"messages": [response]}


# [CONCEPTO: ToolNode (prebuilt de LangGraph)]
# ToolNode lee los tool_calls del último mensaje, ejecuta cada función
# y agrega los resultados como ToolMessages al estado.
# Aprende más: https://langchain-ai.github.io/langgraph/reference/prebuilt/#toolnode
_tool_node = ToolNode(TOOLS)


def tools_node(state: AgentState) -> dict:
    token = current_agent_context.set(
        AgentRuntimeContext(
            user_id=state["user_id"],
            channel=state.get("channel", "telegram"),
        )
    )
    try:
        return _tool_node.invoke(state)
    finally:
        current_agent_context.reset(token)


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
