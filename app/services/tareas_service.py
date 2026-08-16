"""CRUD de tareas con las validaciones de negocio del proyecto.

Las fechas se guardan y devuelven en formato 'YYYY-MM-DD HH:MM:SS' (hora
local), igual que en la versión original.
"""

from __future__ import annotations

from datetime import datetime

from ..db import db
from ..schemas import FORMATO_FECHA, TareaCreate, TareaUpdate

_ahora = lambda: datetime.now().strftime(FORMATO_FECHA)  # noqa: E731


class ErrorNegocio(ValueError):
    """Error de validación de reglas de negocio."""


def _normalizar_recurrencia(datos: dict) -> dict:
    """Si la tarea no es recurrente, limpia los campos de recurrencia."""
    if not datos.get("es_recurrente"):
        datos["recurrencia_min"] = None
        datos["recurrencia_inicio"] = None
        datos["recurrencia_fin"] = None
        return datos
    faltan = [c for c in ("recurrencia_min", "recurrencia_inicio", "recurrencia_fin")
              if not datos.get(c)]
    if faltan:
        raise ErrorNegocio(
            "Tarea recurrente: indique cada cuántos minutos se repite y el "
            "rango de recurrencia (inicio y fin)."
        )
    if datos["recurrencia_fin"] <= datos["recurrencia_inicio"]:
        raise ErrorNegocio("El fin de la recurrencia debe ser posterior a su inicio.")
    return datos


def _validar(datos: dict) -> None:
    if datos["fecha_fin"] <= datos["fecha_inicio"]:
        raise ErrorNegocio("La fecha de fin debe ser posterior a la fecha de inicio.")
    _normalizar_recurrencia(datos)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def listar(estado: str | None = None) -> list[dict]:
    sql = "SELECT * FROM tareas"
    params: tuple = ()
    if estado:
        sql += " WHERE estado = ?"
        params = (estado,)
    sql += " ORDER BY estado = 'pendiente' DESC, prioridad, fecha_inicio"
    filas = db.fetch_all(sql, params)
    return [_fila_a_dict(f) for f in filas]


def obtener(tarea_id: int) -> dict | None:
    fila = db.fetch_one("SELECT * FROM tareas WHERE id = ?", (tarea_id,))
    return _fila_a_dict(fila) if fila else None


def _fila_a_dict(fila: dict) -> dict:
    salida = dict(fila)
    salida["bloque_entero"] = bool(salida["bloque_entero"])
    salida["es_recurrente"] = bool(salida["es_recurrente"])
    return salida


# ---------------------------------------------------------------------------
# Mutaciones
# ---------------------------------------------------------------------------
def crear(datos: TareaCreate) -> dict:
    valores = datos.model_dump()
    _validar(valores)
    ahora = _ahora()
    tarea_id = db.insert(
        """INSERT INTO tareas
           (titulo, descripcion, estado, prioridad, fecha_inicio, fecha_fin,
            duracion_min, bloque_entero, es_recurrente, recurrencia_min,
            recurrencia_inicio, recurrencia_fin, creado_en, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            valores["titulo"],
            valores["descripcion"],
            valores["estado"],
            valores["prioridad"],
            valores["fecha_inicio"],
            valores["fecha_fin"],
            valores["duracion_min"],
            1 if valores["bloque_entero"] else 0,
            1 if valores["es_recurrente"] else 0,
            valores["recurrencia_min"],
            valores["recurrencia_inicio"],
            valores["recurrencia_fin"],
            ahora,
            ahora,
        ),
    )
    db.commit()
    return obtener(tarea_id)


def actualizar(tarea_id: int, cambios: TareaUpdate) -> dict | None:
    actual = obtener(tarea_id)
    if actual is None:
        return None
    nuevos = {k: v for k, v in cambios.model_dump().items() if v is not None}
    if not nuevos:
        return actual

    fusion = {**actual, **nuevos}
    _validar(fusion)

    campos = ", ".join(f"{c} = ?" for c in nuevos)
    parametros: list = []
    for c in nuevos:
        v = nuevos[c]
        parametros.append(1 if isinstance(v, bool) and c in ("bloque_entero", "es_recurrente") else v)
    parametros.append(_ahora())
    parametros.append(tarea_id)
    db.conn.execute(f"UPDATE tareas SET {campos}, actualizado_en = ? WHERE id = ?", parametros)
    db.commit()
    return obtener(tarea_id)


def cambiar_estado(tarea_id: int, estado: str) -> dict | None:
    fila = obtener(tarea_id)
    if fila is None:
        return None
    if estado == "completada":
        # Solo se puede completar una tarea que ya "vive en el pasado"
        # según su horario ASIGNADO: la recurrencia terminó (recurrente)
        # o el último bloque asignado ya terminó (no recurrente). No se
        # usa la ventana de asignación de la tarea: una ventana amplia no
        # convierte a la tarea en "en curso" ni habilita completarla antes
        # de que pase su hora realmente asignada.
        ahora = datetime.now()
        if fila["es_recurrente"]:
            fin_vida = datetime.strptime(fila["recurrencia_fin"], FORMATO_FECHA)
        else:
            bloque = db.fetch_one(
                "SELECT fin FROM horario_generado WHERE tarea_id = ? "
                "ORDER BY fin DESC LIMIT 1",
                (tarea_id,),
            )
            if bloque is None:
                raise ErrorNegocio(
                    "No se puede marcar como completada: la tarea aún no "
                    "tiene un horario asignado."
                )
            fin_vida = datetime.strptime(bloque["fin"], FORMATO_FECHA)
        if fin_vida > ahora:
            raise ErrorNegocio(
                "No se puede marcar como completada: su horario asignado "
                "aún no ha pasado por completo."
            )
    db.conn.execute(
        "UPDATE tareas SET estado = ?, actualizado_en = ? WHERE id = ?",
        (estado, _ahora(), tarea_id),
    )
    db.commit()
    return obtener(tarea_id)


def eliminar(tarea_id: int) -> bool:
    cursor = db.conn.execute("DELETE FROM tareas WHERE id = ?", (tarea_id,))
    db.commit()
    return cursor.rowcount > 0


def listar_no_programadas() -> list[dict]:
    filas = db.fetch_all(
        """SELECT n.id, n.tarea_id, n.fecha_intento, n.motivo,
                  n.duracion_faltante_min, n.detalles, t.titulo
           FROM tareas_no_programadas n
           JOIN tareas t ON t.id = n.tarea_id
           ORDER BY n.fecha_intento DESC, n.id DESC"""
    )
    return [dict(f) for f in filas]
