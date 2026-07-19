# Heracles 2.0 — Guía de actualización desde VS Code

Documento técnico para transformar `HeraclesBotStudy` desde un bot de Telegram experimental en un backend de agente confiable, preparado para una aplicación móvil.

## 1. Objetivo y alcance

El objetivo inmediato no es construir la aplicación móvil. Primero se estabilizará el agente y su modelo de dominio para que Telegram, la web actual y la futura app consuman la misma lógica.

Resultados esperados:

- El modelo no puede elegir ni modificar la identidad del usuario.
- Las progresiones son propuestas por el agente, validadas por el backend y tienen fallback determinístico.
- Las respuestas del modelo que producen datos usan esquemas Pydantic.
- Una rutina propuesta no se guarda sin confirmación explícita.
- Las operaciones de finalizar sesión son idempotentes.
- La memoria deja de depender de RAM antes del despliegue móvil.
- Cada comportamiento crítico tiene pruebas automatizadas.
- Telegram queda como adaptador opcional, no como núcleo del sistema.

Fuera de alcance por ahora:

- React Native/Expo.
- MCP.
- RAG o base vectorial.
- Arquitectura multiagente.
- Microservicios.

## 2. Principios de diseño

1. **El agente entrena; el backend valida.** El LLM puede proponer progresiones según perfil, historial y rendimiento, pero permisos, fechas, identidad, guardrails y persistencia pertenecen al backend.
2. **El estado real vive en la base de datos.** La conversación no reemplaza el perfil, la rutina ni el historial.
3. **Todo dato generado por un modelo se valida.** Ningún JSON libre se persiste directamente.
4. **Las escrituras importantes son confirmables y reversibles.** Una rutina completa siempre pasa por borrador y confirmación.
5. **Telegram es un canal.** La lógica del agente no debe producir enlaces o formatos exclusivos de Telegram.
6. **Una sola fuente de verdad.** No mantener simultáneamente marcadores de texto y herramientas para guardar la misma entidad.

## 3. Estado actual relevante

Archivos principales:

```text
bot/
├── agent/
│   ├── graph.py       # grafo ReAct y MemorySaver
│   ├── nodes.py       # prompt, contexto, llamada al modelo y progresión textual
│   ├── state.py       # estado mínimo: messages + user_id
│   └── tools.py       # seis herramientas de escritura
├── handlers/
│   ├── onboarding.py  # onboarding dependiente de Telegram
│   ├── telegram.py    # canal Telegram y guardado por marcadores
│   └── web_api.py     # app web y evaluación de sesión
└── storage/
    └── user_store.py  # SQLite y migraciones manuales
```

Riesgos actuales que esta guía corrige:

- `user_id` es un argumento controlado por el LLM en todas las herramientas.
- `MemorySaver` pierde conversaciones al reiniciar y puede crecer sin límite.
- Las rutinas son texto libre interpretado con expresiones regulares.
- `save_routine` y `<<<RUTINA>>>` implementan dos caminos de persistencia.
- La progresión no debe persistir una respuesta JSON libre del modelo: el agente propone bajo contrato y el backend valida límites de seguridad antes de guardar.
- `finish_session` puede ejecutarse más de una vez.
- No hay pruebas ni validación estricta de las decisiones del agente.

## 4. Estrategia de ramas y commits

Crear una rama antes de modificar:

```bash
git switch -c refactor/heracles-agent-v2
```

Hacer un commit por tarea terminada:

```text
test: add current agent characterization tests
refactor: inject trusted user context into tools
feat: add structured agent contracts
feat: add deterministic progression engine
refactor: replace routine markers with draft workflow
feat: make session completion idempotent
feat: add persistent agent checkpoints
```

No mezclar migración de base de datos, aplicación móvil y cambios del agente en un mismo commit.

## 5. Preparación en VS Code

### 5.1 Abrir el proyecto

Descomprimir el ZIP y abrir la carpeta que contiene `requirements.txt`:

```bash
code HeraclesBotStudy-main
```

### 5.2 Entorno virtual

En la terminal integrada:

```bash
python -m venv .venv
```

Activar en Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Activar en Linux/macOS:

