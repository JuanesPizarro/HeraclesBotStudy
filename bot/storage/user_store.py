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
        new_columns = [
            ("experience_level",      "TEXT"),
            ("days_per_week",         "INTEGER"),
            ("session_time_minutes",  "INTEGER"),
            ("equipment",             "TEXT"),
            ("home_equipment_detail", "TEXT"),
            ("daily_activity",        "TEXT"),
            ("limitations",           "TEXT"),
            ("level_test_requested",  "INTEGER DEFAULT 0"),
            ("onboarding_done",       "INTEGER DEFAULT 0"),
        ]
        with self._get_conn() as conn:
            existing = {
                row[1] for row in conn.execute("PRAGMA table_info(users)")
            }
            for col_name, col_type in new_columns:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
                    )

    def upsert_user(self, telegram_id: str, name: str) -> None:
        """Crea el usuario si no existe; no hace nada si ya existe."""
        # [CONCEPTO: UPSERT con INSERT OR IGNORE]
        # INSERT OR IGNORE intenta insertar; si hay conflicto en PRIMARY KEY,
        # simplemente ignora sin error. Evita duplicados.
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (telegram_id, name) VALUES (?, ?)",
                (telegram_id, name),
            )

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
    ) -> int:
        """Guarda un registro de entrenamiento y devuelve el ID del registro."""
        # [CONCEPTO: Parámetros con ? en SQL]
        # NUNCA concatenes strings en SQL: f"... WHERE id = {user_id}"
        # Eso permite SQL Injection. Usa siempre parámetros con ?.
        # La librería sanitiza los valores automáticamente.
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO workouts (user_id, exercise, sets, reps, weight_kg)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, exercise, sets, reps, weight_kg),
            )
            return cursor.lastrowid

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

    def save_onboarding(
        self,
        telegram_id: str,
        days_per_week: int,
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
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE users
                   SET days_per_week          = ?,
                       session_time_minutes   = ?,
                       equipment              = ?,
                       home_equipment_detail  = ?,
                       experience_level       = ?,
                       daily_activity         = ?,
                       limitations            = ?,
                       goal                   = ?,
                       level_test_requested   = ?,
                       onboarding_done        = 1
                   WHERE telegram_id = ?""",
                (
                    days_per_week, session_time_minutes, equipment,
                    home_equipment_detail, experience_level, daily_activity,
                    limitations, goal, int(level_test_requested), telegram_id,
                ),
            )

    def get_all_user_ids(self) -> list[str]:
        """Devuelve los telegram_ids de todos los usuarios registrados."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT telegram_id FROM users").fetchall()
            return [row["telegram_id"] for row in rows]
