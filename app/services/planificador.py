"""
app/services/planificador.py
─────────────────────────────
Motor de planificación del proyecto: organiza las tareas pendientes con la
regla de descanso que los tests ya exigían.

Algoritmo que organiza las tareas pendientes en bloques dentro de la tabla
`horario_generado`. Respeta ventanas flexibles, prioridades, recurrencia y
ciclos de concentración (90 min de trabajo, alternancia tras 3 ciclos
consecutivos). Si bloque_entero=True, no se divide.

Planificación:
- Se borran todos los bloques futuros antes de empezar (regeneración completa).
- Se planifican todas las ocurrencias desde 'ahora' hasta el horizonte,
  respetando prioridades.
- Los minutos ya realizados (bloques finalizados antes de 'ahora') no se tocan.

Regla de descanso (definida por los tests del proyecto):
- Tras terminar un bloque de 90 min o más (de una tarea flexible o de una
  tarea bloque_entero) se reservan 10 min de descanso inmediatamente después,
  marcando ese hueco como ocupado para la planificación de las demás tareas.
- Entre ciclos consecutivos de una MISMA tarea flexible se intercala descanso
  de 10 min SOLO si la ventana es lo bastante holgada para que la tarea siga
  cabiendo completa (nunca se generan descansos que "rompan" una ventana
  ajustada).
- El descanso no se inserta como bloque en la base de datos: únicamente
  reserva el hueco en la planificación de esta corrida.
"""

import copy
import math
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------
# Constantes de los ciclos de concentración
# ---------------------------------------------------------------------
CICLO_TRABAJO_MIN = 90
MAX_CICLOS_SEGUIDOS = 3
DIAS_HORIZONTE = 7
DESCANSO_MIN = 10

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------
# DDL mínimo del motor (usado solo cuando se ejecuta sin conexión
# inyectada: crea la base desde cero, igual que el script original con
# su schema.sql). La aplicación web usa su propio DDL en app/db.py.
# ---------------------------------------------------------------------
_DDL_ENGINE = [
    """
    CREATE TABLE IF NOT EXISTS tareas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        descripcion TEXT,
        estado TEXT DEFAULT 'pendiente'
            CHECK(estado IN ('pendiente', 'completada', 'cancelada')),
        prioridad INTEGER DEFAULT 3 CHECK(prioridad >= 1),
        fecha_inicio TEXT NOT NULL,
        fecha_fin TEXT NOT NULL,
        duracion_min INTEGER NOT NULL,
        bloque_entero INTEGER DEFAULT 0,
        es_recurrente INTEGER DEFAULT 0,
        recurrencia_min INTEGER,
        recurrencia_inicio TEXT,
        recurrencia_fin TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS horario_generado (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id INTEGER NOT NULL,
        inicio TEXT NOT NULL,
        fin TEXT NOT NULL,
        completado INTEGER DEFAULT 0,
        fijado INTEGER DEFAULT 0,
        FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tareas_no_programadas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarea_id INTEGER NOT NULL,
        fecha_intento TEXT,
        motivo TEXT NOT NULL DEFAULT 'falta de tiempo',
        duracion_faltante_min INTEGER NOT NULL DEFAULT 0,
        detalles TEXT,
        FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
    )
    """,
]


