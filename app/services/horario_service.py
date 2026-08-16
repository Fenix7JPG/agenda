"""Servicio de generación de horario con soporte Turso.

Estrategia "sandbox + diff", idéntica para SQLite local y Turso:

1. SNAPSHOT: se copian las tablas `tareas`, `horario_generado` y
   `tareas_no_programadas` de la base real a una SQLite en memoria.
2. MOTOR: se ejecuta `generar_horario` sobre la memoria (hace toda la
   lectura/escritura intensiva sin tocar la red).
3. DIFF: sobre la base real se aplican solo los cambios resultantes:
   - se borran los bloques futuros y todas las tareas no programadas;
   - se insertan los bloques futuros y las no programadas generadas.

Los INSERT masivos usan `db.insert_rows_bulk`, que en Turso se traduce en
un único batch HTTP atómico.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from ..config import settings
from ..db import DDL_STATEMENTS, db
from .planificador import FORMATO_FECHA, generar_horario

MEMORIA = ":memory:"


def _crear_sandbox() -> sqlite3.Connection:
    conn = sqlite3.connect(MEMORIA)
    conn.row_factory = sqlite3.Row
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    return conn


def _copiar_tabla(conn_mem: sqlite3.Connection, tabla: str) -> None:
    """Copia todas las filas de una tabla de la base real a la memoria."""
    columnas = [f["name"] for f in db.fetch_all(f"PRAGMA table_info({tabla})")]
    filas = db.fetch_all(f"SELECT * FROM {tabla}")
    if not filas:
        return
    cols_sql = ", ".join(columnas)
    ph = ", ".join("?" for _ in columnas)
    sql = f"INSERT INTO {tabla} ({cols_sql}) VALUES ({ph})"
    conn_mem.executemany(sql, [tuple(f[col] for col in columnas) for f in filas])


def generar(ahora: datetime | None = None) -> dict:
    """Regenera el horario y devuelve un resumen con los cambios aplicados."""
    if ahora is None:
        ahora = datetime.now()
    ahora_str = ahora.strftime(FORMATO_FECHA)

    # 0. Tareas no recurrentes pendientes que ya "viven en el pasado"
    #    (su ventana terminó por completo): se reubican a partir de ahora
    #    conservando la duración de su ventana, para que esta generación
    #    las vuelva a organizar. Se arranca un minuto después de ahora:
    #    el diff de bloques solo recoge bloques con inicio estrictamente
    #    posterior a 'ahora', y un bloque clavado en 'ahora' se perdería.
    vencidas = db.fetch_all(
        "SELECT id, fecha_inicio, fecha_fin FROM tareas "
        "WHERE estado = 'pendiente' AND es_recurrente = 0 AND fecha_fin <= ?",
        (ahora_str,),
    )
    for fila in vencidas:
        inicio_viejo = datetime.strptime(fila["fecha_inicio"], FORMATO_FECHA)
        fin_viejo = datetime.strptime(fila["fecha_fin"], FORMATO_FECHA)
        duracion_ventana = fin_viejo - inicio_viejo
        nuevo_inicio = ahora + timedelta(minutes=1)
        nuevo_fin = nuevo_inicio + duracion_ventana
        db.conn.execute(
            "UPDATE tareas SET fecha_inicio = ?, fecha_fin = ?, "
            "actualizado_en = ? WHERE id = ?",
            (nuevo_inicio.strftime(FORMATO_FECHA),
             nuevo_fin.strftime(FORMATO_FECHA), ahora_str, fila["id"]),
        )
    if vencidas:
        db.commit()

    # 1. Sandbox en memoria con el estado actual
    mem = _crear_sandbox()
    for tabla in ("tareas", "horario_generado", "tareas_no_programadas"):
        _copiar_tabla(mem, tabla)

    # 2. Motor sobre la memoria
    generar_horario(
        MEMORIA, ahora=ahora, conn=mem, horizonte_dias=settings.horizonte_dias
    )

    # 3. Leer el resultado generado en memoria (solo los no fijados: los
    #    fijados ya existen en la base real y no deben reinsertarse)
    bloques_nuevos = mem.execute(
        "SELECT tarea_id, inicio, fin FROM horario_generado "
        "WHERE inicio > ? AND fijado = 0",
        (ahora_str,),
    ).fetchall()
    no_programadas = mem.execute(
        "SELECT tarea_id, motivo, duracion_faltante_min, detalles, fecha_intento "
        "FROM tareas_no_programadas"
    ).fetchall()

    # 4. Aplicar el diff sobre la base real en un único batch atómico
    #    (Turso: una sola petición HTTP; SQLite local: una transacción).
    n_eliminados = int(db.fetch_one(
        "SELECT COUNT(*) AS c FROM horario_generado "
        "WHERE inicio > ? AND fijado = 0",
        (ahora_str,),
    )["c"])

    sentencias: list[str] = [
        "DELETE FROM horario_generado WHERE inicio > "
        f"{db.sql_literal(ahora_str)} AND fijado = 0",
    ]
    for tarea_id, inicio, fin in bloques_nuevos:
        sentencias.append(
            "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES "
            f"({db.sql_literal(tarea_id)}, {db.sql_literal(inicio)}, {db.sql_literal(fin)})"
        )
    sentencias.append("DELETE FROM tareas_no_programadas")
    for tarea_id, motivo, falta, detalles, intento in no_programadas:
        sentencias.append(
            "INSERT INTO tareas_no_programadas "
            "(tarea_id, motivo, duracion_faltante_min, detalles, fecha_intento) VALUES "
            f"({db.sql_literal(tarea_id)}, {db.sql_literal(motivo)}, "
            f"{db.sql_literal(falta)}, {db.sql_literal(detalles)}, {db.sql_literal(intento)})"
        )
    db.atomic_statements(sentencias)

    return {
        "bloques_insertados": len(bloques_nuevos),
        "bloques_eliminados": n_eliminados,
        "no_programadas": len(no_programadas),
        "tareas_reorganizadas": len(vencidas),
    }


def listar_bloques(inicio: str | None = None, fin: str | None = None) -> list[dict]:
    """Bloques del horario con título, prioridad, recurrencia y fijado."""
    sql = """
        SELECT h.id, h.tarea_id, h.inicio, h.fin, h.completado, h.fijado,
               t.titulo, t.prioridad, t.es_recurrente
        FROM horario_generado h
        JOIN tareas t ON t.id = h.tarea_id
    """
    condiciones, params = [], []
    if inicio:
        condiciones.append("h.fin > ?")
        params.append(inicio)
    if fin:
        condiciones.append("h.inicio < ?")
        params.append(fin)
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY h.inicio"
    filas = db.fetch_all(sql, params)
    return [
        {
            "id": f["id"],
            "tarea_id": f["tarea_id"],
            "inicio": f["inicio"],
            "fin": f["fin"],
            "completado": bool(f["completado"]),
            "fijado": bool(f["fijado"]),
            "es_recurrente": bool(f["es_recurrente"]),
            "titulo": f["titulo"],
            "prioridad": f["prioridad"],
        }
        for f in filas
    ]


class ErrorMoverBloque(Exception):
    """Error de negocio al mover un bloque; lleva el código HTTP asociado."""

    def __init__(self, status_code: int, mensaje: str) -> None:
        super().__init__(mensaje)
        self.status_code = status_code
        self.mensaje = mensaje


def mover_bloque(bloque_id: int, nuevo_inicio: str, ahora: datetime | None = None) -> dict:
    """Mueve un bloque a una hora nueva (gestión manual del horario).

    Reglas: los bloques recurrentes no se pueden mover (candado); los
    completados tampoco; el destino no puede estar en el pasado ni
    solaparse con otro bloque. El bloque queda marcado como fijado para
    que la regeneración del horario no lo reubique.
    """
    if ahora is None:
        ahora = datetime.now()

    bloque = db.fetch_one(
        "SELECT h.id, h.tarea_id, h.inicio, h.fin, h.completado, h.fijado, "
        "t.es_recurrente, t.titulo, t.prioridad "
        "FROM horario_generado h JOIN tareas t ON t.id = h.tarea_id "
        "WHERE h.id = ?",
        (bloque_id,),
    )
    if bloque is None:
        raise ErrorMoverBloque(404, "Bloque no encontrado")
    if bloque["completado"]:
        raise ErrorMoverBloque(409, "No se puede mover un bloque completado")
    if bloque["es_recurrente"]:
        raise ErrorMoverBloque(
            409, "Este bloque es recurrente y no se puede mover")

    inicio_orig = datetime.strptime(bloque["inicio"], FORMATO_FECHA)
    fin_orig = datetime.strptime(bloque["fin"], FORMATO_FECHA)
    duracion = (fin_orig - inicio_orig).total_seconds() / 60

    inicio_nuevo = datetime.strptime(nuevo_inicio, FORMATO_FECHA)
    fin_nuevo = inicio_nuevo + timedelta(minutes=duracion)

    if inicio_nuevo < ahora:
        raise ErrorMoverBloque(400, "No se puede mover un bloque al pasado")

    solapados = db.fetch_one(
        "SELECT COUNT(*) AS c FROM horario_generado "
        "WHERE id != ? AND inicio < ? AND fin > ?",
        (bloque_id, fin_nuevo.strftime(FORMATO_FECHA),
         inicio_nuevo.strftime(FORMATO_FECHA)),
    )["c"]
    if solapados:
        raise ErrorMoverBloque(409, "Ya hay otro bloque en ese horario")

    db.conn.execute(
        "UPDATE horario_generado SET inicio = ?, fin = ?, fijado = 1 WHERE id = ?",
        (inicio_nuevo.strftime(FORMATO_FECHA),
         fin_nuevo.strftime(FORMATO_FECHA), bloque_id),
    )
    db.commit()
    return {
        "id": bloque["id"],
        "tarea_id": bloque["tarea_id"],
        "inicio": inicio_nuevo.strftime(FORMATO_FECHA),
        "fin": fin_nuevo.strftime(FORMATO_FECHA),
        "completado": bool(bloque["completado"]),
        "fijado": True,
        "es_recurrente": bool(bloque["es_recurrente"]),
        "titulo": bloque["titulo"],
        "prioridad": bloque["prioridad"],
    }


def actualizar_completado(
    bloque_id: int, completado: bool, ahora: datetime | None = None
) -> bool:
    """Marca un bloque como completado o pendiente.

    Regla (igual que en «Mis tareas»): solo se puede marcar como
    completado cuando su hora de fin ya pasó por completo; las
    actividades futuras no se pueden completar. Desmarcar (volver a
    pendiente) sí se permite en cualquier momento.
    """
    if ahora is None:
        ahora = datetime.now()

    if completado:
        bloque = db.fetch_one(
            "SELECT fin FROM horario_generado WHERE id = ?", (bloque_id,)
        )
        if bloque is None:
            return False
        fin = datetime.strptime(bloque["fin"], FORMATO_FECHA)
        if fin > ahora:
            raise ErrorMoverBloque(
                422,
                "El bloque aún no ha terminado: solo se puede completar "
                "una actividad cuyo horario ya pasó por completo",
            )

    cursor = db.conn.execute(
        "UPDATE horario_generado SET completado = ? WHERE id = ?",
        (1 if completado else 0, bloque_id),
    )
    db.commit()
    return cursor.rowcount > 0


def eliminar_bloque(bloque_id: int) -> bool:
    cursor = db.conn.execute(
        "DELETE FROM horario_generado WHERE id = ?", (bloque_id,)
    )
    db.commit()
    return cursor.rowcount > 0
