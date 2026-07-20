# botHeracles — Contexto del proyecto

## Qué es
Bot de Telegram para acompañamiento en entrenamiento de fuerza (gym).
Proyecto de aprendizaje orientado a conseguir empleo en AI/backend engineering.
Diseñado con mentalidad SaaS desde el inicio: costos mínimos de LLM, arquitectura en capas.

## Stack
| Capa | Tecnología | Por qué |
|---|---|---|
| Bot | python-telegram-bot v21+ | Librería oficial, async nativa |
| LLM | DeepSeek API (deepseek-chat) | ~10x más barato que GPT-4, API compatible con OpenAI |
| Agente | LangGraph StateGraph | Skill más demandado en AI engineering 2024-2025 |
| Memoria | MemorySaver (dev) / SqliteSaver (prod) | Historial de conversación por usuario |
| Web API | FastAPI + Uvicorn | Webhooks de n8n + API para app web |
| Frontend | Alpine.js + Tailwind CSS (CDN) | SPA sin build step, dark mode, mobile-first |
| DB | SQLite (sqlite3 built-in) | Simple, sin dependencias extra |
| Automatización | n8n (Docker) | Recordatorios programados via webhook |
| Túnel | Cloudflare Tunnel | Expone el servidor local con HTTPS vía dominio propio |
| Deploy | Docker Compose + Oracle Cloud Free Tier | VM siempre activa, SQLite persistente |

## Arquitectura en capas (mentalidad SaaS)

```
Canal Telegram
        │
        ├── /rutina ──────────────────► SQLite → respuesta       (0 LLM calls)
        ├── /historial ───────────────► SQLite → respuesta       (0 LLM calls)
        ├── /webapp ──────────────────► genera web_token → URL   (0 LLM calls)
        ├── /start ───────────────────► onboarding FSM           (0 LLM calls)
        │                               (bloquea agente hasta completar)
        └── texto libre
                │
                ▼
        _NeedsOnboardingFilter → si onboarding incompleto → redirige a /start
                │
                ▼
        Preparar contexto (Python, 0 costo)
          perfil + rutina activa + últimos entrenamientos + overrides
                │
                ▼
        Agente LangGraph — system prompt con contexto inyectado
          tools disponibles (solo escritura):
            • save_workout        → usuario reportó un ejercicio
            • update_goal         → usuario cambió su objetivo
            • update_equipment    → usuario actualizó su equipamiento
            • log_session_override → modificación temporal de sesión
            • save_routine        → usuario aprueba/confirma una rutina propuesta
            • save_progression_target → al evaluar una sesión, el agente dicta y
                                    persiste nuevos objetivos (peso/reps/series/
                                    tiempo) por ejercicio, sin pedir confirmación
                │
                ├── sin tool calls → END              (1 LLM call)
                └── con tool calls → tools → agent   (2 LLM calls)

Canal Web (https://gym.perritoemo.online/app?token=xxx)
        │
        ├── GET  /api/session/plan    → plan del día; si hay override con ejercicios
        │                               estructurados, los aplica sobre la rutina base
        ├── GET  /api/session/me      → perfil del usuario               (0 LLM calls)
        ├── POST /api/session/set     → guardar serie (peso/reps/RPE)   (0 LLM calls)
        ├── GET  /api/session/today   → log de la sesión actual         (0 LLM calls)
        └── POST /api/session/finish  → agente calcula progresión de carga,
                                        la persiste en progression_targets y envía
                                        la evaluación al chat de Telegram (1 LLM call)

Canal n8n (webhook automation)
        │
        └── POST /webhook/n8n/reminder → recibe mensaje + user_ids y envía
                                          notificaciones Telegram
```

### Principios de costo
- **Lecturas van en el system prompt**, no en tools. El LLM ya tiene perfil,
  rutina e historial desde el primer token — sin loops de "descubrimiento".
- **Rutinas se persisten con marker pattern**: el LLM envuelve la rutina en
  `<<<RUTINA>>>...<<<FIN_RUTINA>>>`, el código Python extrae y guarda en SQLite.
  Costo extra: 0 llamadas al LLM.
- **Comandos directos a DB**: `/rutina` e `/historial` nunca pasan por el agente.
- **App web = 0 LLM calls**: el registro de sesiones es 100% código Python + SQLite.
- **Progresión post-sesión = 1 LLM call directo**: sin LangGraph ni tool calls,
  solo análisis con historial por ejercicio.

