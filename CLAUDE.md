# botHeracles — Contexto del proyecto

## Qué es
Bot de Telegram para acompañamiento en entrenamiento de fuerza (gym).
Proyecto de aprendizaje orientado a conseguir empleo en AI/backend engineering.

## Stack
| Capa | Tecnología | Por qué |
|---|---|---|
| Bot | python-telegram-bot v21+ | Librería oficial, async nativa |
| LLM | DeepSeek API (deepseek-chat) | ~10x más barato que GPT-4, API compatible con OpenAI |
| Agente | LangGraph StateGraph | Skill más demandado en AI engineering 2024-2025 |
| Memoria | MemorySaver (dev) / SqliteSaver (prod) | Historial de conversación por usuario |
| Web | FastAPI + Uvicorn | Recibe webhooks de n8n |
| DB | SQLite (sqlite3 built-in) | Simple, sin dependencias extra |
| Automatización | n8n (Docker) | Recordatorios programados via webhook |
| Deploy | Docker Compose | Levanta bot + n8n con un comando |

## Arquitectura del agente (LangGraph)
```
START → [agent_node] → (tool_calls?) → [tools_node] → [agent_node]
                     → (sin tools)   → END
```
Patrón ReAct: el LLM razona y actúa en ciclo hasta tener respuesta final.

## Estructura de archivos
```
bot/
├── config.py               # Variables de entorno
├── main.py                 # Entry point — asyncio.gather(bot + servidor)
├── agent/
│   ├── state.py            # AgentState TypedDict (messages + user_id)
│   ├── tools.py            # save_workout, get_recent_workouts, get_user_profile, update_goal
│   ├── nodes.py            # agent_node, tools_node, should_continue
│   └── graph.py            # StateGraph compilado con MemorySaver
├── handlers/
│   ├── telegram.py         # /start, /ayuda, handle_message
│   └── n8n_webhook.py      # POST /webhook/n8n/reminder
└── storage/
    └── user_store.py       # SQLite: tablas users + workouts
```

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

## Convenciones del proyecto
- Comentarios educativos en **español** con etiqueta `[CONCEPTO: ...]`
- Cada concepto incluye referencia a dónde aprender más
- Type hints en todas las funciones
- No hay tests aún — agregar con pytest cuando el usuario lo pida

## Estado actual
- [x] Estructura base del proyecto
- [x] Agente LangGraph con 4 tools (workout CRUD)
- [x] Bot Telegram (polling, comandos /start /ayuda)
- [x] FastAPI + webhook para n8n
- [x] SQLite persistencia
- [x] Docker Compose con n8n
- [ ] Tests unitarios
- [ ] Webhook mode para producción
- [ ] SqliteSaver para persistencia de conversaciones
- [ ] Comando /historial (mostrar últimos N entrenamientos)
- [ ] Sugerencias de progresión automáticas

## n8n
- UI en http://localhost:5678 (con Docker)
- Ver instrucciones de configuración en `n8n/README.md`
- Endpoint que escucha: `POST /webhook/n8n/reminder`
- Header requerido: `X-Webhook-Secret`

## Perfil del desarrollador
- Nivel Python: básico
- Objetivo: aprender construyendo, posicionarse en AI/backend
- Los comentarios `[CONCEPTO]` son parte intencional del proyecto para aprendizaje
