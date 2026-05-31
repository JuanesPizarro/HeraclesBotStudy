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
| Deploy | Docker Compose | Levanta bot + n8n con un comando |

## Arquitectura en capas (mentalidad SaaS)

```
Canal Telegram
        │
        ├── /rutina ──────────────────► SQLite → respuesta       (0 LLM calls)
        ├── /historial ───────────────► SQLite → respuesta       (0 LLM calls)
        ├── /webapp ──────────────────► genera web_token → URL   (0 LLM calls)
        ├── /start ───────────────────► onboarding FSM           (0 LLM calls)
        │
        └── texto libre
                │
                ▼
        Preparar contexto (Python, 0 costo)
          perfil + rutina activa + últimos entrenamientos
                │
                ▼
        Agente LangGraph — system prompt con contexto inyectado
          tools disponibles (solo escritura):
            • save_workout   → usuario reportó un ejercicio
            • update_goal    → usuario cambió su objetivo
                │
                ├── sin tool calls → END              (1 LLM call)
                └── con tool calls → tools → agent   (2 LLM calls)

Canal Web (https://dominio.com/app?token=xxx)
        │
        ├── GET /api/session/plan   → plan guiado del día (ejercicios ordenados,
        │                             peso sugerido del historial, descanso por rango de reps)
        ├── GET /api/session/me     → perfil del usuario               (0 LLM calls)
        ├── POST /api/session/set   → guardar serie (peso/reps/RIR)   (0 LLM calls)
        └── GET /api/session/today  → log de la sesión actual         (0 LLM calls)
```

### Principios de costo
- **Lecturas van en el system prompt**, no en tools. El LLM ya tiene perfil,
  rutina e historial desde el primer token — sin loops de "descubrimiento".
- **Rutinas se persisten con marker pattern**: el LLM envuelve la rutina en
  `<<<RUTINA>>>...<<<FIN_RUTINA>>>`, el código Python extrae y guarda en SQLite.
  Costo extra: 0 llamadas al LLM.
- **Comandos directos a DB**: `/rutina` e `/historial` nunca pasan por el agente.
- **App web = 0 LLM calls**: el registro de sesiones es 100% código Python + SQLite.

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
│   ├── tools.py            # save_workout, update_goal, log_session_override
│   ├── nodes.py            # agent_node con contexto: fecha de hoy, sesión del día,
│   │                       # overrides activos, sección de rutina correspondiente
│   └── graph.py            # StateGraph compilado con MemorySaver
├── handlers/
│   ├── telegram.py         # /start, /rutina, /historial, /webapp, /ayuda
│   │                       # handle_message + _extract_and_save_routine()
│   ├── onboarding.py       # ConversationHandler FSM — paso 1 usa multi-select
│   │                       # de días específicos (Lun/Mar/..) en lugar de cantidad
│   ├── n8n_webhook.py      # POST /webhook/n8n/reminder
│   └── web_api.py          # Endpoints web:
│                           #   GET  /app                  → sirve workout.html
│                           #   GET  /api/session/plan     → plan guiado del día
│                           #   GET  /api/session/me       → perfil del usuario
│                           #   POST /api/session/set      → guardar una serie
│                           #   GET  /api/session/today    → log de la sesión actual
├── templates/
│   └── workout.html        # SPA Alpine.js + Tailwind — flujo guiado:
│                           #   • Ejercicio a ejercicio en el orden de la rutina
│                           #   • Peso pre-cargado del historial
│                           #   • Timer pre-configurado por rango de reps
│                           #   • Progreso visual (barra por ejercicio)
│                           #   • Pantalla de descanso y resumen final
└── storage/
    └── user_store.py       # SQLite: users + workouts + routines + session_overrides