### Flujo del agente LangGraph
```
START → [agent_node] → (tool_calls?) → [tools_node] → [agent_node]
                     → (sin tools)   → END
```

## Estructura de archivos
```
bot/
├── config.py               # Variables de entorno (dataclass + validación)
│                           # Incluye WEB_URL para Cloudflare Tunnel / deploy
├── main.py                 # Entry point — asyncio.gather(bot + servidor)
├── agent/
│   ├── state.py            # AgentState TypedDict (messages + user_id)
│   ├── tools.py            # save_workout, update_goal, update_equipment,
│   │                       # log_session_override, save_routine,
│   │                       # save_progression_target (persiste progresión desde
│   │                       # el chat y actualiza la rutina general)
│   ├── nodes.py            # agent_node — contexto completo inyectado:
│   │                       #   fecha actual (REFERENCIA ABSOLUTA), sesión del día,
│   │                       #   overrides activos, perfil, rutina, historial
│   │                       # Guardrails: formato (sin tablas/headers), alcance
│   │                       # (solo entrenamiento), validación de equipamiento,
│   │                       # español neutro (sin modismos regionales)
│   └── graph.py            # StateGraph compilado con MemorySaver
├── handlers/
│   ├── telegram.py         # /start, /rutina, /historial, /webapp, /ayuda
│   │                       # handle_message (con guardia de onboarding)
│   │                       # + _extract_and_save_routine()
│   ├── onboarding.py       # ConversationHandler FSM — 9 pasos
│   │                       # _NeedsOnboardingFilter: intercepta mensajes de usuarios
│   │                       # con onboarding incompleto antes de llegar al agente
│   ├── n8n_webhook.py      # POST /webhook/n8n/reminder
│   └── web_api.py          # Endpoints web:
│                           #   GET  /app                  → sirve workout.html
│                           #   GET  /api/session/plan     → plan del día
│                           #                               (aplica override si tiene
│                           #                                ejercicios estructurados)
│                           #   GET  /api/session/me       → perfil del usuario
│                           #   POST /api/session/set      → guardar una serie
│                           #   GET  /api/session/today    → log de la sesión actual
│                           #   POST /api/session/finish   → progresión post-sesión
├── templates/
│   └── workout.html        # SPA Alpine.js + Tailwind — flujo guiado:
│                           #   • Soporte de formatos mixtos (ejercicios normales
│                           #     + bloques de circuito con rondas)
│                           #   • Ejercicio a ejercicio en el orden de la rutina
│                           #   • Peso pre-cargado desde progression_targets
│                           #     (o último registro si no hay target)
│                           #   • Timer pre-configurado por rango de reps
│                           #   • Progreso visual (barra segmentada, circuito en ámbar)
│                           #   • Pantalla de descanso en días sin entrenamiento
│                           #   • Resumen de sesión + sugerencias de progresión
│                           #     calculadas por el agente al finalizar
└── storage/
    └── user_store.py       # SQLite: users + workouts + routines +
                            # session_overrides + progression_targets
```

## Tablas SQLite
| Tabla | Propósito |
|---|---|
| `users` | Perfil completo del usuario (onboarding + objetivo + `web_token`) |
| `workouts` | Historial de ejercicios (`sets`, `reps`, `weight_kg`, `rpe`, `notes`) |
| `routines` | Rutina activa por usuario (soft replace — guarda historial) |
| `session_overrides` | Modificaciones temporales a la rutina base |
| `progression_targets` | Peso sugerido por el agente para la próxima sesión por ejercicio |

### Columnas clave en `workouts`
| Columna | Tipo | Descripción |
|---|---|---|
| `sets` | INTEGER | Desde Telegram: series totales (ej. 4). Desde web: siempre 1 |
| `reps` | INTEGER | Repeticiones por serie |
| `weight_kg` | REAL | Peso en kg. 0 = peso corporal |
| `rpe` | INTEGER | Esfuerzo Percibido (6=liviano, 10=fallo). Null si viene de Telegram |
| `notes` | TEXT | Sensaciones de la serie. Null si viene de Telegram |

