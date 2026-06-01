import sqlite3
from pathlib import Path
from typing import Optional
from bot.config import settings

# =====================================================================
# [CONCEPTO: SQLite con el módulo sqlite3 de Python]
# SQLite guarda toda la base de datos en un archivo .db.
# Ideal para: desarrollo, bots pequeños, apps con <10k usuarios.
# Para escalar: migrar a PostgreSQL (con psycopg2 o asyncpg).
#
# [CONCEPTO: SQL básico que debes conocer]
# - SELECT, INSERT, UPDATE, DELETE — operaciones CRUD
# - WHERE, ORDER BY, LIMIT — filtros y ordenamiento
# - PRIMARY KEY, FOREIGN KEY — integridad referencial
# - CREATE TABLE IF NOT EXISTS — idempotencia en migraciones
#
# Aprende más: https://sqlitebrowser.org/ (GUI para explorar el .db)
# Curso: "SQL for Beginners" en cualquier plataforma
# =====================================================================


class UserStore:
    """Capa de acceso a datos (DAL) para usuarios y entrenamientos."""

    def __init__(self, db_path: str = settings.DATABASE_PATH):
        # Crear el directorio "data/" si no existe
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        # [CONCEPTO: row_factory]
        # sqlite3.Row permite acceder a columnas por nombre (row["name"])
        # en lugar de por índice (row[0]). Mucho más legible.
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Crea las tablas si no existen. Seguro de llamar múltiples veces."""
        # [CONCEPTO: executescript — múltiples statements SQL]
        # Útil para inicialización. En apps grandes, usa herramientas de
        # migración como Alembic (SQLAlchemy) o Flyway (Java).
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id  TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    goal         TEXT DEFAULT 'ganar fuerza y masa muscular',
                    created_at   TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS workouts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL,
                    exercise    TEXT NOT NULL,
                    sets        INTEGER NOT NULL,
                    reps        INTEGER NOT NULL,
                    weight_kg   REAL NOT NULL DEFAULT 0,
                    logged_at   TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
                );

                -- Índice para acelerar consultas de historial por usuario
                -- [CONCEPTO: Índices de base de datos]
                -- Sin índice, SQLite lee TODA la tabla para filtrar por user_id.
                -- Con índice, la búsqueda es O(log n) en vez de O(n).
                CREATE INDEX IF NOT EXISTS idx_workouts_user_id
                    ON workouts(user_id);

                -- =====================================================================
                -- [CONCEPTO: Tabla de rutinas — diseño one-to-one activo]
                --
                -- Cada usuario tiene una sola rutina "activa" en cualquier momento.
                -- Guardamos el texto completo (no la estructura normalizada) porque:
                --   1. El LLM genera la rutina como texto — extraer estructura es frágil
                --   2. El texto completo es lo que se muestra y se comparte
                --   3. Para analítica futura, podemos parsear o añadir columnas
                --
                -- Patrón "soft replace": en lugar de UPDATE directo, insertamos un
                -- registro nuevo con is_active=1 y desactivamos el anterior.
                -- Esto da historial de rutinas antiguas sin coste de complejidad alto.
                -- =====================================================================
                CREATE TABLE IF NOT EXISTS routines (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL,
                    routine_text TEXT NOT NULL,
                    created_at  TEXT DEFAULT (datetime('now')),
                    is_active   INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
                );

                CREATE INDEX IF NOT EXISTS idx_routines_user_id
                    ON routines(user_id);

                -- =====================================================================
                -- [CONCEPTO: Tabla de overrides de sesión]
                --
                -- Un override es una modificación temporal a la rutina general.
                -- No toca la rutina base — solo crea una "excepción" para una fecha.
                -- Ejemplos:
                --   - "Esta semana juego fútbol el martes" → override ese martes
                --   - "Hoy me duele la rodilla" → override el día de hoy
                --
                -- scope: 'day' = solo ese día | 'week' = esa semana completa
                -- =====================================================================
                CREATE TABLE IF NOT EXISTS session_overrides (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT NOT NULL,
                    target_date  TEXT NOT NULL,
                    scope        TEXT NOT NULL DEFAULT 'day',
                    modification TEXT NOT NULL,
                    reason       TEXT,
                    created_at   TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
                );

                CREATE INDEX IF NOT EXISTS idx_overrides_user_date
                    ON session_overrides(user_id, target_date);
            """)
        # [CONCEPTO: Migraciones incrementales]
        # En producción se usa Alembic o herramientas similares para gestionar
        # versiones del schema. Aquí usamos ALTER TABLE manualmente para
        # añadir columnas sin romper datos existentes.
        self._migrate_db()

    def _migrate_db(self) -> None:
        """Agrega columnas nuevas al schema sin borrar datos existentes."""
        # [CONCEPTO: PRAGMA table_info]
        # SQLite expone metadata de las tablas a través de PRAGMAs.
        # PRAGMA table_info(tabla) devuelve una fila por columna con:
        # cid, name, type, notnull, dflt_value, pk
        # Usamos esto para saber qué columnas ya existen antes de añadir.
        new_user_columns = [
            ("experience_level",      "TEXT"),
            ("days_per_week",         "INTEGER"),
            ("session_time_minutes",  "INTEGER"),
            ("equipment",             "TEXT"),
            ("home_equipment_detail", "TEXT"),
            ("daily_activity",        "TEXT"),
            ("limitations",           "TEXT"),
            ("level_test_requested",  "INTEGER DEFAULT 0"),
            ("onboarding_done",       "INTEGER DEFAULT 0"),
            ("web_token",             "TEXT"),
            ("training_days",         "TEXT"),
            # Control de acceso: 'active' | 'pending' | 'blocked'
            # DEFAULT 'active' para que usuarios existentes no pierdan el acceso.
            # Los usuarios nuevos se insertan explícitamente con 'pending'.
            ("status",                "TEXT DEFAULT 'active'"),
        ]
        # Columnas para registro granular desde la app web (serie a serie)
        new_workout_columns = [
            ("rir",   "INTEGER"),   # Repeticiones en Recámara (0 = fallo, 5 = muy cómodo)
            ("notes", "TEXT"),      # Sensaciones / observaciones de la serie
        ]
        with self._get_conn() as conn:
            existing_users = {
                row[1] for row in conn.execute("PRAGMA table_info(users)")
            }
            for col_name, col_type in new_user_columns:
                if col_name not in existing_users:
                    conn.execute(
                        f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
                    )
            existing_workouts = {
                row[1] for row in conn.execute("PRAGMA table_info(workouts)")
            }
            for col_name, col_type in new_workout_columns:
                if col_name not in existing_workouts:
                    conn.execute(
                        f"ALTER TABLE workouts ADD COLUMN {col_name} {col_type}"
                    )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_web_token ON users(web_token)"
                " WHERE web_token IS NOT NULL"
            )
            # ── Migración de training_days para usuarios existentes ──────────────
            # [CONCEPTO: Migración de datos sin pérdida]
            # Usuarios con days_per_week pero sin training_days vinieron del
            # onboarding antiguo. Extraemos los días de su rutina activa
            # leyendo los encabezados de sección (DÍA N — ... (Lunes)).
            # Si no hay rutina activa o no se puede parsear, se deja NULL —
            # el usuario lo completará la próxima vez que haga /start.
            _DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            no_days = conn.execute(
                "SELECT telegram_id FROM users WHERE training_days IS NULL AND onboarding_done = 1"
            ).fetchall()
            for (uid,) in no_days:
                row = conn.execute(
                    "SELECT routine_text FROM routines WHERE user_id = ? AND is_active = 1 LIMIT 1",
                    (uid,),
                ).fetchone()
                if not row:
                    continue
                import re as _re
                found = []
                for line in row[0].split("\n"):
                    for day in _DAYS_ES:
                        if _re.search(rf"\b{_re.escape(day)}\b", line, _re.IGNORECASE) and day not in found:
                            found.append(day)
                if found:
                    found.sort(key=lambda d: _DAYS_ES.index(d))
                    training_days_str = ",".join(found)
                    conn.execute(
                        "UPDATE users SET training_days = ?, days_per_week = ? WHERE telegram_id = ?",
                        (training_days_str, len(found), uid),
                    )

    def upsert_user(self, telegram_id: str, name: str) -> bool:
        """
        Crea el usuario si no existe. Devuelve True si fue creado ahora.

        [CONCEPTO: Detectar si un INSERT creó un registro nuevo]
        INSERT OR IGNORE no nos dice si insertó o ignoró. Usamos SELECT previo
        para detectar usuarios nuevos y asignarles status='pending'.
        Los usuarios existentes conservan su status actual (no se sobreescribe).

        Retorna True → usuario recién creado (pendiente de aprobación)
        Retorna False → usuario ya existía
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT telegram_id FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            if existing:
                return False
            # Nuevo usuario: status='pending' hasta que el admin lo apruebe
            conn.execute(
                "INSERT INTO users (telegram_id, name, status) VALUES (?, ?, 'pending')",
                (telegram_id, name),
            )
            return True

    def get_user_status(self, telegram_id: str) -> str:
        """Devuelve el status de acceso del usuario. 'unknown' si no existe."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT status FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            return row["status"] if row else "unknown"

    def update_user_status(self, telegram_id: str, status: str) -> None:
        """Actualiza el status de acceso: 'active', 'pending' o 'blocked'."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET status = ? WHERE telegram_id = ?",
                (status, telegram_id),
            )

    def get_all_users_with_status(self) -> list[dict]:
        """Devuelve todos los usuarios con su estado, para el panel del admin."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT telegram_id, name, status, onboarding_done, created_at
                   FROM users ORDER BY created_at DESC""",
            ).fetchall()
            return [dict(row) for row in rows]

    def get_user(self, telegram_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_goal(self, telegram_id: str, goal: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET goal = ? WHERE telegram_id = ?",
                (goal, telegram_id),
            )

    def save_workout(
        self,
        user_id: str,
        exercise: str,
        sets: int,
        reps: int,
        weight_kg: float,
        rir: int | None = None,
        notes: str | None = None,
    ) -> int:
        """
        Guarda un registro de entrenamiento y devuelve el ID del registro.

        Cuando se llama desde el agente (Telegram): sets>1, rir/notes=None.
        Cuando se llama desde la app web: sets=1, rir y notes opcionales.
        """
        # [CONCEPTO: Parámetros con ? en SQL]
        # NUNCA concatenes strings en SQL: f"... WHERE id = {user_id}"
        # Eso permite SQL Injection. Usa siempre parámetros con ?.
        # La librería sanitiza los valores automáticamente.
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO workouts (user_id, exercise, sets, reps, weight_kg, rir, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, exercise, sets, reps, weight_kg, rir, notes),
            )
            return cursor.lastrowid

    def get_user_by_token(self, web_token: str) -> Optional[dict]:
        """Busca un usuario por su web_token. Devuelve None si no existe."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE web_token = ?",
                (web_token,),
            ).fetchone()
            return dict(row) if row else None

    def get_or_create_web_token(self, telegram_id: str) -> str:
        """
        Devuelve el web_token del usuario, generando uno nuevo si no tiene.

        [CONCEPTO: secrets.token_urlsafe]
        Genera un token criptográficamente seguro de N bytes aleatorios,
        codificado en base64 URL-safe. 24 bytes → ~32 caracteres.
        Imposible de adivinar por fuerza bruta.
        """
        import secrets
        user = self.get_user(telegram_id)
        if user and user.get("web_token"):
            return user["web_token"]
        token = secrets.token_urlsafe(24)
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET web_token = ? WHERE telegram_id = ?",
                (token, telegram_id),
            )
        return token

    def get_last_weight_for_exercise(self, user_id: str, exercise: str) -> float | None:
        """
        Devuelve el último peso registrado para un ejercicio específico.

        [CONCEPTO: Sugerencia de carga progresiva]
        Pre-llenar el peso con el último valor registrado elimina fricción:
        el usuario parte del punto exacto donde lo dejó, solo ajusta si cambia.
        Busca el ejercicio más reciente ignorando mayúsculas/minúsculas.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT weight_kg FROM workouts
                   WHERE user_id = ? AND LOWER(exercise) = LOWER(?)
                   ORDER BY logged_at DESC LIMIT 1""",
                (user_id, exercise),
            ).fetchone()
            return row["weight_kg"] if row else None

    def get_today_workouts(self, user_id: str) -> list[dict]:
        """
        Devuelve todas las series registradas hoy por el usuario, en orden cronológico.

        [CONCEPTO: DATE() en SQLite]
        DATE('now') devuelve la fecha actual en UTC como 'YYYY-MM-DD'.
        DATE(logged_at) extrae solo la parte de fecha del timestamp.
        Comparar ambas filtra registros del día de hoy sin importar la hora.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, exercise, sets, reps, weight_kg, rir, notes, logged_at
                   FROM workouts
                   WHERE user_id = ? AND DATE(logged_at) = DATE('now')
                   ORDER BY logged_at ASC""",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_workouts(self, user_id: str, limit: int = 10) -> list[dict]:
        """Retorna los últimos N entrenamientos del usuario, del más reciente al más antiguo."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT exercise, sets, reps, weight_kg, logged_at
                   FROM workouts
                   WHERE user_id = ?
                   ORDER BY logged_at DESC
                   LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def is_onboarding_done(self, telegram_id: str) -> bool:
        """Devuelve True si el usuario completó el onboarding."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT onboarding_done FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            return bool(row and row["onboarding_done"])

    def update_training_days(self, telegram_id: str, training_days: str) -> None:
        """Actualiza los días de entrenamiento del usuario."""
        days_count = len([d for d in training_days.split(",") if d.strip()])
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET training_days = ?, days_per_week = ? WHERE telegram_id = ?",
                (training_days, days_count, telegram_id),
            )

    def save_session_override(
        self,
        user_id: str,
        target_date: str,
        scope: str,
        modification: str,
        reason: str | None = None,
    ) -> int:
        """
        Registra una modificación temporal a la sesión de entrenamiento.

        [CONCEPTO: Inmutabilidad de la rutina base + overrides]
        La rutina general nunca se toca para cambios temporales.
        En su lugar, añadimos un override que el agente consulta en el contexto.
        Patrón equivalente a "feature flags" o "config overrides" en software.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO session_overrides (user_id, target_date, scope, modification, reason)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, target_date, scope, modification, reason),
            )
            return cursor.lastrowid

    def get_active_overrides(self, user_id: str) -> list[dict]:
        """
        Devuelve los overrides vigentes: desde hoy hasta los próximos 7 días.

        [CONCEPTO: Ventana temporal de contexto]
        7 días es suficiente para que el agente vea cambios de "esta semana"
        sin cargar demasiado el system prompt con datos irrelevantes.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT target_date, scope, modification, reason
                   FROM session_overrides
                   WHERE user_id = ?
                     AND target_date >= DATE('now')
                     AND target_date <= DATE('now', '+7 days')
                   ORDER BY target_date ASC""",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_onboarding(
        self,
        telegram_id: str,
        training_days: str,
        session_time_minutes: int,
        equipment: str,
        home_equipment_detail: str | None,
        experience_level: str,
        daily_activity: str,
        limitations: str,
        goal: str,
        level_test_requested: bool,
    ) -> None:
        """Persiste las respuestas del onboarding y marca al usuario como configurado."""
        # [CONCEPTO: UPDATE con múltiples columnas]
        # Un solo UPDATE puede modificar N columnas a la vez.
        # Es más eficiente y atómico que N UPDATEs separados.
        days_count = len([d for d in training_days.split(",") if d.strip()])
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE users
                   SET training_days         = ?,
                       days_per_week         = ?,
                       session_time_minutes  = ?,
                       equipment             = ?,
                       home_equipment_detail = ?,
                       experience_level      = ?,
                       daily_activity        = ?,
                       limitations           = ?,
                       goal                  = ?,
                       level_test_requested  = ?,
                       onboarding_done       = 1
                   WHERE telegram_id = ?""",
                (
                    training_days, days_count, session_time_minutes, equipment,
                    home_equipment_detail, experience_level, daily_activity,
                    limitations, goal, int(level_test_requested), telegram_id,
                ),
            )

    def get_all_user_ids(self) -> list[str]:
        """Devuelve los telegram_ids de todos los usuarios registrados."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users").fetchall()
            return [row["telegram_id"] for row in rows]

    def save_routine(self, user_id: str, routine_text: str) -> int:
        """
        Guarda la rutina activa del usuario. Desactiva cualquier rutina anterior.

        [CONCEPTO: Transacciones atómicas con with conn]
        Las dos operaciones (UPDATE + INSERT) ocurren dentro de la misma
        transacción. Si alguna falla, SQLite hace rollback automático —
        nunca quedamos con dos rutinas activas ni con ninguna.
        El context manager 'with conn' en sqlite3 hace commit al salir o
        rollback si hay excepción.
        """
        with self._get_conn() as conn:
            # Desactivar rutina anterior (si existe)
            conn.execute(
                "UPDATE routines SET is_active = 0 WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            # Insertar la nueva como activa
            cursor = conn.execute(
                "INSERT INTO routines (user_id, routine_text) VALUES (?, ?)",
                (user_id, routine_text),
            )
            return cursor.lastrowid

    def get_active_routine(self, user_id: str) -> Optional[dict]:
        """Devuelve la rutina activa del usuario, o None si no tiene ninguna."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT routine_text, created_at
                   FROM routines
                   WHERE user_id = ? AND is_active = 1
                   ORDER BY id DESC
                   LIMIT 1""",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
