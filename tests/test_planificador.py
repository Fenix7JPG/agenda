"""
test_generar_horario.py
───────────────────────
Pruebas unitarias para el algoritmo de generación de horario (generar_horario.py).
Usa una base de datos SQLite en memoria. No necesita mock porque se inyecta 'ahora'.

Regla de descanso actualizada:
- Al terminar una tarea (bloque_entero o flexible) que haya durado 90 min o más,
  se reservan 10 min de descanso inmediatamente después.
"""
import os
import unittest
import sqlite3
from datetime import datetime, timedelta

import app.services.planificador as generar_horario

DB_MEMORY = ":memory:"
AHORA_REFERENCIA = datetime(2026, 7, 27, 8, 0, 0)


class BaseDeDatosTemporal:
    """Crea una base de datos en memoria a partir de un archivo schema.sql."""

    def __init__(self, schema_path: str = "schema.sql"):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        
        if not os.path.exists(schema_path):
            schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        self.conn.executescript(schema_sql)

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()


class TestGenerarHorario(unittest.TestCase):

    def _insertar_tarea(self, conn, titulo, fecha_inicio, fecha_fin, duracion_min,
                         prioridad=3, bloque_entero=True, es_recurrente=False,
                         recurrencia_min=None, recurrencia_inicio=None, recurrencia_fin=None):
        conn.execute(
            """INSERT INTO tareas (titulo, fecha_inicio, fecha_fin, duracion_min,
                                   prioridad, bloque_entero, es_recurrente,
                                   recurrencia_min, recurrencia_inicio, recurrencia_fin)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (titulo, fecha_inicio, fecha_fin, duracion_min,
             prioridad, bloque_entero, es_recurrente,
             recurrencia_min, recurrencia_inicio, recurrencia_fin)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def _leer_horario(self, conn):
        return conn.execute(
            "SELECT tarea_id, inicio, fin FROM horario_generado ORDER BY inicio"
        ).fetchall()

    # -----------------------------------------------------------------
    # Tests básicos
    # -----------------------------------------------------------------
    def test_tarea_simple_bloque_entero_se_agenda_en_el_futuro(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                 "2026-07-27 09:00:00", "2026-07-27 11:00:00", 60,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            inicio = datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            self.assertGreaterEqual(inicio, datetime(2026, 7, 27, 9, 0))
            self.assertLessEqual(fin, datetime(2026, 7, 27, 11, 0))
            self.assertEqual((fin - inicio).seconds // 60, 60)

    def test_tarea_no_bloque_entero_puede_dividirse(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea B",
                                 "2026-07-27 10:00:00", "2026-07-27 12:00:00", 90,
                                 prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            total_minutos = sum(
                (datetime.strptime(b["fin"], "%Y-%m-%d %H:%M:%S") -
                 datetime.strptime(b["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
                for b in bloques
            )
            self.assertEqual(total_minutos, 90)

    def test_respeto_de_prioridades(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Urgente",
                                 "2026-07-27 09:00:00", "2026-07-27 10:00:00", 60,
                                 prioridad=1, bloque_entero=True)
            self._insertar_tarea(conn, "No urgente",
                                 "2026-07-27 09:00:00", "2026-07-27 10:00:00", 60,
                                 prioridad=4, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            tarea_id_agendada = bloques[0]["tarea_id"]
            tarea = conn.execute("SELECT titulo FROM tareas WHERE id=?", (tarea_id_agendada,)).fetchone()
            self.assertEqual(tarea["titulo"], "Urgente")

    def test_no_se_agendan_tareas_en_el_pasado(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Pasada",
                                 "2026-07-26 10:00:00", "2026-07-26 12:00:00", 60)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 0)
            self.assertEqual(len(self._leer_horario(conn)), 0)

    def test_tarea_recurrente_genera_ocurrencias_dentro_del_horizonte(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Diaria",
                                "2026-07-26 09:00:00", "2026-07-26 10:00:00", 30,
                                prioridad=2, bloque_entero=True, es_recurrente=True,
                                recurrencia_min=1440,
                                recurrencia_inicio="2026-07-26 09:00:00",
                                recurrencia_fin="2026-07-28 23:59:00")
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 2)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 2)

    def test_recurrente_pendiente_en_el_pasado_se_reagenda_en_la_ventana(self):
        """Un bloque recurrente sin completar que quedó en el pasado se
        vuelve a agendar en lo que queda de la ventana de su ocurrencia."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Repaso semanal",
                                "2026-07-26 10:00:00", "2026-07-27 20:00:00", 90,
                                prioridad=2, bloque_entero=True, es_recurrente=True,
                                recurrencia_min=1440,
                                recurrencia_inicio="2026-07-26 10:00:00",
                                recurrencia_fin="2026-07-26 10:01:00")
            # Primera generación a las 08:00: bloque 08:00-09:30
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            # Seis horas después: el bloque quedó en el pasado sin completar
            tarde = AHORA_REFERENCIA + timedelta(hours=6)
            bloques_creados = generar_horario.generar_horario(
                DB_MEMORY, ahora=tarde, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            nuevos = [b for b in bloques if b["inicio"] >= "2026-07-27 14:00:00"]
            self.assertEqual(len(nuevos), 1)
            self.assertGreaterEqual(
                datetime.strptime(nuevos[0]["inicio"], "%Y-%m-%d %H:%M:%S"), tarde)

    def test_recurrente_completado_en_el_pasado_no_se_reagenda(self):
        """Los bloques completados en el pasado cuentan como hechos y no se
        vuelven a agendar al regenerar."""
        with BaseDeDatosTemporal() as conn:
            tarea_id = self._insertar_tarea(
                conn, "Repaso semanal",
                "2026-07-26 10:00:00", "2026-07-27 20:00:00", 90,
                prioridad=2, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-26 10:00:00",
                recurrencia_fin="2026-07-26 10:01:00")
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            conn.execute(
                "UPDATE horario_generado SET completado = 1 WHERE tarea_id = ?",
                (tarea_id,))
            conn.commit()
            tarde = AHORA_REFERENCIA + timedelta(hours=6)
            bloques_creados = generar_horario.generar_horario(
                DB_MEMORY, ahora=tarde, conn=conn)
            self.assertEqual(bloques_creados, 0)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)

    def test_recurrente_con_bloque_en_curso_se_reagenda_completo(self):
        """Un bloque en curso sin completar no cuenta como hecho: al
        regenerar se agendan de nuevo sus minutos completos."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Repaso semanal",
                                 "2026-07-26 10:00:00", "2026-07-27 20:00:00", 90,
                                 prioridad=2, bloque_entero=True, es_recurrente=True,
                                 recurrencia_min=1440,
                                 recurrencia_inicio="2026-07-26 10:00:00",
                                 recurrencia_fin="2026-07-26 10:01:00")
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            # A mitad del bloque (08:30): sigue en curso y sin completar
            medio = AHORA_REFERENCIA + timedelta(minutes=30)
            bloques_creados = generar_horario.generar_horario(
                DB_MEMORY, ahora=medio, conn=conn)
            # El motor re-agenda los 90 min completos (el bloque en curso
            # ocupa su hueco en el sandbox, así que el nuevo va después)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 2)
            nuevos = [b for b in bloques if b["inicio"] >= "2026-07-27 09:30:00"]
            self.assertEqual(len(nuevos), 1)

    def test_solapamiento_se_evita(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "T1",
                                 "2026-07-27 09:00:00", "2026-07-27 10:00:00", 60,
                                 prioridad=1, bloque_entero=True)
            self._insertar_tarea(conn, "T2",
                                 "2026-07-27 09:00:00", "2026-07-27 10:00:00", 60,
                                 prioridad=2, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertLessEqual(len(bloques), 1)

    # -----------------------------------------------------------------
    # Tests de planificación parcial
    # -----------------------------------------------------------------
    def test_bloque_entero_completo_si_cabe(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Completo",
                                 "2026-07-27 09:00:00", "2026-07-27 10:00:00", 60,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            duracion = (datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
            self.assertEqual(duracion, 60)

    def test_bloque_entero_tiempo_restante_mayor_que_duracion_no_fuerza_parcial(self):
        with BaseDeDatosTemporal() as conn:
            conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (999, '2026-07-27 07:00:00', '2026-07-27 10:30:00')")
            self._insertar_tarea(conn, "No parcial",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 60,
                                prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 0)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)

    def test_bloque_entero_tiempo_restante_menor_fuerza_parcial(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Parcial",
                                 "2026-07-27 09:00:00", "2026-07-27 09:45:00", 60,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            inicio = datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            self.assertEqual(inicio, datetime(2026, 7, 27, 9, 0))
            self.assertEqual(fin, datetime(2026, 7, 27, 9, 45))

    def test_bloque_entero_tiempo_restante_menor_usa_ahora(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "En curso",
                                 "2026-07-27 07:00:00", "2026-07-27 08:45:00", 60,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            inicio = datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            self.assertEqual(inicio, datetime(2026, 7, 27, 8, 0))
            self.assertEqual(fin, datetime(2026, 7, 27, 8, 45))

    def test_bloque_entero_sin_huecos_no_agenda_aunque_tiempo_insuficiente(self):
        with BaseDeDatosTemporal() as conn:
            conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (999, '2026-07-27 08:00:00', '2026-07-27 08:45:00')")
            self._insertar_tarea(conn, "Sin hueco",
                                 "2026-07-27 08:00:00", "2026-07-27 08:45:00", 60,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 0)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)

    def test_bloque_entero_deadline_vencido_no_agenda(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Vencida",
                                 "2026-07-27 07:00:00", "2026-07-27 07:30:00", 30,
                                 prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 0)

    # --- Flexible con deadline inminente ---
    def test_flexible_tiempo_restante_menor_fuerza_bloque_parcial(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Flexible ajustada",
                                "2026-07-27 08:00:00", "2026-07-27 10:30:00", 200,
                                prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            inicio = datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            self.assertEqual(inicio, datetime(2026, 7, 27, 8, 0))
            self.assertEqual(fin, datetime(2026, 7, 27, 10, 30))
            duracion = (fin - inicio).seconds // 60
            self.assertEqual(duracion, 150)

    def test_flexible_tiempo_restante_mayor_no_fuerza_parcial(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Flexible holgada",
                                 "2026-07-27 08:00:00", "2026-07-28 18:00:00", 90,
                                 prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            total = sum((datetime.strptime(b["fin"], "%Y-%m-%d %H:%M:%S") -
                         datetime.strptime(b["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
                        for b in bloques)
            self.assertEqual(total, 90)

    def test_flexible_sin_huecos_no_agenda_aunque_tiempo_insuficiente(self):
        with BaseDeDatosTemporal() as conn:
            conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (999, '2026-07-27 08:00:00', '2026-07-27 10:30:00')")
            self._insertar_tarea(conn, "Flexible sin hueco",
                                 "2026-07-27 08:00:00", "2026-07-27 10:30:00", 200,
                                 prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 0)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            self.assertEqual(bloques[0]["tarea_id"], 999)

    # -----------------------------------------------------------------
    # Tests de registro de tareas no programadas
    # -----------------------------------------------------------------
    def test_tarea_no_agendada_se_registra_en_no_programadas(self):
        with BaseDeDatosTemporal() as conn:
            conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (999, '2026-07-27 07:00:00', '2026-07-27 10:30:00')")
            self._insertar_tarea(conn, "No agendada",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 60,
                                prioridad=1, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            self.assertEqual(bloques[0]["tarea_id"], 999)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["tarea_id"], 1)
            self.assertEqual(registros[0]["duracion_faltante_min"], 60)
            self.assertEqual(registros[0]["motivo"], "sin hueco suficiente")

    def test_bloque_entero_parcial_registra_faltante(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Parcial",
                                "2026-07-27 09:00:00", "2026-07-27 09:45:00", 60,
                                prioridad=1, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            duracion = (datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
            self.assertEqual(duracion, 45)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["duracion_faltante_min"], 15)
            self.assertIn("parcial", registros[0]["motivo"].lower())

    def test_flexible_con_restante_registra_faltante(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Flex resto",
                     "2026-07-27 08:00:00", "2026-07-27 10:30:00", 200,
                     prioridad=1, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            total = sum((datetime.strptime(b["fin"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(b["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
                        for b in bloques)
            self.assertEqual(total, 150)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["duracion_faltante_min"], 50)

    def test_tarea_completada_no_genera_registro(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Completa",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 60,
                                prioridad=1, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 0)

    def test_tarea_vencida_se_registra(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Vencida",
                                "2026-07-27 07:00:00", "2026-07-27 07:30:00", 30,
                                prioridad=1, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["duracion_faltante_min"], 30)
            self.assertIn("vencido", registros[0]["motivo"].lower())

    def test_flexible_sin_hueco_no_agenda_y_registra(self):
        with BaseDeDatosTemporal() as conn:
            conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (999, '2026-07-27 08:00:00', '2026-07-27 10:30:00')")
            self._insertar_tarea(conn, "Flex sin hueco",
                                "2026-07-27 08:00:00", "2026-07-27 10:30:00", 90,
                                prioridad=1, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            registros = conn.execute("SELECT * FROM tareas_no_programadas").fetchall()
            self.assertEqual(len(registros), 1)
            self.assertEqual(registros[0]["duracion_faltante_min"], 90)

    # -----------------------------------------------------------------
    # Tests de descanso por ciclos y cambio de tarea (regla actualizada)
    # -----------------------------------------------------------------
    def test_tarea_larga_unica_se_divida_en_ciclos_90_10(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea Larga",
                                "2026-07-27 08:00:00", "2026-07-27 16:00:00", 360,
                                prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 4)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 4)
            for i in range(len(bloques) - 1):
                fin_anterior = datetime.strptime(bloques[i]["fin"], "%Y-%m-%d %H:%M:%S")
                inicio_siguiente = datetime.strptime(bloques[i+1]["inicio"], "%Y-%m-%d %H:%M:%S")
                diferencia = (inicio_siguiente - fin_anterior).total_seconds() / 60
                self.assertAlmostEqual(diferencia, 10)
            for b in bloques:
                duracion = (datetime.strptime(b["fin"], "%Y-%m-%d %H:%M:%S") -
                            datetime.strptime(b["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
                self.assertEqual(duracion, 90)

    def test_dos_tareas_largas_alternan_cada_3_ciclos(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                "2026-07-27 08:00:00", "2026-07-27 20:00:00", 300,
                                prioridad=1, bloque_entero=False)
            id_a = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            self._insertar_tarea(conn, "Tarea B",
                                "2026-07-27 08:00:00", "2026-07-27 20:00:00", 300,
                                prioridad=2, bloque_entero=False)
            id_b = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertGreater(len(bloques), 4)
            tareas_ids = [b["tarea_id"] for b in bloques]
            self.assertEqual(tareas_ids[0], id_a)
            self.assertEqual(tareas_ids[1], id_a)
            self.assertEqual(tareas_ids[2], id_a)
            self.assertIn(id_b, tareas_ids[3:5])

    def test_tarea_corta_sin_descansos_extra(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Corta",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 60,
                                prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            duracion = (datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
            self.assertEqual(duracion, 60)

    def test_tarea_con_ventana_ajustada_no_genera_descansos_innecesarios(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Ajustada",
                                "2026-07-27 09:00:00", "2026-07-27 12:20:00", 200,
                                prioridad=1, bloque_entero=False)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 3)
            total = sum((datetime.strptime(b["fin"], "%Y-%m-%d %H:%M:%S") -
                         datetime.strptime(b["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
                        for b in bloques)
            self.assertEqual(total, 200)
            for i in range(len(bloques) - 1):
                fin_anterior = datetime.strptime(bloques[i]["fin"], "%Y-%m-%d %H:%M:%S")
                inicio_siguiente = datetime.strptime(bloques[i+1]["inicio"], "%Y-%m-%d %H:%M:%S")
                self.assertEqual(fin_anterior, inicio_siguiente,
                                "Los bloques deben ser consecutivos, sin descansos")

    def test_bloque_entero_ignora_ciclos_y_descansos(self):
        """Un bloque_entero de 360 min se agenda completo; después de él se reserva descanso."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Intocable",
                                "2026-07-27 08:00:00", "2026-07-27 16:00:00", 360,
                                prioridad=1, bloque_entero=True)
            bloques_creados = generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(bloques_creados, 1)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1)
            duracion = (datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S") -
                        datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")).seconds // 60
            self.assertEqual(duracion, 360)

    def test_descanso_al_cambiar_de_tarea_con_ultimo_bloque_90min(self):
        """Tras un bloque flexible de 90 min, se añade descanso antes de la siguiente tarea."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 90,
                                prioridad=1, bloque_entero=False)
            self._insertar_tarea(conn, "Tarea B",
                                "2026-07-27 09:00:00", "2026-07-27 12:00:00", 30,
                                prioridad=2, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 2)
            self.assertEqual(bloques[0]["inicio"], "2026-07-27 09:00:00")
            self.assertEqual(bloques[0]["fin"], "2026-07-27 10:30:00")
            self.assertEqual(bloques[1]["inicio"], "2026-07-27 10:40:00")
            fin_b = datetime.strptime(bloques[1]["fin"], "%Y-%m-%d %H:%M:%S")
            inicio_b = datetime.strptime(bloques[1]["inicio"], "%Y-%m-%d %H:%M:%S")
            self.assertEqual((fin_b - inicio_b).seconds // 60, 30)

    def test_sin_descanso_si_ultimo_bloque_menor_de_90min(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                "2026-07-27 09:00:00", "2026-07-27 10:00:00", 45,
                                prioridad=1, bloque_entero=False)
            self._insertar_tarea(conn, "Tarea B",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 30,
                                prioridad=2, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 2)
            fin_a = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            inicio_b = datetime.strptime(bloques[1]["inicio"], "%Y-%m-%d %H:%M:%S")
            self.assertEqual(fin_a, inicio_b)

    def test_sin_descanso_si_no_hay_espacio_inmediato(self):
        """Si justo después no hay hueco para el descanso, simplemente no se inserta,
        y la tarea siguiente puede ocupar el espacio (sin descanso)."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                "2026-07-27 09:00:00", "2026-07-27 11:00:00", 90,
                                prioridad=1, bloque_entero=False)
            self._insertar_tarea(conn, "Tarea B",
                                "2026-07-27 10:30:00", "2026-07-27 11:00:00", 30,
                                prioridad=2, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertIn(len(bloques), [1, 2])
            if len(bloques) == 2:
                fin_a = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
                inicio_b = datetime.strptime(bloques[1]["inicio"], "%Y-%m-%d %H:%M:%S")
                self.assertEqual(fin_a, inicio_b)

    def test_descanso_solo_si_cambio_de_tarea_distinta(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Tarea A",
                                "2026-07-27 09:00:00", "2026-07-27 14:00:00", 200,
                                prioridad=1, bloque_entero=False)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = self._leer_horario(conn)
            self.assertGreater(len(bloques), 1)
            for i in range(len(bloques)-1):
                if bloques[i]["tarea_id"] == bloques[i+1]["tarea_id"]:
                    fin = datetime.strptime(bloques[i]["fin"], "%Y-%m-%d %H:%M:%S")
                    inicio = datetime.strptime(bloques[i+1]["inicio"], "%Y-%m-%d %H:%M:%S")
                    diff = (inicio - fin).total_seconds() / 60
                    self.assertIn(diff, [0, 10])

    # -----------------------------------------------------------------
    # NUEVOS tests de consistencia de descanso (siempre se pone)
    # -----------------------------------------------------------------
    def test_descanso_siempre_tras_bloque_entero_largo(self):
        """Un bloque_entero de 90 min fuerza descanso, impidiendo tarea inmediata."""
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Larga",
                                 "2026-07-27 09:00:00", "2026-07-27 10:30:00", 90,
                                 prioridad=1, bloque_entero=True)
            # La siguiente tarea empieza justo al terminar la larga, pero el descanso lo impide
            self._insertar_tarea(conn, "Corta",
                                 "2026-07-27 10:30:00", "2026-07-27 10:40:00", 10,
                                 prioridad=2, bloque_entero=True)
            generar_horario.generar_horario(":memory:", ahora=datetime(2026,7,27,8,0,0), conn=conn)
            bloques = self._leer_horario(conn)
            self.assertEqual(len(bloques), 1, "Solo la tarea larga debe agendarse")
            self.assertEqual(bloques[0]["tarea_id"], 1)

    def test_descanso_consistente_entre_dormir_y_quehaceres(self):
        """Después de Dormir (360 min) siempre hay 10 min de descanso antes de quehaceres."""
        with BaseDeDatosTemporal() as conn:
            id_dormir = self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440, recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            id_quehaceres = self._insertar_tarea(conn, "quehaceres",
                "2026-07-27 00:00:00", "2026-07-28 00:00:00", 30,
                prioridad=2, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440, recurrencia_inicio="2026-07-27 00:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            generar_horario.generar_horario(":memory:", ahora=datetime(2026,7,29,2,0,0), conn=conn)
            bloques = conn.execute(
                f"SELECT tarea_id, inicio, fin FROM horario_generado WHERE tarea_id IN ({id_dormir},{id_quehaceres}) ORDER BY inicio"
            ).fetchall()
            diffs = set()
            fin_dormir = None
            for tid, ini, fin in bloques:
                if tid == id_dormir:
                    fin_dormir = datetime.strptime(fin, "%Y-%m-%d %H:%M:%S")
                elif tid == id_quehaceres and fin_dormir is not None:
                    inicio_q = datetime.strptime(ini, "%Y-%m-%d %H:%M:%S")
                    diffs.add(int((inicio_q - fin_dormir).total_seconds() // 60))
                    fin_dormir = None
            self.assertEqual(diffs, {10}, "La pausa debe ser siempre 10 min")

    # -----------------------------------------------------------------
    # Tests de horizonte y Dormir (ya existentes, sin cambios)
    # -----------------------------------------------------------------
    def test_dormir_con_horizonte_2_dias_incluye_noche_del_segundo_dia(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            import app.services.planificador as generar_horario
            original = generar_horario.DIAS_HORIZONTE
            try:
                generar_horario.DIAS_HORIZONTE = 2
                generar_horario.generar_horario(":memory:",
                                                ahora=datetime(2026,7,27,8,0,0),
                                                conn=conn)
            finally:
                generar_horario.DIAS_HORIZONTE = original
            inicios = [r[0] for r in conn.execute(
                "SELECT inicio FROM horario_generado WHERE tarea_id=1 ORDER BY inicio"
            ).fetchall()]
            self.assertIn("2026-07-27 23:00:00", inicios)
            self.assertIn("2026-07-28 23:00:00", inicios)
            self.assertIn("2026-07-29 23:00:00", inicios)
            self.assertNotIn("2026-07-30 23:00:00", inicios)

    def test_dormir_recurrente_aparece_hasta_el_final_del_horizonte(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            import app.services.planificador as generar_horario
            original = generar_horario.DIAS_HORIZONTE
            try:
                generar_horario.DIAS_HORIZONTE = 30
                generar_horario.generar_horario(":memory:",
                                                ahora=datetime(2026,7,29,5,58,0),
                                                conn=conn)
            finally:
                generar_horario.DIAS_HORIZONTE = original
            inicios = [r[0] for r in conn.execute(
                "SELECT inicio FROM horario_generado WHERE tarea_id=1 ORDER BY inicio"
            ).fetchall()]
            self.assertIn("2026-08-28 23:00:00", inicios)
            self.assertNotIn("2026-08-29 23:00:00", inicios)

    def test_dormir_horizonte_30_desde_29jul_incluye_noche_28ago(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            import app.services.planificador as generar_horario
            original = generar_horario.DIAS_HORIZONTE
            try:
                generar_horario.DIAS_HORIZONTE = 30
                generar_horario.generar_horario(":memory:",
                                                ahora=datetime(2026,7,29,1,31,0),
                                                conn=conn)
            finally:
                generar_horario.DIAS_HORIZONTE = original
            inicios = [r[0] for r in conn.execute(
                "SELECT inicio FROM horario_generado WHERE tarea_id=1 ORDER BY inicio"
            ).fetchall()]
            self.assertIn("2026-08-28 23:00:00", inicios)
            self.assertNotIn("2026-08-29 23:00:00", inicios)

    def test_horizonte_redondeo_fin_dia_es_exacto(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            import app.services.planificador as generar_horario
            original = generar_horario.DIAS_HORIZONTE
            try:
                generar_horario.DIAS_HORIZONTE = 2
                generar_horario.generar_horario(":memory:",
                                                ahora=datetime(2026,7,27,8,0,0),
                                                conn=conn)
            finally:
                generar_horario.DIAS_HORIZONTE = original
            inicios = [r[0] for r in conn.execute(
                "SELECT inicio FROM horario_generado WHERE tarea_id=1 ORDER BY inicio"
            ).fetchall()]
            self.assertIn("2026-07-29 23:00:00", inicios)
            self.assertNotIn("2026-07-30 23:00:00", inicios)

    def test_ninguna_tarea_sobrepasa_horizonte(self):
        with BaseDeDatosTemporal() as conn:
            self._insertar_tarea(conn, "Dormir",
                "2026-07-27 23:00:00", "2026-07-28 05:00:00", 360,
                prioridad=1, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440,
                recurrencia_inicio="2026-07-27 23:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            self._insertar_tarea(conn, "Estudio semanal",
                "2026-08-24 10:00:00", "2026-08-31 08:30:00", 90,
                prioridad=4, bloque_entero=False, es_recurrente=True,
                recurrencia_min=10080,
                recurrencia_inicio="2026-08-24 10:00:00",
                recurrencia_fin="2026-09-18 08:30:00")
            import app.services.planificador as generar_horario
            original = generar_horario.DIAS_HORIZONTE
            try:
                generar_horario.DIAS_HORIZONTE = 30
                generar_horario.generar_horario(":memory:",
                                                ahora=datetime(2026,7,29,1,53,0),
                                                conn=conn)
            finally:
                generar_horario.DIAS_HORIZONTE = original
            limite = datetime(2026, 8, 28, 23, 59, 59)
            infracciones = conn.execute("""
                SELECT COUNT(*) FROM horario_generado
                WHERE inicio > ? OR fin > ?
            """, (limite.strftime("%Y-%m-%d %H:%M:%S"),)*2).fetchone()[0]
            self.assertEqual(infracciones, 0, "Hay bloques fuera del horizonte")
    def _insertar_bloque(self, conn, tarea_id, inicio_str, fin_str):
        conn.execute("INSERT INTO horario_generado (tarea_id, inicio, fin) VALUES (?, ?, ?)",
                    (tarea_id, inicio_str, fin_str))

    # -------------------------------------------------------------------
    # NUEVOS TESTS PARA PLANIFICACIÓN INCREMENTAL
    # -------------------------------------------------------------------
    
    def test_regeneracion_completa_no_duplica_bloques(self):
        """Al regenerar, cada tarea diaria debe tener exactamente un bloque por día."""
        with BaseDeDatosTemporal() as conn:
            id_q = self._insertar_tarea(conn, "quehaceres",
                "2026-07-27 00:00:00", "2026-07-28 00:00:00", 30,
                prioridad=2, bloque_entero=True, es_recurrente=True,
                recurrencia_min=1440, recurrencia_inicio="2026-07-27 00:00:00",
                recurrencia_fin="2027-07-27 00:00:00")
            # Ejecutar regeneración
            generar_horario.generar_horario(":memory:", ahora=datetime(2026,7,29,17,30,0), conn=conn)

            # Contar bloques para el 29/07
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM horario_generado WHERE tarea_id={id_q} AND inicio >= '2026-07-29 00:00:00' AND inicio < '2026-07-30 00:00:00'"
            ).fetchone()[0]
            self.assertEqual(cnt, 1, "Debe haber un único bloque por día tras regeneración completa")

    # -------------------------------------------------------------------
    # TESTS DE BLOQUES FIJADOS (movidos a mano, sobreviven a regenerar)
    # -------------------------------------------------------------------

    def test_bloque_fijado_sobrevive_y_su_tiempo_no_se_duplica(self):
        """Un bloque fijado se conserva al regenerar y sus minutos se
        descuentan de la tarea (no se agenda el mismo trabajo dos veces)."""
        with BaseDeDatosTemporal() as conn:
            id_t = self._insertar_tarea(conn, "Tarea manual",
                "2026-07-27 08:00:00", "2026-07-27 18:00:00", 60,
                prioridad=1, bloque_entero=True)
            conn.execute(
                "INSERT INTO horario_generado (tarea_id, inicio, fin, fijado) "
                "VALUES (?, ?, ?, 1)",
                (id_t, "2026-07-27 15:00:00", "2026-07-27 16:00:00"))
            generados = generar_horario.generar_horario(
                DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(generados, 0,
                             "La tarea ya está cubierta por el bloque fijado")
            bloques = conn.execute(
                "SELECT tarea_id, inicio, fin, fijado FROM horario_generado "
                "ORDER BY inicio").fetchall()
            self.assertEqual(len(bloques), 1)
            self.assertEqual(bloques[0]["inicio"], "2026-07-27 15:00:00")
            self.assertEqual(bloques[0]["fin"], "2026-07-27 16:00:00")
            self.assertEqual(bloques[0]["fijado"], 1)

    def test_bloque_fijado_al_borde_de_ventana_no_se_duplica(self):
        """Un bloque fijado a caballo del borde de la ventana cuenta su
        duración completa: regenerar no crea un bloque adicional."""
        with BaseDeDatosTemporal() as conn:
            id_t = self._insertar_tarea(conn, "Al borde",
                "2026-07-27 08:00:00", "2026-07-27 20:00:00", 60,
                prioridad=1, bloque_entero=True)
            conn.execute(
                "INSERT INTO horario_generado (tarea_id, inicio, fin, fijado) "
                "VALUES (?, ?, ?, 1)",
                (id_t, "2026-07-27 19:30:00", "2026-07-27 20:30:00"))
            generados = generar_horario.generar_horario(
                DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            self.assertEqual(generados, 0,
                             "No debe agendar trabajo ya reservado por el usuario")
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM horario_generado WHERE tarea_id=?",
                (id_t,)).fetchone()
            self.assertEqual(total["c"], 1,
                             "Debe quedar únicamente el bloque fijado")

    def test_bloque_fijado_de_otra_tarea_ocupa_el_hueco(self):
        """Un bloque fijado ajeno actúa como ocupado: la tarea nueva se
        agenda sin solaparse con él."""
        with BaseDeDatosTemporal() as conn:
            conn.execute(
                "INSERT INTO horario_generado (tarea_id, inicio, fin, fijado) "
                "VALUES (999, '2026-07-27 08:00:00', '2026-07-27 12:00:00', 1)")
            id_a = self._insertar_tarea(conn, "Tarea A",
                "2026-07-27 08:00:00", "2026-07-27 18:00:00", 120,
                prioridad=1, bloque_entero=True)
            generar_horario.generar_horario(DB_MEMORY, ahora=AHORA_REFERENCIA, conn=conn)
            bloques = conn.execute(
                "SELECT inicio, fin FROM horario_generado "
                "WHERE tarea_id=? AND fijado=0", (id_a,)).fetchall()
            self.assertEqual(len(bloques), 1)
            inicio = datetime.strptime(bloques[0]["inicio"], "%Y-%m-%d %H:%M:%S")
            fin = datetime.strptime(bloques[0]["fin"], "%Y-%m-%d %H:%M:%S")
            fin_fijado = datetime(2026, 7, 27, 12, 0)
            self.assertTrue(
                fin <= datetime(2026, 7, 27, 8, 0) or inicio >= fin_fijado,
                "La tarea no debe solaparse con el bloque fijado")
            self.assertGreaterEqual(inicio, fin_fijado,
                                    "Debe agendarse después del bloque fijado")

if __name__ == "__main__":
    unittest.main()