```bash
source .venv/bin/activate
```

Instalar dependencias:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Seleccionar `.venv` mediante `Python: Select Interpreter` en la paleta de comandos.

### 5.3 Dependencias de desarrollo

Agregar inicialmente a `requirements-dev.txt`:

```text
pytest>=8.0
pytest-asyncio>=0.24
httpx>=0.27
ruff>=0.9
mypy>=1.14
```

Instalar:

```bash
pip install -r requirements-dev.txt
```

### 5.4 Configuración recomendada de VS Code

Crear `.vscode/settings.json`:

```json
{
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  "python.testing.pytestArgs": ["tests"],
  "python.analysis.typeCheckingMode": "basic",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "ruff.lint.run": "onSave"
}
```

## 6. Arquitectura objetivo

```text
bot/
├── api/
│   ├── dependencies.py       # usuario autenticado y contexto confiable
│   └── routers/
├── agent/
│   ├── graph.py
│   ├── state.py
│   ├── context.py            # construcción de contexto
│   ├── contracts.py          # respuestas Pydantic
│   ├── policies.py           # permisos y confirmaciones
│   ├── tools.py
│   └── prompts/
│       ├── identity.md
│       ├── safety.md
│       ├── conversation.md
│       ├── routine.md
│       └── session.md
├── domain/
│   ├── exercises.py
│   ├── routines.py
│   ├── sessions.py
│   └── progression.py
├── services/
│   ├── agent_service.py
│   ├── routine_service.py
│   └── session_service.py
├── channels/
│   ├── telegram.py
│   └── web.py
└── storage/
    ├── repositories.py
    └── user_store.py          # temporal durante migración
```

No es necesario crear toda esta estructura de una vez. Cada hito siguiente introduce solo los componentes que necesita.

---

# Hito 0 — Congelar el comportamiento actual con pruebas

## Objetivo

Poder refactorizar sin romper silenciosamente el proyecto.

## Archivos nuevos

```text
tests/
├── conftest.py
├── test_routine_parser.py
├── test_progression_text.py
├── test_web_api.py
└── test_user_store.py
```

## Casos mínimos

### Parser de rutina

- Extrae el día correcto aunque otro día sea mencionado en una nota.
- Reconoce `3x8`, `3x8-10` y circuitos.
- No interpreta el encabezado del circuito como ejercicio.
- Conserva unidades de tiempo sin duplicar `seg`.

### Base de datos

- Crear usuario no duplica filas.
- Guardar rutina desactiva la anterior.
- Guardar una serie conserva RPE y notas.
- Un objetivo de progresión reemplaza solamente el ejercicio correcto.

### API

- Token inválido devuelve `401` o `403` de manera consistente.
- Plan del día corresponde a la zona `America/Santiago`.
- Finalizar sin series devuelve resultado vacío controlado.

### Test de caracterización de progresión textual

- Actualiza series y repeticiones del ejercicio correcto.
- No cambia otro ejercicio con nombre parecido.
- No agrega peso cuando `next_weight == 0`.

## Criterio de aceptación

```bash
pytest -q
```

Debe finalizar sin errores antes de comenzar el Hito 1.

---

# Hito 1 — Proteger la identidad del usuario

## Problema

El modelo recibe `user_id` y debe devolverlo en cada tool call. La identidad no puede depender de una instrucción del prompt.

## Cambio de estado

Actualizar `bot/agent/state.py`:

```python
from typing import Annotated, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    channel: str
```

`user_id` sigue existiendo en el estado interno, pero no en los argumentos visibles de las herramientas.

## Contexto de ejecución

Crear `bot/agent/runtime.py`:

```python
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
```

Este adaptador permite corregir el problema sin bloquearse por una versión concreta de LangGraph. Si la versión instalada soporta inyección nativa de contexto en tools, preferirla posteriormente.

## Modificar herramientas

Antes:

```python
@tool
def update_goal(user_id: str, new_goal: str) -> str:
    _store.update_goal(user_id, new_goal)
```

Después:

```python
@tool
def update_goal(new_goal: str) -> str:
    context = require_agent_context()
    _store.update_goal(context.user_id, new_goal)
    return f"Objetivo actualizado: {new_goal}"
```