# ---------------------------------------------------------------------
# Funciones auxiliares de intervalos
# ---------------------------------------------------------------------
def _merge_intervals(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_int = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_int[0]]
    for start, end in sorted_int[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _free_gaps(occupied: List[Tuple[datetime, datetime]],
               window_start: datetime,
               window_end: datetime) -> List[Tuple[datetime, datetime]]:
    clipped = []
    for s, e in occupied:
        if e <= window_start or s >= window_end:
            continue
        clipped.append((max(s, window_start), min(e, window_end)))
    merged = _merge_intervals(clipped)
    gaps = []
    cursor = window_start
    for s, e in merged:
        if cursor < s:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def _total_free_minutes(occupied, window_start, window_end):
    gaps = _free_gaps(occupied, window_start, window_end)
    return sum((e - s).total_seconds() / 60 for s, e in gaps)


def _add_interval(intervals: List[Tuple[datetime, datetime]],
                  start: datetime, end: datetime):
    intervals.append((start, end))
    merged = _merge_intervals(intervals)
    intervals.clear()
    intervals.extend(merged)


def _reservar_descanso(occupied: List[Tuple[datetime, datetime]],
                       desde: datetime) -> bool:
    """Reserva 10 min de descanso tras `desde` si el espacio inmediato está
    libre. No inserta nada en la base de datos: solo marca el hueco como
    ocupado para el resto de la planificación."""
    fin = desde + timedelta(minutes=DESCANSO_MIN)
    for s, e in occupied:
        if s < fin and desde < e:
            return False
    _add_interval(occupied, desde, fin)
    return True


def _minutos_planificados_pasado(conn, tarea_id, ventana_inicio, ventana_fin, ahora):
    """Minutos ya dados por hechos: bloques completados o en curso.

    Los bloques sin completar que quedaron por completo en el pasado NO
    cuentan: el planificador los vuelve a agendar en lo que queda de la
    ventana (reorganización de pendientes atrasados).
    """
    rows = conn.execute(
        "SELECT inicio, fin FROM horario_generado "
        "WHERE tarea_id=? AND inicio <= ? AND fin > ? "
        "AND (completado = 1 OR fin > ?)",
        (tarea_id, ahora.strftime(FORMATO_FECHA),
         ventana_inicio.strftime(FORMATO_FECHA),
         ahora.strftime(FORMATO_FECHA))
    ).fetchall()
    total = 0
    for r in rows:
        i = datetime.strptime(r["inicio"], FORMATO_FECHA)
        f = datetime.strptime(r["fin"], FORMATO_FECHA)
        if f > ventana_inicio:  # al menos algo dentro de la ventana
            solapado_inicio = max(i, ventana_inicio)
            solapado_fin = min(f, ventana_fin)
            if solapado_fin > solapado_inicio:
                total += (solapado_fin - solapado_inicio).total_seconds() / 60
    return total


def _minutos_fijados_en(conn, tarea_id, ventana_inicio, ventana_fin):
    """Minutos de bloques movidos a mano (fijado=1) de una tarea.

    Cuenta la duración completa de los bloques fijados que intersectan la
    ventana: si el usuario movió el bloque (aunque quede a caballo del borde),
    ese trabajo ya está reservado y no debe planificarse de nuevo.
    """
    rows = conn.execute(
        "SELECT inicio, fin FROM horario_generado "
        "WHERE tarea_id=? AND fijado=1 AND fin > ? AND inicio < ?",
        (tarea_id, ventana_inicio.strftime(FORMATO_FECHA),
         ventana_fin.strftime(FORMATO_FECHA))
    ).fetchall()
    total = 0
    for r in rows:
        i = datetime.strptime(r["inicio"], FORMATO_FECHA)
        f = datetime.strptime(r["fin"], FORMATO_FECHA)
        total += (f - i).total_seconds() / 60
    return total


# ---------------------------------------------------------------------
# Planificación con ciclos de concentración + regla de descanso
# ---------------------------------------------------------------------
def _planificar_en_ciclos(vt, occupied, conn, ignorar_limite_ciclos=False) -> Tuple[int, int, Optional[Dict]]:
    """
    Devuelve (duracion_restante, bloques_insertados, ultimo_bloque).
    ultimo_bloque es un dict {'fin': datetime, 'duracion': int} o None.
    """
    tarea_id = vt["id"]
    dur = vt["duracion_min"]
    w_start = vt["ventana_inicio"]
    w_end = vt["ventana_fin"]
    ultimo_bloque = None
    if dur <= 0:
        return 0, 0, None

    tiempo_ventana = (w_end - w_start).total_seconds() / 60.0

    # Si la ventana total es más corta que la duración, forzamos un bloque máximo
    if tiempo_ventana < dur:
        gaps = _free_gaps(occupied, w_start, w_end)
        if gaps:
            g_start, g_end = gaps[0]
            block_start = max(g_start, w_start)
            block_end = min(block_start + timedelta(minutes=dur), w_end)
            if block_start < block_end:
                conn.execute(
                    "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                    (tarea_id, block_start.strftime(FORMATO_FECHA),
                     block_end.strftime(FORMATO_FECHA))
                )
                _add_interval(occupied, block_start, block_end)
                duracion_real = (block_end - block_start).total_seconds() / 60
                if duracion_real >= CICLO_TRABAJO_MIN:
                    _reservar_descanso(occupied, block_end)
                return dur - duracion_real, 1, {'fin': block_end, 'duracion': duracion_real}
        return dur, 0, None

    # Caso normal: duración <= CICLO_TRABAJO_MIN
    if dur <= CICLO_TRABAJO_MIN:
        gaps = _free_gaps(occupied, w_start, w_end)
        for g_start, g_end in gaps:
            if (g_end - g_start).total_seconds() / 60 >= dur:
                block_end = g_start + timedelta(minutes=dur)
                conn.execute(
                    "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                    (tarea_id, g_start.strftime(FORMATO_FECHA),
                     block_end.strftime(FORMATO_FECHA))
                )
                _add_interval(occupied, g_start, block_end)
                if dur >= CICLO_TRABAJO_MIN:
                    _reservar_descanso(occupied, block_end)
                ultimo_bloque = {'fin': block_end, 'duracion': dur}
                return 0, 1, ultimo_bloque

        # Si no cupo y la ventana es insuficiente, se fuerza parcial
        tiempo_disponible = (w_end - w_start).total_seconds() / 60.0
        if 0 < tiempo_disponible < dur and gaps:
            g_start, g_end = gaps[0]
            block_start = max(g_start, w_start)
            block_end = min(block_start + timedelta(minutes=dur), w_end)
            if block_start < block_end:
                conn.execute(
                    "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                    (tarea_id, block_start.strftime(FORMATO_FECHA),
                     block_end.strftime(FORMATO_FECHA))
                )
                _add_interval(occupied, block_start, block_end)
                duracion_real = (block_end - block_start).total_seconds() / 60
                if duracion_real >= CICLO_TRABAJO_MIN:
                    _reservar_descanso(occupied, block_end)
                ultimo_bloque = {'fin': block_end, 'duracion': duracion_real}
                return dur - duracion_real, 1, ultimo_bloque
        return dur, 0, None

    # Duración > CICLO_TRABAJO_MIN: planificación por ciclos con descansos
    remaining = dur
    bloques_insertados = 0
    ciclos_seguidos = 0

    # Descansos entre ciclos de la misma tarea solo si la ventana es lo
    # bastante holgada para acomodar la tarea completa con sus descansos.
    num_ciclos_estimado = math.ceil(dur / CICLO_TRABAJO_MIN)
    requiere_descansos = tiempo_ventana >= dur + DESCANSO_MIN * (num_ciclos_estimado - 1)

    while remaining > 0 and (ignorar_limite_ciclos or ciclos_seguidos < MAX_CICLOS_SEGUIDOS):
        bloque_duracion = min(remaining, CICLO_TRABAJO_MIN)
        colocado = False

        gaps = _free_gaps(occupied, w_start, w_end)
        for g_start, g_end in gaps:
            if (g_end - g_start).total_seconds() / 60 >= bloque_duracion:
                block_start = g_start
                block_end = block_start + timedelta(minutes=bloque_duracion)

                conn.execute(
                    "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                    (tarea_id, block_start.strftime(FORMATO_FECHA),
                     block_end.strftime(FORMATO_FECHA))
                )
                _add_interval(occupied, block_start, block_end)

                remaining -= bloque_duracion
                bloques_insertados += 1
                ciclos_seguidos += 1
                ultimo_bloque = {'fin': block_end, 'duracion': bloque_duracion}
                colocado = True

                # Regla de descanso: tras un bloque de 90+ min reservamos
                # descanso si la tarea terminó o si la ventana lo permite.
                if bloque_duracion >= CICLO_TRABAJO_MIN and (remaining == 0 or requiere_descansos):
                    _reservar_descanso(occupied, block_end)
                break

        if not colocado:
            # ¿Deadline inminente? forzar un bloque parcial
            tiempo_disponible = (w_end - w_start).total_seconds() / 60.0
            if 0 < tiempo_disponible < remaining:
                gaps = _free_gaps(occupied, w_start, w_end)
                if gaps:
                    g_start, g_end = gaps[0]
                    block_start = max(g_start, w_start)
                    block_end = min(block_start + timedelta(minutes=remaining), w_end)
                    if block_start < block_end:
                        conn.execute(
                            "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                            (tarea_id, block_start.strftime(FORMATO_FECHA),
                             block_end.strftime(FORMATO_FECHA))
                        )
                        _add_interval(occupied, block_start, block_end)
                        duracion_real = (block_end - block_start).total_seconds() / 60
                        remaining -= duracion_real
                        bloques_insertados += 1
                        ultimo_bloque = {'fin': block_end, 'duracion': duracion_real}
                        if duracion_real >= CICLO_TRABAJO_MIN:
                            _reservar_descanso(occupied, block_end)
            break

    return remaining, bloques_insertados, ultimo_bloque


