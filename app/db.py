"""Capa de acceso a datos con soporte dual: SQLite local y Turso.

El resto de la aplicación interactúa siempre a través de `db` (instancia
única de Database) y nunca conoce el motor subyacente.

- Modo local: sqlite3 estándar contra un archivo en data/.
- Modo Turso: cliente libsql contra la URL remota (credenciales en .env).

DDL: se define aquí en Python (lista de sentencias) y se ejecuta una a una,
lo que funciona igual en SQLite local y en Turso.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from .config import settings

# ---------------------------------------------------------------------------
# Esquema de la base de datos
# ---------------------------------------------------------------------------
DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS tareas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        descripcion TEXT,
        estado TEXT NOT NULL DEFAULT 'pendiente'
            CHECK (estado IN ('pendiente', 'completada', 'cancelada')),
        prioridad INTEGER NOT NULL DEFAULT 3,
        fecha_inicio TEXT NOT NULL,
        fecha_fin TEXT NOT NULL,
        duracion_min INTEGER NOT NULL DEFAULT 60,
        bloque_entero INTEGER NOT NULL DEFAULT 0,
        es_recurrente INTEGER NOT NULL DEFAULT 0,
        recurrencia_min INTEGER,
        recurrencia_inicio TEXT,
        recurrencia_fin TEXT,
        creado_en TEXT NOT NULL,
        actualizado_en TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS horario_generado (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id INTEGER NOT NULL,
        inicio TEXT NOT NULL,
        fin TEXT NOT NULL,
        completado INTEGER NOT NULL DEFAULT 0,
        fijado INTEGER NOT NULL DEFAULT 0,
        creado_en TEXT,
        FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tareas_no_programadas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id INTEGER NOT NULL,
        fecha_intento TEXT NOT NULL,
        motivo TEXT NOT NULL,
        duracion_faltante_min INTEGER NOT NULL DEFAULT 0,
        detalles TEXT,
        creado_en TEXT,
        FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS preferencias (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL,
        actualizado_en TEXT NOT NULL
    )
    """,
]

# Índices que agilizan las consultas del motor y de la API
DDL_INDICES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_horario_tarea ON horario_generado(tarea_id)",
    "CREATE INDEX IF NOT EXISTS idx_horario_inicio ON horario_generado(inicio)",
    "CREATE INDEX IF NOT EXISTS idx_no_prog_tarea ON tareas_no_programadas(tarea_id)",
]


def _escape_literal(value: Any) -> str:
    """Convierte un valor Python en un literal SQL seguro (para batch)."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


class TursoError(Exception):
    """Error devuelto por el servidor Turso."""


def _hrana_value(v: Any) -> dict:
    """Convierte un valor Python al formato de argumento Hrana."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "real", "value": str(v)}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "value": base64.b64encode(bytes(v)).decode("ascii")}
    return {"type": "text", "value": str(v)}


def _from_hrana(v: dict) -> Any:
    """Convierte un valor Hrana de respuesta a Python."""
    tipo = v.get("type")
    if tipo == "null":
        return None
    if tipo == "integer":
        return int(v["value"])
    if tipo == "text":
        return v["value"]
    if tipo == "real":
        return float(v["value"])
    if tipo == "blob":
        return base64.b64decode(v["value"])
    return v.get("value")


def _render_sql(sql: str, params: Sequence[Any]) -> str:
    """Interpola parámetros posicionales como literales SQL seguros."""
    it = iter(params)
    partes: list[str] = []
    for char in sql:
        if char == "?":
            try:
                partes.append(_escape_literal(next(it)))
            except StopIteration:
                partes.append("?")
        else:
            partes.append(char)
    return "".join(partes)