### Columnas clave en `users`
| Columna | Tipo | Descripción |
|---|---|---|
| `training_days` | TEXT | Días específicos: `"lunes,martes,jueves,viernes"` (reemplaza `days_per_week`) |
| `web_token` | TEXT | Token único para autenticar la app web (generado con `secrets.token_urlsafe(24)`) |
| `onboarding_done` | INTEGER | 1 si completó el onboarding inicial |

### Tabla `session_overrides`
Modificaciones temporales a la rutina. No tocan la rutina base.
| Columna | Tipo | Descripción |
|---|---|---|
| `target_date` | TEXT | `YYYY-MM-DD` del día afectado |
| `scope` | TEXT | `'day'` = solo ese día, `'week'` = toda esa semana |
| `modification` | TEXT | Descripción del ajuste. Si tiene bullets `• Nombre: SxR`, la web app los parsea y los usa como plan del día en lugar de la rutina base |
| `reason` | TEXT | Motivo (fútbol, dolor rodilla, etc.) |

### Tabla `progression_targets`
Peso calculado por el agente al finalizar cada sesión. PRIMARY KEY (user_id, exercise).
| Columna | Tipo | Descripción |
|---|---|---|
| `exercise` | TEXT | Nombre exacto del ejercicio |
| `next_weight` | REAL | Peso sugerido para la próxima sesión (kg) |
| `next_reps` | TEXT | Rango de reps sugerido (ej: "8-10") |
| `next_sets` | INTEGER | Series sugeridas (doble progresión: reps/series antes que peso) |
| `basis` | TEXT | Justificación breve del agente (ej: "RPE 8 estable → +2.5 kg") |
| `session_date` | TEXT | Fecha de la sesión que generó el cálculo |

`get_last_weight_for_exercise` consulta esta tabla primero; si hay un target, lo usa como `suggested_weight`. Si no, cae al último registro en `workouts`.

### Identidad de ejercicios
`exercise` funciona hoy como clave lógica en `workouts` y `progression_targets`.
El agente y cualquier código de backend deben reutilizar el nombre canónico ya
conocido cuando se refieran al mismo movimiento. Cambios menores de texto crean
otra clave y separan historial/progresión.

Orden de fuente canónica:
1. `routines.routine_json` si existe.
2. Bullets de `routines.routine_text`.
3. Bullets activos en `session_overrides.modification` para sustituciones temporales.
4. `progression_targets.exercise`.
5. `workouts.exercise` como fallback legacy.

Documento de desarrollo: `docs/EXERCISE_IDENTITY.md`.

### Estrategia de progresión (doble progresión)
Al finalizar la sesión, el agente NO sube peso como primera palanca. Orden estricto:
1. Reps dentro del rango objetivo (si no tocó el techo con RPE 6-8).
2. Series +1 (si ya tocó el techo de reps con margen, antes de subir peso).
3. Peso (solo cuando reps y series ya están al tope) — vuelve next_reps al piso del rango.
Si el RPE fue alto (9-10) sin completar el rango, se mantiene todo igual (consolidar antes de progresar).
Ver `_build_progression_prompt` en `bot/handlers/web_api.py` y `apply_progression_to_routine_text` en `bot/agent/nodes.py` (reescribe series/reps/peso en la rutina general persistida).

La misma estrategia aplica en el chat: cuando el usuario pide evaluar una sesión,
el agente dicta los nuevos objetivos y los persiste con el tool
`save_progression_target` (una llamada por ejercicio) — no pregunta si registrar.
El tool guarda en `progression_targets` y reescribe la rutina general, igual que
`POST /api/session/finish`.

### Lógica de descanso sugerido en la app web
El timer se pre-configura según el rango de reps del ejercicio:
| Rango | Tiempo | Sistema energético |
|---|---|---|
| 1-5 reps | 3 min | Fuerza máxima (fosfágeno) |
| 6-8 reps | 2.5 min | Fuerza/hipertrofia |
| 8-12 reps | 2 min | Hipertrofia (glucolítico) |
| 12-20 reps | 90 seg | Resistencia muscular |
| 20+ reps | 60 seg | Circuito / core |

Para ejercicios de circuito: sin timer entre ejercicios del mismo round; timer de `circuit_rest` solo al final de cada ronda.

## Cómo correr
```bash
# Desarrollo (sin Docker)
cp .env.example .env        # rellenar TELEGRAM_BOT_TOKEN y DEEPSEEK_API_KEY
pip install -r requirements.txt
python -m bot.main

# Con Docker (incluye n8n)
docker compose up --build
```