```

## Tablas SQLite
| Tabla | Propósito |
|---|---|
| `users` | Perfil completo del usuario (onboarding + objetivo + `web_token`) |
| `workouts` | Historial de ejercicios (`sets`, `reps`, `weight_kg`, `rir`, `notes`) |
| `routines` | Rutina activa por usuario (soft replace — guarda historial) |

### Columnas clave en `workouts`
| Columna | Tipo | Descripción |
|---|---|---|
| `sets` | INTEGER | Desde Telegram: series totales (ej. 4). Desde web: siempre 1 |
| `reps` | INTEGER | Repeticiones por serie |
| `weight_kg` | REAL | Peso en kg. 0 = peso corporal |
| `rir` | INTEGER | Repeticiones en Recámara (0=fallo, 5=muy cómodo). Null si viene de Telegram |
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
| `modification` | TEXT | Descripción concreta del ajuste |
| `reason` | TEXT | Motivo (fútbol, dolor rodilla, etc.) |

### Lógica de descanso sugerido en la app web
El timer se pre-configura según el rango de reps del ejercicio:
| Rango | Tiempo | Sistema energético |
|---|---|---|
| 1-5 reps | 3 min | Fuerza máxima (fosfágeno) |
| 6-8 reps | 2.5 min | Fuerza/hipertrofia |
| 8-12 reps | 2 min | Hipertrofia (glucolítico) |
| 12-20 reps | 90 seg | Resistencia muscular |
| 20+ reps | 60 seg | Circuito / core |

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
- `PORT` — default 8000
- `DATABASE_PATH` — default data/heracles.db
- `WEB_URL` — URL pública del servidor (ej. `https://tu-dominio.com` con Cloudflare Tunnel)

## Convenciones del proyecto
- Comentarios educativos en **español** con etiqueta `[CONCEPTO: ...]`
- Cada concepto incluye referencia a dónde aprender más
- Type hints en todas las funciones
- No hay tests aún — agregar con pytest cuando el usuario lo pida
- Formato de rutinas para Telegram: bullet points `•` + separadores `───`, sin tablas markdown

## Estado actual
- [x] Estructura base del proyecto
- [x] Agente LangGraph con tools mínimos (solo escritura)
- [x] Contexto inyectado en system prompt (perfil + rutina + historial)
- [x] Bot Telegram (polling, comandos /start /rutina /historial /webapp /ayuda)
- [x] FastAPI + webhook para n8n
- [x] SQLite persistencia (users + workouts + routines)
- [x] Docker Compose con n8n
- [x] Onboarding completo (ConversationHandler FSM, 9 pasos)
- [x] Rutinas persistidas via marker pattern (0 LLM calls extra)
- [x] App web de registro (Alpine.js + Tailwind, dark mode, mobile-first)
  - Flujo guiado: ejercicio a ejercicio en el orden de la rutina del día
  - Peso pre-cargado desde el último registro histórico por ejercicio
  - Timer pre-configurado según rango de reps (fisiología del descanso)
  - Progreso visual (barra segmentada por ejercicio)
  - Pantalla de descanso en días sin entrenamiento
  - Resumen de sesión al finalizar
  - Autenticación por web_token (no expone Telegram ID en URL)
  - Compatible con Cloudflare Tunnel (HTTPS, acceso desde el gym)
- [x] Reglas de negocio de sesión
  - Días de entrenamiento específicos (Lun/Mar/Jue/Vie) en lugar de cantidad
  - Rutina general inmutable + sistema de overrides temporales
  - Agente detecta alcance del cambio (día / semana / permanente)
  - Tool `log_session_override` para modificaciones sin tocar la rutina base
  - Agente conoce la fecha de hoy y la sección de rutina que corresponde
- [ ] Deploy en producción (ver sección Despliegue)
- [ ] Tests unitarios
- [ ] Webhook mode (recomendado en producción — reemplaza polling)
- [ ] SqliteSaver para persistencia de conversaciones entre reinicios
- [ ] Sugerencias de progresión automáticas
- [ ] Intent router con LCEL (optimización SaaS futura)

