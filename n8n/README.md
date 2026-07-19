# Configuración de n8n para recordatorios

n8n es una plataforma de automatización visual (como Zapier pero self-hosted).
La usamos para enviar recordatorios programados al bot.

## Acceder a n8n

Con Docker Compose corriendo:
- URL local en servidor: http://127.0.0.1:5679
- Usuario: valor de `N8N_BASIC_AUTH_USER` o `admin`
- Contraseña: valor de `N8N_BASIC_AUTH_PASSWORD`

En producción no expongas n8n directamente a internet. Accede mediante túnel SSH:

```bash
ssh -L 5679:127.0.0.1:5679 heraclesapi
```

## Crear el workflow de recordatorio diario

### Paso 1 — Trigger: Schedule
1. Haz clic en **"+ Add first step"**
2. Busca **"Schedule Trigger"**
3. Configura: cada día a las 07:00 (o el horario que prefieras)

### Paso 2 — Acción: HTTP Request
1. Haz clic en **"+"** para agregar un nodo
2. Busca **"HTTP Request"**
3. Configura:
   - **Method**: POST
   - **URL**: `http://bot:8000/webhook/n8n/reminder`
     - En Docker Compose, `bot` es el nombre del servicio (no localhost)
     - Desde fuera de Docker: `http://localhost:8000/webhook/n8n/reminder`
   - **Headers**:
     - `X-Webhook-Secret`: el valor de `WEBHOOK_SECRET` en tu `.env`
     - `Content-Type`: `application/json`
   - **Body** (JSON):
     ```json
     {
       "message": "💪 ¡Buenos días! ¿Tienes entrenamiento hoy? Recuerda registrar tu sesión con Heracles.",
       "user_ids": null
     }
     ```
     - `user_ids: null` envía a todos los usuarios registrados
     - Para un usuario específico: `"user_ids": ["123456789"]`

### Paso 3 — Activar el workflow
1. Haz clic en el toggle **"Active"** arriba a la derecha
2. El workflow correrá automáticamente según el schedule

## Ideas de recordatorios adicionales

- **Recordatorio de descanso**: si un usuario entrenó ayer, recordarle descansar
- **Motivación de fin de semana**: "¡Es sábado! ¿Sesión de fuerza?"
- **Resumen semanal**: cada domingo resumir los entrenamientos de la semana

## Exportar/importar workflows

Puedes exportar tus workflows como JSON desde el menú de n8n y versionarlos en git.
Guarda los exports en esta carpeta `n8n/`.

## Concepto clave: Webhooks

Un webhook es una URL que tu servidor expone para que OTROS servicios te llamen.
En lugar de que TÚ preguntes "¿hay novedades?" (polling), el otro servicio
te avisa cuando algo ocurre (push).

n8n actúa como un cron job visual que hace POST a tu webhook en el horario configurado.