Aplicar a las seis herramientas y eliminar del prompt:

```text
El user_id del usuario actual es...
IMPORTANTE: pasa siempre este user_id...
```

## Envolver la ejecución

En el servicio que invoque el grafo:

```python
token = current_agent_context.set(
    AgentRuntimeContext(user_id=user_id, channel=channel)
)
try:
    result = await agent_graph.ainvoke(...)
finally:
    current_agent_context.reset(token)
```

## Pruebas

- El esquema JSON de cada herramienta no contiene `user_id`.
- Una ejecución para usuario A nunca escribe datos del usuario B.
- Una herramienta sin contexto falla sin tocar la base de datos.

## Criterio de aceptación

- Buscar `user_id:` en `bot/agent/tools.py` no devuelve parámetros de herramientas.
- Todos los tests anteriores continúan pasando.

---

# Hito 2 — Contratos estructurados y límites

## Crear `bot/agent/contracts.py`

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Intent(StrEnum):
    TODAY_PLAN = "today_plan"
    LOG_WORKOUT = "log_workout"
    MODIFY_SESSION = "modify_session"
    CREATE_ROUTINE = "create_routine"
    EVALUATE_SESSION = "evaluate_session"
    UPDATE_PROFILE = "update_profile"
    HISTORY = "history"
    LIMITATION = "limitation"
    OUT_OF_SCOPE = "out_of_scope"


class ProgressionReason(StrEnum):
    BUILD_REPS = "build_reps"
    ADD_SET = "add_set"
    ADD_WEIGHT = "add_weight"
    CONSOLIDATE = "consolidate"
    INSUFFICIENT_DATA = "insufficient_data"


class ProgressionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(min_length=1, max_length=100)
    next_weight: float = Field(ge=0, le=500)
    next_sets: int = Field(ge=1, le=8)
    next_reps_min: int = Field(ge=1, le=100)
    next_reps_max: int = Field(ge=1, le=100)
    reason: ProgressionReason

    @model_validator(mode="after")
    def validate_rep_range(self):
        if self.next_reps_min > self.next_reps_max:
            raise ValueError("next_reps_min cannot exceed next_reps_max")
        return self


class SessionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    decisions: list[ProgressionDecision]
```

## Reglas de validación adicionales

Antes de persistir una decisión:

- `exercise_id` debe pertenecer a la sesión finalizada.
- No puede existir más de una decisión para el mismo ejercicio.
- El peso debe ser representable con los incrementos disponibles.
- El modelo no puede crear ejercicios durante una evaluación.
- Si la estructura no valida, usar el cálculo determinista como fallback.

## Límite de ciclo del agente

Configurar un límite de recursión al invocar LangGraph:

```python
config = {
    "configurable": {"thread_id": user_id},
    "recursion_limit": 8,
}
```

Capturar el error de límite y devolver un mensaje controlado sin repetir escrituras.

## Criterio de aceptación

- JSON con campos extra es rechazado.
- Pesos negativos, cero series o rangos invertidos son rechazados.
- Ningún bucle supera el límite configurado.

---

# Hito 3 — Progresión híbrida agente + guardrails

## Objetivo

Permitir que el agente actúe como entrenador inteligente, usando perfil,
historial, RPE, notas y evolución personal para proponer la próxima carga. El
backend no decide todos los números por defecto: valida que la propuesta cumpla
límites conservadores y usa un motor determinístico solo como fallback.

## Crear `bot/domain/progression.py`

Modelos de entrada sugeridos:

```python
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ProgressionAction(StrEnum):
    BUILD_REPS = "build_reps"
    ADD_SET = "add_set"
    ADD_WEIGHT = "add_weight"
    CONSOLIDATE = "consolidate"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class Prescription:
    exercise_id: str
    weight: Decimal
    sets: int
    reps_min: int
    reps_max: int
    max_sets: int
    weight_increment: Decimal


@dataclass(frozen=True)
class CompletedSet:
    reps: int
    weight: Decimal
    rpe: int | None