## Variables de entorno requeridas
- `TELEGRAM_BOT_TOKEN` — desde @BotFather en Telegram
- `DEEPSEEK_API_KEY` — desde platform.deepseek.com
- `WEBHOOK_SECRET` — string secreto compartido con n8n
- `PORT` — default 8001 en producción
- `DATABASE_PATH` — default data/heracles.db
- `WEB_URL` — URL pública del servidor (ej. `https://gym.perritoemo.online`)
- `TIMEZONE` — zona horaria del servidor (ej. `America/Santiago`)

## Convenciones del proyecto
- Comentarios educativos en **español** con etiqueta `[CONCEPTO: ...]`
- Cada concepto incluye referencia a dónde aprender más
- Type hints en todas las funciones
- No hay tests aún — agregar con pytest cuando el usuario lo pida
- Formato de rutinas para Telegram: bullet points `•` + separadores `───`, sin tablas markdown

## Estado actual

### Completado
- [x] Estructura base del proyecto
- [x] Agente LangGraph con tools (save_workout, update_goal, update_equipment, log_session_override)
- [x] Contexto inyectado en system prompt (perfil + rutina + historial + overrides + fecha)
- [x] Bot Telegram (polling, comandos /start /rutina /historial /webapp /ayuda)
- [x] FastAPI + webhook para n8n
- [x] SQLite persistencia (users + workouts + routines + session_overrides + progression_targets)
- [x] Docker Compose con n8n
- [x] **Deploy en producción** — Oracle Cloud Free Tier + Cloudflare Tunnel
  - VM ARM, dominio propio, HTTPS automático
  - Puerto 8001, túnel en `gym.perritoemo.online`
- [x] Onboarding completo (ConversationHandler FSM, 9 pasos)
  - `_NeedsOnboardingFilter`: bloquea el agente hasta que el usuario complete su perfil
  - Mensaje diferente para usuarios nuevos vs usuarios que abandonaron el flujo
- [x] Rutinas persistidas via marker pattern (0 LLM calls extra)
- [x] App web de registro (Alpine.js + Tailwind, dark mode, mobile-first)
  - **Modo circuito real**: detecta bloques `• Circuito (N rondas, descanso Xs):`
    con sub-ítems indentados; navega ejercicio a ejercicio sin timer entre ellos,
    timer de descanso solo al final de cada ronda, badge ámbar "Ronda X/N"
  - Flujo guiado: ejercicio a ejercicio en el orden de la rutina del día
  - Peso pre-cargado desde `progression_targets` (o último registro histórico)
  - Timer pre-configurado según rango de reps (fisiología del descanso)
  - Progreso visual (barra segmentada; circuito en ámbar, normal en índigo)
  - Pantalla de descanso en días sin entrenamiento
  - Resumen de sesión con sugerencias de progresión del agente
  - Autenticación por web_token (no expone Telegram ID en URL)
- [x] Reglas de negocio de sesión
  - Días de entrenamiento específicos (Lun/Mar/Jue/Vie) en lugar de cantidad
  - Rutina general inmutable + sistema de overrides temporales
  - Override con ejercicios estructurados reemplaza el plan de la app web
  - Agente detecta alcance del cambio (día / semana / permanente)
  - Tool `log_session_override` para modificaciones sin tocar la rutina base
  - `get_active_overrides` usa TIMEZONE del servidor (no UTC de SQLite)
- [x] Guardrails del agente
  - Validación de equipamiento: rechaza ítems inválidos (animales, muebles, etc.)
  - Alcance restringido: solo responde preguntas de entrenamiento
  - Español neutro: sin modismos argentinos ni regionales
  - Formato forzado: sin tablas markdown ni headers (Telegram no los renderiza)
  - Fecha como referencia absoluta: ignora fechas del historial de conversación
- [x] **Progresión de carga post-sesión** (1 LLM call directo, sin LangGraph)
  - Al finalizar la sesión web, `POST /api/session/finish` construye prompt con
    series de hoy + últimas 5 sesiones por ejercicio
  - Agente analiza rendimiento (RPE, reps, historial) y devuelve JSON con
    `next_weight` + justificación por ejercicio
  - Se persiste en `progression_targets`; la próxima sesión ya lleva el peso progresado