## Despliegue (opciones gratuitas)

El bot necesita: proceso siempre activo + SQLite persistente + Python 3.11+.
Eso descarta plataformas serverless (Cloudflare Workers, AWS Lambda) y las que
duermen en inactividad (Render free tier).

### Opción recomendada: Oracle Cloud Free Tier + Cloudflare Tunnel

**Por qué es la mejor opción:**
- VM Linux real siempre activa, para siempre, sin tarjeta de crédito con cargo
- SQLite funciona perfectamente (disco persistente)
- Ya tenés Cloudflare Tunnel + dominio → HTTPS gratis sin configurar Nginx

```
Oracle VM (Ubuntu) ──► Python + Docker Compose ──► Cloudflare Tunnel ──► tu dominio
```

**Pasos:**
1. Crear cuenta en cloud.oracle.com → Free Tier → crear VM AMD o ARM
2. `ssh` a la VM, instalar Docker + Docker Compose
3. Clonar el repo, copiar `.env`, correr `docker compose up -d`
4. Instalar `cloudflared` en la VM, conectar el túnel a `localhost:8000`
5. Apuntar el dominio en Cloudflare Dashboard

**Specs gratuitas:** 2 VMs AMD (1 OCPU, 1 GB RAM cada una) o 1 ARM (4 OCPU, 24 GB RAM).
El bot cabe holgado en la VM más pequeña.

---

### Opción más fácil: Fly.io

**Por qué:**
- Deploy en 3 comandos, sin configurar servidores
- Volúmenes persistentes para SQLite (3 GB gratis)
- HTTPS automático con dominio `.fly.dev`

```bash
# Una sola vez
brew install flyctl      # o curl -L https://fly.io/install.sh | sh
flyctl auth login
flyctl launch            # detecta Python, crea fly.toml

# Cada deploy
flyctl deploy
```

**Requiere:** tarjeta de crédito para verificar (no cobra dentro del free tier).
**Límite free:** 3 VMs shared (256 MB RAM), 3 GB almacenamiento.

**Nota importante para SQLite en Fly.io:** crear un volumen persistente:
```bash
flyctl volumes create heracles_data --size 1   # 1 GB
```
Y montar en `fly.toml`:
```toml
[mounts]
  source = "heracles_data"
  destination = "/app/data"
```

---

### Opción más rápida (prototype): Railway

- Deploy desde GitHub en 2 clics, sin CLI
- $5 USD de crédito gratis al mes (~500 horas de uso)
- **Limitación:** SQLite no tiene volumen persistente en el free tier
  → los datos se pierden al hacer deploy (sirve solo para demos)

---

### Cambio necesario para producción: webhook mode

En local usamos **polling** (el bot pregunta a Telegram cada N segundos).
En producción conviene **webhook** (Telegram empuja los mensajes a tu URL):

```python
# En main.py → run_telegram_bot(), reemplazar:
await telegram_app.updater.start_polling()

# Por:
await telegram_app.updater.start_webhook(
    listen="0.0.0.0",
    port=8443,
    url_path=settings.TELEGRAM_BOT_TOKEN,
    webhook_url=f"{settings.WEB_URL}/{settings.TELEGRAM_BOT_TOKEN}",
)
```

Ventajas: más eficiente, tiempo real, no consume CPU en idle.
Con Cloudflare Tunnel ya tenés HTTPS → el webhook funciona sin más configuración.

## n8n
- UI en http://localhost:5678 (con Docker)
- Ver instrucciones de configuración en `n8n/README.md`
- Endpoint que escucha: `POST /webhook/n8n/reminder`
- Header requerido: `X-Webhook-Secret`

## Perfil del desarrollador
- Nivel Python: básico
- Objetivo: aprender construyendo, posicionarse en AI/backend
- Los comentarios `[CONCEPTO]` son parte intencional del proyecto para aprendizaje