@dataclass(frozen=True)
class ProgressionResult:
    exercise_id: str
    next_weight: Decimal
    next_sets: int
    next_reps_min: int
    next_reps_max: int
    action: ProgressionAction
```

## Fallback determinístico

Mantenerlo simple y explícito para cuando el modelo no esté disponible, su JSON
no valide o una decisión sea riesgosa:

1. Sin suficientes series o sin prescripción válida: `INSUFFICIENT_DATA`.
2. Si alguna serie queda bajo el mínimo o existe RPE alto: `CONSOLIDATE`.
3. Si no todas las series alcanzan el techo: `BUILD_REPS` sin cambiar peso ni series.
4. Si todas alcanzan el techo con margen y `sets < max_sets`: `ADD_SET`.
5. Si todas alcanzan el techo, ya está en `max_sets` y el esfuerzo permite progresar: `ADD_WEIGHT`, usando exactamente `weight_increment`.
6. Cambiar una sola palanca por decisión.

No interpretar una molestia o dolor mediante esta función. Esos casos deben salir
del flujo automático y crear una propuesta temporal conservadora.

## Uso en `finish_session`

Flujo objetivo:

1. Construir contexto con perfil, rutina, series de hoy, RPE, notas e historial.
2. Pedir al agente un `SessionEvaluation` JSON con decisiones por ejercicio.
3. Validar contrato Pydantic y guardrails de backend.
4. Aceptar decisiones válidas.
5. Reemplazar decisiones inválidas o faltantes por fallback determinístico.
6. Persistir `progression_targets`.

Si falla el LLM, la sesión igualmente debe finalizar y guardar decisiones
conservadoras. La explicación puede usar una plantilla local.

## Guardrails mínimos

- No persistir ejercicios desconocidos ni duplicados.
- Exigir pesos en incrementos disponibles.
- Bloquear aumentos de peso o volumen si hay dolor o molestia reportada.
- Bloquear aumentos de peso con RPE alto o rendimiento bajo el mínimo.
- Limitar aumentos de carga a un incremento disponible por sesión.
- Permitir reducciones de carga o series dentro de límites razonables.
- No agregar peso externo automáticamente a ejercicios registrados con 0 kg.

## Pruebas parametrizadas obligatorias

| Situación | Resultado esperado |
|---|---|
| Faltan series | `INSUFFICIENT_DATA` o `CONSOLIDATE` según política |
| Repeticiones bajo mínimo | `CONSOLIDATE` |
| RPE alto | `CONSOLIDATE` |
| No alcanza techo en todas | `BUILD_REPS` |
| Techo completo y permite otra serie | `ADD_SET` |
| Techo completo, máximo de series | `ADD_WEIGHT` |
| Peso corporal | Nunca agrega peso salvo configuración explícita |
| Incremento 2.5 kg | Nunca propone 3, 4 o 5 kg |

## Criterio de aceptación

Ejecutar dos veces la función con la misma entrada produce exactamente el mismo resultado y no requiere clave de API.

---

# Hito 4 — Rutinas estructuradas y confirmación

## Objetivo

Eliminar gradualmente la dependencia de texto libre y los marcadores automáticos.

## Modelos iniciales

Crear `bot/domain/routines.py`:

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class BlockType(StrEnum):
    STRAIGHT_SETS = "straight_sets"
    CIRCUIT = "circuit"


class RoutineExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    order: int = Field(ge=1)
    sets: int = Field(ge=1, le=8)
    reps_min: int = Field(ge=1, le=100)
    reps_max: int = Field(ge=1, le=100)
    rest_seconds: int = Field(ge=0, le=600)
    initial_weight: float = Field(ge=0, le=500)


class RoutineBlock(BaseModel):
    type: BlockType
    order: int = Field(ge=1)
    rounds: int | None = Field(default=None, ge=1, le=10)
    exercises: list[RoutineExercise]


class RoutineDay(BaseModel):
    weekday: str
    order: int = Field(ge=1, le=7)
    blocks: list[RoutineBlock]


class RoutineDraft(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    days: list[RoutineDay]
```

## Flujo de negocio