class TursoConnection:
    """Cliente Turso por HTTP (protocolo Hrana sobre /v2/pipeline).

    Expone la misma API estilo sqlite3 que usa el resto de la aplicación
    (execute/fetchall/fetchone/lastrowid/batch) más transacciones remotas
    con begin/commit_tx/rollback_tx. No depende del websocket (este
    endpoint de Turso no lo soporta) ni de aiohttp: usa solo stdlib.

    Las filas se devuelven como list[dict].
    """

    def __init__(self, url: str, auth_token: str | None) -> None:
        self._base_url = url.replace("libsql://", "https://").rstrip("/")
        self._token = auth_token or ""
        self._last_cols: list[str] = []
        self._last_rows: list[list[dict]] = []
        self.lastrowid: int | None = None
        self.rowcount: int = 0
        self._in_tx = False
        self._buffer: list[str] = []

    # -- transporte ----------------------------------------------------------
    def _pipeline(self, requests: list[dict]) -> list[dict]:
        """Envía una petición de pipeline y devuelve `results`."""
        body = json.dumps({"requests": requests}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/v2/pipeline",
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for r in payload.get("results", []):
            if r.get("type") == "error":
                raise TursoError(r["error"]["message"])
        return payload["results"]

    def _ok_result(self, resultado: dict) -> dict:
        if resultado.get("type") != "ok":
            raise TursoError(resultado.get("error", {}).get("message", "error desconocido"))
        return resultado["response"]["result"]

    # -- API tipo sqlite3 ------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> "TursoConnection":
        if self._in_tx:
            # modo transacción: se acumula y se envía en un único batch al confirmar
            self._buffer.append(_render_sql(sql, params))
            self._last_cols, self._last_rows = [], []
            self.lastrowid, self.rowcount = None, 0
            return self
        stmt = {"sql": sql, "args": [_hrana_value(p) for p in (params or ())]}
        request: dict = {"type": "execute", "stmt": stmt}
        result = self._ok_result(self._pipeline([request])[0])
        self._last_cols = [c.get("name") for c in result.get("cols") or []]
        self._last_rows = result.get("rows") or []
        rid = result.get("last_insert_rowid")
        self.lastrowid = int(rid) if rid is not None else None
        self.rowcount = result.get("affected_row_count") or 0
        return self

    def fetchall(self) -> list[dict]:
        return [
            {nombre: _from_hrana(row[i]) for i, nombre in enumerate(self._last_cols)}
            for row in self._last_rows
        ]

    def fetchone(self) -> dict | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def commit(self) -> None:
        pass  # cada sentencia se confirma al vuelo; batch/transacción dan atomicidad

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass  # HTTP no mantiene conexión abierta

    def batch(self, statements: list[str]) -> None:
        """Ejecuta varias sentencias en una sola petición (atómica)."""
        if self._in_tx:
            self._buffer.extend(statements)
            return
        request = {"type": "batch",
                   "batch": {"steps": [{"stmt": {"sql": s}} for s in statements]}}
        resultado = self._ok_result(self._pipeline([request])[0])
        for i, paso in enumerate(resultado.get("step_results") or []):
            if paso.get("type") == "error":
                raise TursoError(f"paso {i} del batch: {paso['error']['message']}")

    # -- transacciones remotas ------------------------------------------------
    # Turso HTTP no soporta transacciones interactivas entre peticiones
    # (BEGIN/COMMIT vía stream no persiste). Se emulan con un buffer local:
    # todo lo ejecutado entre begin() y commit_tx() se envía como UN batch
    # atómico al confirmar; rollback_tx() descarta el buffer sin enviar nada.
    def begin(self) -> None:
        if self._in_tx:
            return
        self._buffer = []
        self._in_tx = True

    def commit_tx(self) -> None:
        if not self._in_tx:
            return
        self._in_tx = False
        pendientes, self._buffer = self._buffer, []
        if pendientes:
            self.batch(pendientes)

    def rollback_tx(self) -> None:
        if not self._in_tx:
            return
        self._in_tx = False
        self._buffer = []


class Database:
    """Contenedor de conexiones por hilo + helpers de acceso.

    Cada hilo (petición de FastAPI) obtiene su propia conexión vía
    `db.conn`; las escrituras se confirman explícitamente con `db.commit()`.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    # -- conexiones ---------------------------------------------------------
    def connect(self) -> Any:
        if settings.usando_turso:
            return TursoConnection(settings.turso_url, settings.turso_auth_token)

        conn = sqlite3.connect(settings.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def conn(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self.connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def commit(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.commit()

    def rollback(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.rollback()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Contexto transaccional: atómico en Turso (transacción remota) y
        commit/rollback explícito en SQLite local."""
        if settings.usando_turso:
            conn = self.conn
            conn.begin()
            try:
                yield
                conn.commit_tx()
            except Exception:
                conn.rollback_tx()
                raise
            return
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise

    # -- helpers ------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        return self.conn.execute(sql, tuple(params))

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row is not None else None

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        cursor = self.conn.execute(sql, tuple(params))
        return int(cursor.lastrowid)

    def execute_many(self, sql: str, seq_params: Sequence[Sequence[Any]]) -> None:
        self.conn.executemany(sql, seq_params)

    def atomic_statements(self, statements: list[str]) -> None:
        """Aplica una lista de sentencias de forma atómica.

        En Turso se envían en un único batch HTTP (atómico); en SQLite
        local se ejecutan dentro de una transacción.
        """
        if not statements:
            return
        if settings.usando_turso:
            self.conn.batch(statements)
            return
        with self.transaction():
            for stmt in statements:
                self.conn.execute(stmt)

    @staticmethod
    def sql_literal(value: Any) -> str:
        """Convierte un valor Python en un literal SQL seguro."""
        return _escape_literal(value)

    # -- esquema ------------------------------------------------------------
    def init_schema(self) -> None:
        for stmt in DDL_STATEMENTS + DDL_INDICES:
            self.conn.execute(stmt)
        # Migración: la columna fijado se añadió después del esquema original
        # (bloques movidos a mano que sobreviven a la regeneración).
        try:
            columnas = [f["name"] for f in self.fetch_all(
                "PRAGMA table_info(horario_generado)")]
        except Exception:
            columnas = []
        if columnas and "fijado" not in columnas:
            self.conn.execute(
                "ALTER TABLE horario_generado "
                "ADD COLUMN fijado INTEGER NOT NULL DEFAULT 0")
        self.commit()

    # -- utilidades de migración / batch ------------------------------------
    def insert_rows_bulk(self, table: str, columns: list[str],
                         rows: Sequence[Sequence[Any]]) -> None:
        """Inserción masiva portátil (executemany en local, batch en Turso)."""
        if not rows:
            return
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        if settings.usando_turso:
            # En Turso el batch es una sola llamada HTTP y es atómico
            statements = [self._render_insert(table, columns, row) for row in rows]
            self.conn.batch(statements)
        else:
            self.execute_many(sql, rows)

    @staticmethod
    def _render_insert(table: str, columns: list[str],
                       row: Sequence[Any]) -> str:
        values = ", ".join(_escape_literal(v) for v in row)
        return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values})"


db = Database()