# ---------------------------------------------------------------------
# Función principal (regeneración completa desde ahora)
# ---------------------------------------------------------------------
def generar_horario(db_path: str = "mi_base.db",
                    ahora: Optional[datetime] = None,
                    conn: Optional[sqlite3.Connection] = None,
                    horizonte_dias: Optional[int] = None) -> int:
    if ahora is None:
        ahora = datetime.now()

    cerrar_conexion = False
    if conn is None:
        conn = sqlite3.connect(db_path)
        for stmt in _DDL_ENGINE:
            conn.execute(stmt)
        conn.commit()
        cerrar_conexion = True

    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass  # en Turso remoto el PRAGMA puede no estar disponible

    dias_horizonte = horizonte_dias if horizonte_dias is not None else DIAS_HORIZONTE

    # Limpiar tareas no programadas antiguas
    conn.execute("DELETE FROM tareas_no_programadas")

    # ─── Borrar los bloques futuros que no estén fijados a mano ───
    # (regeneración completa; los bloques movidos por el usuario se conservan)
    conn.execute("DELETE FROM horario_generado WHERE inicio > ? AND fijado = 0",
                 (ahora.strftime(FORMATO_FECHA),))

    # 2. Cargar ocupados iniciales: bloques que terminen después de 'ahora'
    #    y además todos los bloques fijados (reservados por el usuario)
    ocupados_iniciales = conn.execute(
        "SELECT inicio, fin FROM horario_generado WHERE inicio <= ? OR fijado = 1",
        (ahora.strftime(FORMATO_FECHA),)
    ).fetchall()
    occupied = []
    for row in ocupados_iniciales:
        inicio = datetime.strptime(row["inicio"], FORMATO_FECHA)
        fin = datetime.strptime(row["fin"], FORMATO_FECHA)
        if fin > ahora:
            _add_interval(occupied, inicio, fin)

    # 3. Obtener tareas pendientes
    tareas = conn.execute("""
        SELECT id, titulo, fecha_inicio, fecha_fin, duracion_min,
               prioridad, bloque_entero, es_recurrente,
               recurrencia_min, recurrencia_inicio, recurrencia_fin
        FROM tareas
        WHERE estado = 'pendiente'
    """).fetchall()

    virtual_tasks = []
    horizonte = (ahora + timedelta(days=dias_horizonte)).replace(hour=23, minute=59, second=59, microsecond=0)
    faltantes = []

    for t in tareas:
        t_start = datetime.strptime(t["fecha_inicio"], FORMATO_FECHA)
        t_end = datetime.strptime(t["fecha_fin"], FORMATO_FECHA)
        duration = t["duracion_min"]

        if t["es_recurrente"]:
            rec_min = t["recurrencia_min"]
            if rec_min is None or rec_min <= 0:
                continue
            rec_start = datetime.strptime(t["recurrencia_inicio"], FORMATO_FECHA)
            rec_end = datetime.strptime(t["recurrencia_fin"], FORMATO_FECHA)
            window_dur = (t_end - t_start).total_seconds() / 60

            current = rec_start
            while current + timedelta(minutes=window_dur) <= ahora and current <= rec_end:
                current += timedelta(minutes=rec_min)

            limite = min(rec_end, horizonte)
            while current <= limite:
                occ_end = current + timedelta(minutes=window_dur)

                if occ_end > ahora:
                    eff_start = max(ahora, current)
                    eff_end = min(occ_end, horizonte)
                    ya_hecho = _minutos_planificados_pasado(conn, t["id"], current, occ_end, ahora)
                    ya_fijado = _minutos_fijados_en(conn, t["id"], eff_start, eff_end)
                    duracion_restante = max(0, t["duracion_min"] - ya_hecho - ya_fijado)
                    if duracion_restante > 0:
                        virtual_tasks.append({
                            "id": t["id"],
                            "titulo": t["titulo"],
                            "ventana_inicio": eff_start,
                            "ventana_fin": eff_end,
                            "duracion_min": duracion_restante,
                            "bloque_entero": t["bloque_entero"],
                            "prioridad": t["prioridad"]
                        })
                current += timedelta(minutes=rec_min)
        else:
            eff_start = max(ahora, t_start)
            eff_end = min(t_end, horizonte)
            if eff_end <= eff_start or duration <= 0:
                faltantes.append((t["id"], "deadline vencido", duration))
                continue
            # Descontar minutos ya reservados por bloques movidos a mano
            duracion_efectiva = duration - _minutos_fijados_en(conn, t["id"], eff_start, eff_end)
            if duracion_efectiva <= 0:
                continue  # esta tarea ya quedó cubierta por bloques fijados
            virtual_tasks.append({
                "id": t["id"],
                "titulo": t["titulo"],
                "ventana_inicio": eff_start,
                "ventana_fin": eff_end,
                "duracion_min": duracion_efectiva,
                "bloque_entero": t["bloque_entero"],
                "prioridad": t["prioridad"]
            })

    virtual_tasks.sort(key=lambda x: (x["prioridad"], x["ventana_inicio"]))

    total_bloques_insertados = 0
    tareas_con_restante = []

    # ─── Primera ronda ───
    for vt in virtual_tasks:
        if vt["bloque_entero"]:
            w_start = vt["ventana_inicio"]
            w_end = vt["ventana_fin"]
            dur = vt["duracion_min"]
            gaps = _free_gaps(occupied, w_start, w_end)
            colocado = False

            for g_start, g_end in gaps:
                if (g_end - g_start).total_seconds() / 60 >= dur:
                    block_end = g_start + timedelta(minutes=dur)
                    conn.execute(
                        "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                        (vt["id"], g_start.strftime(FORMATO_FECHA),
                         block_end.strftime(FORMATO_FECHA))
                    )
                    _add_interval(occupied, g_start, block_end)
                    total_bloques_insertados += 1
                    colocado = True
                    if dur >= CICLO_TRABAJO_MIN:
                        _reservar_descanso(occupied, block_end)
                    break

            if not colocado:
                tiempo_disponible = (w_end - w_start).total_seconds() / 60.0
                if 0 < tiempo_disponible < dur and gaps:
                    g_start, g_end = gaps[0]
                    block_start = max(g_start, w_start)
                    block_end = min(block_start + timedelta(minutes=dur), w_end)
                    if block_start < block_end:
                        conn.execute(
                            "INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                            (vt["id"], block_start.strftime(FORMATO_FECHA),
                             block_end.strftime(FORMATO_FECHA))
                        )
                        _add_interval(occupied, block_start, block_end)
                        total_bloques_insertados += 1
                        duracion_real = (block_end - block_start).total_seconds() / 60
                        if duracion_real >= CICLO_TRABAJO_MIN:
                            _reservar_descanso(occupied, block_end)
                        if dur - duracion_real > 0:
                            faltantes.append((vt["id"], "parcial por deadline", dur - duracion_real))
                else:
                    faltantes.append((vt["id"], "sin hueco suficiente", dur))
        else:
            restante, insertados, ultimo = _planificar_en_ciclos(vt, occupied, conn)
            total_bloques_insertados += insertados
            if restante > 0:
                faltantes.append((vt["id"], "restante tras planificación", restante))
                if _free_gaps(occupied, vt["ventana_inicio"], vt["ventana_fin"]):
                    vt_restante = copy.deepcopy(vt)
                    vt_restante["duracion_min"] = restante
                    tareas_con_restante.append(vt_restante)

    # ─── Segunda ronda (reintentos, sin límite de ciclos) ───
    tareas_con_restante.sort(key=lambda x: (x["prioridad"], x["ventana_inicio"]))
    for vt in tareas_con_restante:
        restante, insertados, ultimo = _planificar_en_ciclos(vt, occupied, conn, ignorar_limite_ciclos=True)
        total_bloques_insertados += insertados
        if restante > 0:
            faltantes.append((vt["id"], "restante tras segunda ronda", restante))

    # ─── Insertar registros de tareas no programadas ───
    for tarea_id, motivo, falta_min in faltantes:
        conn.execute(
            "INSERT INTO tareas_no_programadas (tarea_id, motivo, duracion_faltante_min, detalles, fecha_intento) "
            "VALUES (?, ?, ?, ?, ?)",
            (tarea_id, motivo, int(falta_min), None, ahora.strftime(FORMATO_FECHA))
        )

    conn.commit()
    if cerrar_conexion:
        conn.close()
    return total_bloques_insertados


if __name__ == "__main__":
    generar_horario()