```text
Usuario solicita rutina
→ agente genera RoutineDraft
→ Pydantic valida
→ backend valida equipamiento, días y duplicados
→ se guarda como draft
→ cliente muestra vista previa
→ usuario confirma
→ servicio crea versión activa
```

## Migración compatible

No eliminar `routine_text` al principio.

Agregar inicialmente:

- `routine_json` nullable.
- `status`: `draft`, `active`, `archived`.
- `version`.
- `confirmed_at`.

El backend debe preferir `routine_json`. Si está vacío, usa temporalmente el parser actual.

## Eliminar duplicación

Cuando el flujo estructurado esté probado:

- Eliminar `ROUTINE_START` y `ROUTINE_END`.
- Eliminar `_extract_and_save_routine()`.
- Conservar una sola operación: crear borrador.
- Activar rutina mediante endpoint o callback explícito.

## Criterio de aceptación

- Pedir una rutina no reemplaza la rutina activa.
- Confirmarla crea una versión nueva y archiva la anterior.
- Cancelarla no modifica datos activos.
- La rutina puede renderizarse sin expresiones regulares.

---

# Hito 5 — Sesiones idempotentes

## Modelo necesario

Crear una entidad `training_sessions`:

```sql
CREATE TABLE training_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    routine_id INTEGER,
    scheduled_date TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    evaluated_at TEXT,
    UNIQUE(user_id, scheduled_date, routine_id)
);
```

Relacionar cada serie con `session_id`.

## Estados

```text
planned → in_progress → completed → evaluated
                    ↘ cancelled
```

Una sesión `evaluated` no vuelve a calcularse. El endpoint devuelve el resultado ya almacenado.

## Endpoint

```http
POST /api/sessions/{session_id}/finish
Idempotency-Key: <uuid>
Authorization: Bearer <token>
```

## Transacción

La operación debe:

1. Bloquear o verificar el estado de la sesión.
2. Cambiar a `completed`.
3. Calcular progresiones.
4. Guardar decisiones.
5. Cambiar a `evaluated`.
6. Confirmar la transacción.

Si se repite, devuelve la evaluación existente.

## Criterio de aceptación

Dos solicitudes simultáneas con el mismo identificador producen una sola evaluación y un solo conjunto de progresiones.

---

# Hito 6 — Separar prompt, intención y canal

## Prompt modular

Mover el prompt monolítico a archivos separados:

```text
bot/agent/prompts/
├── identity.md
├── scope.md
├── safety.md
├── conversation.md
├── routine_generation.md
├── session_adjustment.md
└── progression_explanation.md
```

Eliminar reglas visuales de Telegram del prompt base. El canal formatea la respuesta después.

## Router de intención

Implementar primero un router simple con reglas para acciones inequívocas y modelo estructurado para casos ambiguos.

Rutas:

```text
today_plan
log_workout
modify_session
create_routine
evaluate_session
update_profile
history
limitation
out_of_scope
```

## Nuevo grafo

```text
START
  → classify_intent
  → load_context
  → policy_check
  → route
      ├─ direct_query
      ├─ deterministic_calculation
      ├─ draft_change
      └─ conversational_response
  → format_response
  → END
```

Mantener el ciclo de herramientas solamente en las rutas que realmente lo necesitan.

## Adaptadores de canal

Crear una respuesta neutral:

```python
class AgentResponse(BaseModel):
    message: str
    actions: list[dict] = []
    requires_confirmation: bool = False
```

Telegram transforma `actions` en botones. La aplicación móvil las transforma en componentes nativos.

## Criterio de aceptación

- Consultar el plan no expone herramientas de escritura innecesarias.
- La misma consulta produce contenido equivalente en web y Telegram.
- El prompt base no contiene URLs ni restricciones de formato de Telegram.

---

# Hito 7 — Persistencia y PostgreSQL

Realizar este hito después de estabilizar los contratos.

## Dependencias previstas

```text
sqlalchemy[asyncio]
asyncpg
alembic
psycopg[binary]
langgraph-checkpoint-postgres
```

Verificar nombres y versiones en la documentación oficial antes de instalarlas, porque estas bibliotecas evolucionan.

## Cambios