### Pendiente
- [ ] **API móvil v1**
  - Crear `bot/handlers/mobile_api.py` con `APIRouter(prefix="/api/v1")`
  - Implementar contratos de `docs/MOBILE_API_V1.md`
  - Mantener `/api/session/*` como API web legacy hasta migrar la app actual
  - Tests de auth, plan de sesión, guardado de sets y finish idempotente
- [ ] Recordatorios inteligentes con n8n
  - Endpoint `POST /webhook/n8n/daily-reminder` que filtra usuarios con entrenamiento hoy
  - Mensaje personalizado con bloque de sesión + override si aplica
  - Workflow n8n: Schedule Trigger (8 AM) → HTTP Request al endpoint
- [ ] Tests unitarios (pytest)
- [ ] Webhook mode para Telegram (reemplaza polling en producción)
- [ ] SqliteSaver para persistir conversaciones entre reinicios del contenedor

## Features futuras (roadmap)

### Alta prioridad — retención y valor percibido
- **Reporte semanal automático**: cada lunes el agente genera un resumen
  de la semana anterior (sesiones completadas, progresión de pesos, tendencias).
  Se envía por Telegram. 0 input del usuario. n8n como disparador.
- **Detección de récords personales (PRs)**: al guardar un workout, comparar
  con el histórico del ejercicio. Si es nuevo máximo de peso, reps o volumen
  → el bot lo celebra automáticamente.
- **Racha de adherencia**: contador de semanas consecutivas entrenadas.
  Alerta si el usuario rompe la racha; felicitación al superar hitos (4, 8, 12 semanas).

### Media prioridad — inteligencia de entrenamiento
- **Alerta de estancamiento**: si un ejercicio lleva 3+ sesiones sin progresión
  (mismo peso, mismo RPE) → el agente avisa y sugiere ajuste (variante, técnica, deload).
- **Control de volumen por grupo muscular**: tracking de series semanales por músculo.
  Aviso si hay desequilibrio o sobrecarga.
- **Sugerencia de semana de descarga (deload)**: después de 4-6 semanas de carga
  progresiva, proponer reducción de volumen/intensidad para recuperación.

### Baja prioridad — escalabilidad SaaS
- **Intent router con LCEL**: clasificar mensajes antes del agente para rutear
  directamente a handlers específicos sin pasar por el LLM completo.
- **Panel de administración**: gestión de usuarios, aprobaciones, estadísticas globales.
- **SqliteSaver → PostgreSQL**: para soporte multi-worker y persistencia entre deploys.

## Despliegue actual

**Oracle Cloud Free Tier + Cloudflare Tunnel**

```
Oracle VM ARM (Ubuntu) ──► Docker Compose ──► Cloudflare Tunnel ──► gym.perritoemo.online
                              bot:8001
                              n8n:5678
```

- Bot en `127.0.0.1:8001` (no expuesto directo a internet)
- Cloudflare Tunnel enruta `gym.perritoemo.online → localhost:8001`
- SSH alias: `heraclesapi`
- Deploy: `ssh heraclesapi "cd ~/botHeracles && git pull && docker compose up -d --build bot"`

### Otras opciones documentadas

**Fly.io** (más fácil, requiere tarjeta):
```bash
flyctl launch && flyctl volumes create heracles_data --size 1 && flyctl deploy
```

**Railway** (prototype only — SQLite no persiste en free tier)

### Cambio futuro: webhook mode

En producción conviene reemplazar polling por webhook:
```python
# En main.py → run_telegram_bot():
await telegram_app.updater.start_webhook(
    listen="0.0.0.0",
    port=8443,
    url_path=settings.TELEGRAM_BOT_TOKEN,
    webhook_url=f"{settings.WEB_URL}/{settings.TELEGRAM_BOT_TOKEN}",
)
```

## n8n
- UI en `http://localhost:5679` (con Docker en producción)
- Endpoint actual: `POST /webhook/n8n/reminder` (body: `{message, user_ids}`)
- Header requerido: `X-Webhook-Secret`
- Ver instrucciones en `n8n/README.md`

## Perfil del desarrollador
- Nivel Python: básico
- Objetivo: aprender construyendo, posicionarse en AI/backend
- Los comentarios `[CONCEPTO]` son parte intencional del proyecto para aprendizaje
