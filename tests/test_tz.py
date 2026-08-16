"""Tests del reloj de la aplicación (app/tz.py).

El fix de zona horaria: el backend debe generar horarios en hora de Perú
(UTC-5) sin importar la zona horaria del servidor (Render corre en UTC).
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import app.services.planificador as planificador
from app.tz import ahora_local, zona_local


def test_zona_local_por_defecto_utc_menos_5():
    assert zona_local().utcoffset(None) == timedelta(hours=-5)


def test_ahora_local_es_naive():
    assert ahora_local().tzinfo is None


def test_ahora_local_coincide_con_utc_mas_offset():
    """En cualquier servidor, ahora_local() debe equivaler a UTC+offset."""
    offset = zona_local().utcoffset(None)
    esperado = (datetime.now(timezone.utc) + offset).replace(tzinfo=None)
    diff = abs((ahora_local() - esperado).total_seconds())
    assert diff < 5, f"diferencia de {diff}s con UTC+offset"


def test_offset_configurable_por_variable_de_entorno(monkeypatch):
    monkeypatch.setenv("APP_UTC_OFFSET", "-6")
    assert zona_local().utcoffset(None) == timedelta(hours=-6)


def test_offset_invalido_vuelve_a_menos_5(monkeypatch):
    monkeypatch.setenv("APP_UTC_OFFSET", "abc")
    assert zona_local().utcoffset(None) == timedelta(hours=-5)


def test_generar_horario_sin_injectar_ahora_arranca_en_hora_lima(tmp_path):
    """Simula Render: sin inyectar 'ahora', el motor debe planear desde la
    hora de Perú, no desde la hora UTC del servidor."""
    # Base con una sola tarea de ventana amplia que incluye ahora
    hoy_lima = ahora_local()
    inicio_ventana = (hoy_lima - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    fin_ventana = (hoy_lima + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in planificador._DDL_ENGINE:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO tareas (titulo, fecha_inicio, fecha_fin, duracion_min, "
        "prioridad, bloque_entero, es_recurrente) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Clase de prueba", inicio_ventana, fin_ventana, 60, 3, 1, 0),
    )
    conn.commit()

    # Llamada sin 'ahora': usa ahora_local() internamente
    planificador.generar_horario(conn=conn, ahora=None)

    filas = conn.execute(
        "SELECT inicio FROM horario_generado ORDER BY inicio").fetchall()
    assert filas, "debió agendar la tarea"
    primer_inicio = datetime.strptime(filas[0]["inicio"], "%Y-%m-%d %H:%M:%S")
    # El motor redondea a minutos; el primer bloque debe empezar a lo más
    # un par de minutos después de ahora (en hora de Perú).
    diff = (primer_inicio - hoy_lima.replace(second=0, microsecond=0)).total_seconds()
    assert -60 <= diff <= 180, f"primer bloque a {primer_inicio}, ahora Lima {hoy_lima}"
    conn.close()