- Crear `DATABASE_URL`.
- Mantener SQLite solo para tests locales simples.
- Usar Alembic desde la primera migración PostgreSQL.
- Sustituir consultas directas por repositorios.
- Configurar checkpointer persistente.
- Definir una política de resumen o poda de mensajes.

## Identidad

Dejar de usar `telegram_id` como clave primaria. Crear:

```text
users.id: UUID
external_identities:
  user_id
  provider: telegram | email | google
  provider_user_id
```

Esto permitirá que una cuenta móvil pueda vincular posteriormente Telegram sin duplicar el perfil.

## Criterio de aceptación

- Reiniciar el backend no borra memoria ni datos.
- Dos procesos pueden atender usuarios sin usar memoria local compartida.
- Las migraciones se aplican en una base vacía y sobre una copia de datos existentes.

---

# Hito 8 — Observabilidad y evaluaciones

## Logging estructurado

Cada solicitud debe registrar:

- `request_id`.
- `user_id` anonimizado.
- `session_id`.
- Intención detectada.
- Modelo y versión del prompt.
- Latencia.
- Número de llamadas al LLM.
- Herramientas ejecutadas.
- Tokens y costo cuando el proveedor lo informe.
- Resultado de validación.

No registrar tokens, contraseñas, texto sensible completo ni claves de API.

## Dataset de evaluación

Crear `tests/evals/cases.jsonl` con casos representativos:

```json
{"id":"plan_today","message":"¿Qué me corresponde hoy?","expected_intent":"today_plan","allowed_tools":[]}
{"id":"temporary_change","message":"Hoy no tengo acceso a las mancuernas","expected_intent":"modify_session","allowed_tools":["create_session_override_draft"]}
{"id":"routine_confirmation","message":"Sí, aplica esa rutina","expected_intent":"create_routine","allowed_tools":["activate_routine_draft"]}
```

No incluir datos personales reales.

## Métricas de calidad

- Exactitud de intención.
- Porcentaje de tool calls permitidos.
- Escrituras incorrectas.
- Respuestas estructuradas válidas.
- Latencia p50/p95.
- Costo promedio por conversación.
- Porcentaje de fallback.

## Criterio de aceptación

Una modificación de prompt no se integra si empeora casos críticos o habilita herramientas no permitidas.

---

# 9. Seguridad de comportamiento

Heracles debe limitarse a orientación general de entrenamiento y no presentarse como diagnóstico profesional.

Reglas que deben implementarse como políticas del backend, no solo como prompt:

- Si se reporta una molestia, evitar progresión automática del movimiento afectado.
- No incentivar continuar un ejercicio que produce dolor.
- Una limitación puntual crea un borrador temporal, no altera inmediatamente la rutina permanente.
- Las respuestas deben indicar límites cuando falta información relevante.
- Cambios permanentes requieren confirmación.
- Toda herramienta tiene un esquema de permisos por intención.

Tabla inicial:

| Intención | Herramientas permitidas |
|---|---|
| `today_plan` | Ninguna |
| `history` | Ninguna |
| `log_workout` | `save_workout` |
| `modify_session` | `create_session_override_draft` |
| `create_routine` | `create_routine_draft` |
| `evaluate_session` | Ninguna escritura LLM; usa motor determinista |
| `update_profile` | `create_profile_change_draft` |
| `limitation` | `create_session_override_draft` |
| `out_of_scope` | Ninguna |

# 10. MCP: decisión documentada

No implementar MCP en estos hitos.

Justificación:

- Las herramientas viven en el mismo proceso y acceden a la misma base de datos.
- MCP no corrige prompts, memoria, progresión ni validación.
- Añadiría autenticación, latencia y superficie de error.

Reevaluar MCP cuando exista al menos uno de estos casos:

- Otros agentes necesitan consumir las capacidades de Heracles.
- Integración modular con calendarios o dispositivos autorizados.
- Catálogo de ejercicios operado como servicio separado.
- Herramientas compartidas entre varias aplicaciones.

Antes de exponer escrituras mediante MCP deben existir permisos, identidad, auditoría, idempotencia y aislamiento por usuario.

# 11. Checklist antes de comenzar la app móvil

- [ ] Herramientas sin `user_id` controlado por el modelo.
- [ ] Pruebas automatizadas estables.
- [ ] Progresión determinista.
- [ ] Rutinas estructuradas.
- [ ] Confirmación y reversión de cambios.
- [ ] Sesiones con ID y estados.
- [ ] Finalización idempotente.
- [ ] Respuestas Pydantic.
- [ ] Prompt independiente de Telegram.
- [ ] Servicio de agente reutilizable por API.
- [ ] UUID interno independiente del proveedor de acceso.
- [ ] PostgreSQL y migraciones.
- [ ] Checkpointer persistente.
- [ ] Logs, métricas y evaluaciones.

# 12. Orden de ejecución recomendado

No comenzar varios hitos simultáneamente.

```text
Semana/bloque 1: Hito 0 + Hito 1
Semana/bloque 2: Hito 2 + Hito 3
Semana/bloque 3: Hito 4 + Hito 5
Semana/bloque 4: Hito 6
Semana/bloque 5: Hito 7
Semana/bloque 6: Hito 8 y estabilización
Después: API móvil y proyecto Expo
```

La duración real depende del tiempo disponible; los criterios de aceptación, y no el calendario, determinan cuándo avanzar.

# 13. Comandos de verificación por commit

```bash
ruff check bot tests
ruff format --check bot tests
mypy bot
pytest -q
```

Durante la transición, `mypy` puede comenzar limitado a los módulos nuevos si el código existente genera demasiadas advertencias:

```bash
mypy bot/domain bot/agent/contracts.py
```

# 14. Plantilla de tarea para trabajar con un asistente en VS Code

Usar una tarea por conversación o sesión de trabajo:

```text
Implementa únicamente el Hito N de HERACLES_PLAN_ACTUALIZACION_VSCODE.md.

Condiciones:
- Antes de editar, inspecciona los archivos involucrados y los cambios locales.
- No implementes hitos posteriores.
- Conserva compatibilidad con el comportamiento actual salvo lo que el hito cambia explícitamente.
- Agrega o actualiza pruebas.
- No modifiques .env ni expongas secretos.
- Ejecuta las verificaciones indicadas.
- Al terminar, informa archivos modificados, decisiones tomadas, tests ejecutados y riesgos pendientes.
```

## Primera tarea sugerida

```text
Implementa únicamente el Hito 0 de HERACLES_PLAN_ACTUALIZACION_VSCODE.md.
Primero crea pruebas de caracterización para el parser de rutinas, la actualización
textual de progresión, UserStore y los endpoints web que no llaman al LLM.
No refactorices todavía el código productivo salvo pequeños cambios imprescindibles
para permitir inyección de dependencias en tests.
```

# 15. Definición de terminado para cada hito

Un hito está terminado solamente cuando:

- El código cumple su criterio de aceptación.
- Existen pruebas para caminos correctos y errores relevantes.
- No se añadieron secretos ni datos personales al repositorio.
- El README o este documento refleja cualquier desviación de diseño.
- Los cambios pueden explicarse en un commit independiente.
- El sistema anterior sigue funcionando o existe una migración explícita.

# 16. Decisiones que no debe tomar automáticamente un asistente de código

Detener la implementación y pedir decisión si aparece alguno de estos casos:

- Es necesario borrar o transformar datos existentes de forma irreversible.
- La versión instalada de LangGraph no soporta el mecanismo de contexto elegido.
- Se requiere seleccionar proveedor de autenticación.
- La migración a PostgreSQL necesita infraestructura o credenciales reales.
- Una regla de progresión no está definida y puede cambiar el comportamiento del producto.
- Hay cambios locales del usuario que entran en conflicto con el hito.

---

## Resultado final esperado

Al completar esta guía, Heracles será un backend de entrenamiento asistido con un agente acotado: el sistema mantendrá identidad, reglas, cálculos y persistencia bajo control del código; el LLM se concentrará en comprender mensajes, resolver ambigüedades y explicar decisiones. Esa base podrá exponerse mediante FastAPI tanto a Telegram como a una aplicación React Native sin duplicar lógica.
