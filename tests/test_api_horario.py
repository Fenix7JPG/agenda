"""Tests del horario: generación vía API, bloques y regla de descanso."""

from datetime import datetime, timedelta

from app.schemas import FORMATO_FECHA


def _tarea(titulo, duracion_min, *, ventana_min=240, bloque_entero=True,
           prioridad=3, **cambios):
    inicio = datetime.now() + timedelta(days=2)
    fin = inicio + timedelta(minutes=ventana_min)
    datos = {
        "titulo": titulo,
        "descripcion": "",
        "estado": "pendiente",
        "prioridad": prioridad,
        "fecha_inicio": inicio.strftime(FORMATO_FECHA),
        "fecha_fin": fin.strftime(FORMATO_FECHA),
        "duracion_min": duracion_min,
        "bloque_entero": bloque_entero,
        "es_recurrente": False,
    }
    datos.update(cambios)
    return datos


def test_generar_sin_tareas_no_inserta_nada(cliente_logueado):
    respuesta = cliente_logueado.post("/api/horario/generar")
    assert respuesta.status_code == 200
    resumen = respuesta.json()
    assert resumen["bloques_insertados"] == 0
    assert resumen["bloques_eliminados"] == 0
    assert resumen["no_programadas"] == 0


def test_generar_agenda_tarea_simple_y_lista_bloques(cliente_logueado):
    cliente_logueado.post("/api/tareas", json=_tarea("Leer capítulo", 60))

    respuesta = cliente_logueado.post("/api/horario/generar")
    assert respuesta.status_code == 200
    assert respuesta.json()["bloques_insertados"] == 1

    bloques = cliente_logueado.get("/api/horario/bloques").json()
    assert len(bloques) == 1
    assert bloques[0]["titulo"] == "Leer capítulo"
    assert bloques[0]["completado"] is False


def test_bloques_por_rango_de_fechas(cliente_logueado):
    cliente_logueado.post("/api/tareas", json=_tarea("Dentro del rango", 60))
    cliente_logueado.post("/api/horario/generar")

    inicio = datetime.now() + timedelta(days=1)
    fin = inicio + timedelta(days=10)
    bloques = cliente_logueado.get(
        "/api/horario/bloques",
        params={"inicio": inicio.strftime(FORMATO_FECHA),
                "fin": fin.strftime(FORMATO_FECHA)},
    ).json()
    assert any(b["titulo"] == "Dentro del rango" for b in bloques)

    # Rango en el pasado: no debe devolver nada
    pasado = datetime.now() - timedelta(days=30)
    vacio = cliente_logueado.get(
        "/api/horario/bloques",
        params={"inicio": pasado.strftime(FORMATO_FECHA),
                "fin": pasado.strftime(FORMATO_FECHA)},
    ).json()
    assert all(b["titulo"] != "Dentro del rango" for b in vacio)


def test_bloque_futuro_no_se_puede_completar(cliente_logueado):
    """Las actividades futuras no se pueden marcar como completadas."""
    cliente_logueado.post("/api/tareas", json=_tarea("Hacer informe", 60))
    cliente_logueado.post("/api/horario/generar")
    bloque_id = cliente_logueado.get("/api/horario/bloques").json()[0]["id"]

    respuesta = cliente_logueado.patch(
        f"/api/horario/bloques/{bloque_id}", json={"completado": True}
    )
    assert respuesta.status_code == 422
    assert "aún no ha terminado" in respuesta.json()["detail"]
    assert cliente_logueado.get("/api/horario/bloques").json()[0]["completado"] is False


def test_bloque_pasado_se_completa_se_desmarca_y_se_elimina(cliente_logueado):
    """Un bloque cuyo horario ya pasó sí se puede completar y desmarcar."""
    from app.db import db

    cliente_logueado.post("/api/tareas", json=_tarea("Pasado", 60))
    tarea_id = cliente_logueado.get("/api/tareas").json()[0]["id"]
    fin = datetime.now() - timedelta(hours=1)
    inicio = fin - timedelta(minutes=60)
    db.conn.execute(
        "INSERT INTO horario_generado (tarea_id, inicio, fin, completado, fijado) "
        "VALUES (?, ?, ?, 0, 0)",
        (tarea_id, inicio.strftime(FORMATO_FECHA), fin.strftime(FORMATO_FECHA)),
    )
    db.commit()
    bloque_id = cliente_logueado.get("/api/horario/bloques").json()[0]["id"]

    assert cliente_logueado.patch(
        f"/api/horario/bloques/{bloque_id}", json={"completado": True}
    ).status_code == 200
    assert cliente_logueado.get("/api/horario/bloques").json()[0]["completado"] is True

    # Desmarcar (volver a pendiente) se permite en cualquier momento
    assert cliente_logueado.patch(
        f"/api/horario/bloques/{bloque_id}", json={"completado": False}
    ).status_code == 200
    assert cliente_logueado.get("/api/horario/bloques").json()[0]["completado"] is False

    assert cliente_logueado.delete(f"/api/horario/bloques/{bloque_id}").status_code == 204
    assert cliente_logueado.get("/api/horario/bloques").json() == []
    assert cliente_logueado.patch(
        f"/api/horario/bloques/{bloque_id}", json={"completado": True}
    ).status_code == 404


def test_bloque_futuro_completado_se_puede_desmarcar(cliente_logueado):
    """Si un bloque futuro quedó completado (datos viejos), se puede revertir."""
    from app.db import db

    cliente_logueado.post("/api/tareas", json=_tarea("Futuro", 60))
    tarea_id = cliente_logueado.get("/api/tareas").json()[0]["id"]
    fin = datetime.now() + timedelta(hours=5)
    inicio = fin - timedelta(minutes=60)
    db.conn.execute(
        "INSERT INTO horario_generado (tarea_id, inicio, fin, completado, fijado) "
        "VALUES (?, ?, ?, 1, 0)",
        (tarea_id, inicio.strftime(FORMATO_FECHA), fin.strftime(FORMATO_FECHA)),
    )
    db.commit()
    bloque_id = cliente_logueado.get("/api/horario/bloques").json()[0]["id"]

    respuesta = cliente_logueado.patch(
        f"/api/horario/bloques/{bloque_id}", json={"completado": False}
    )
    assert respuesta.status_code == 200


def test_tarea_sin_hueco_queda_registrada_como_no_programada(cliente_logueado):
    # Tarea A ocupa toda la ventana futura; B (bloque entero) no cabe.
    cliente_logueado.post(
        "/api/tareas", json=_tarea("Ocupante", 240, ventana_min=240, prioridad=1)
    )
    cliente_logueado.post(
        "/api/tareas", json=_tarea("Sin hueco", 120, ventana_min=240, prioridad=2)
    )

    resumen = cliente_logueado.post("/api/horario/generar").json()
    assert resumen["no_programadas"] >= 1

    no_programadas = cliente_logueado.get("/api/tareas/no-programadas").json()
    titulos = [n["titulo"] for n in no_programadas]
    assert "Sin hueco" in titulos


def test_regla_descanso_no_rompe_ventana_ajustada(cliente_logueado):
    """Porte end-to-end de test_tarea_con_ventana_ajustada del motor:
    una tarea flexible de 200 min en una ventana de exactamente 200 min se
    agenda en bloques consecutivos SIN descansos intercalados."""
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Tarea ajustada", 200, ventana_min=200, bloque_entero=False),
    )
    cliente_logueado.post("/api/horario/generar")

    bloques = cliente_logueado.get("/api/horario/bloques").json()
    assert len(bloques) == 3
    for anterior, siguiente in zip(bloques, bloques[1:]):
        assert anterior["fin"] == siguiente["inicio"]


def test_regla_descanso_tras_bloque_largo(cliente_logueado):
    """Tras un bloque de 90 min de una tarea, la siguiente tarea distinta
    empieza 10 min después (descanso reservado)."""
    tarea_a = cliente_logueado.post(
        "/api/tareas",
        json=_tarea("A", 90, ventana_min=120, bloque_entero=False, prioridad=1),
    ).json()
    # B comparte el mismo inicio de ventana que A
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("B", 30, ventana_min=240, bloque_entero=False, prioridad=2),
    )
    cliente_logueado.post("/api/horario/generar")

    bloques = cliente_logueado.get("/api/horario/bloques").json()
    bloques_a = [b for b in bloques if b["tarea_id"] == tarea_a["id"]]
    bloques_b = [b for b in bloques if b["titulo"] == "B"]
    assert len(bloques_a) == 1 and len(bloques_b) == 1

    fin_a = datetime.strptime(bloques_a[0]["fin"], FORMATO_FECHA)
    inicio_b = datetime.strptime(bloques_b[0]["inicio"], FORMATO_FECHA)
    assert (inicio_b - fin_a).total_seconds() == 600  # 10 minutos exactos


# ---------------------------------------------------------------------------
# Mover bloques (gestión manual del horario)
# ---------------------------------------------------------------------------

def _ventana_futura(horas=10, dias=2):
    inicio = (datetime.now() + timedelta(days=dias)).replace(
        hour=8, minute=0, second=0, microsecond=0)
    return inicio, inicio + timedelta(hours=horas)


def test_mover_bloque_reubica_marca_fijado_y_sobrevive(cliente_logueado):
    inicio_v, fin_v = _ventana_futura()
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Móvil", 60,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post("/api/horario/generar")
    bloque = cliente_logueado.get("/api/horario/bloques").json()[0]

    destino = (inicio_v + timedelta(hours=7)).strftime(FORMATO_FECHA)
    respuesta = cliente_logueado.put(
        f"/api/horario/bloques/{bloque['id']}/mover", json={"inicio": destino})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["inicio"] == destino
    assert cuerpo["fijado"] is True
    assert cuerpo["es_recurrente"] is False

    # La regeneración no lo reubica ni duplica su tiempo
    cliente_logueado.post("/api/horario/generar")
    bloques = cliente_logueado.get("/api/horario/bloques").json()
    movidos = [b for b in bloques if b["id"] == bloque["id"]]
    assert len(movidos) == 1
    assert movidos[0]["inicio"] == destino
    assert movidos[0]["fijado"] is True
    # No se agendó otro bloque para la misma tarea
    assert sum(1 for b in bloques if b["tarea_id"] == bloque["tarea_id"]) == 1


def test_mover_bloque_recurrente_dentro_de_su_ventana(cliente_logueado):
    """Un recurrente con ventana ancha sí se mueve y queda fijado."""
    inicio_v = datetime.now() + timedelta(days=2)
    fin_v = inicio_v + timedelta(days=3)  # ventana ancha de 3 días
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Repaso semanal", 30, bloque_entero=True, es_recurrente=True,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA),
                    recurrencia_min=1440,
                    recurrencia_inicio=inicio_v.strftime(FORMATO_FECHA),
                    recurrencia_fin=(inicio_v + timedelta(minutes=1)).strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post("/api/horario/generar")
    recurrentes = [b for b in cliente_logueado.get("/api/horario/bloques").json()
                   if b["es_recurrente"]]
    assert recurrentes, "debe haber bloques recurrentes generados"
    bloque = recurrentes[0]

    destino = (inicio_v + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0)
    respuesta = cliente_logueado.put(
        f"/api/horario/bloques/{bloque['id']}/mover",
        json={"inicio": destino.strftime(FORMATO_FECHA)})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["inicio"] == destino.strftime(FORMATO_FECHA)
    assert cuerpo["fijado"] is True
    assert cuerpo["es_recurrente"] is True

    # La regeneración no lo reubica ni duplica su tiempo
    cliente_logueado.post("/api/horario/generar")
    bloques = cliente_logueado.get("/api/horario/bloques").json()
    de_la_tarea = [b for b in bloques if b["tarea_id"] == bloque["tarea_id"]]
    assert len(de_la_tarea) == 1
    assert de_la_tarea[0]["inicio"] == destino.strftime(FORMATO_FECHA)
    assert de_la_tarea[0]["fijado"] is True


def test_mover_bloque_recurrente_fuera_de_ventana_devuelve_409(cliente_logueado):
    """Un recurrente con ventana exacta (sin holgura) no se puede posponer."""
    inicio_v = datetime.now() + timedelta(days=2)
    fin_v = inicio_v + timedelta(minutes=45)  # ventana exacta, como una clase
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Clase de prueba", 45, bloque_entero=True, es_recurrente=True,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA),
                    recurrencia_min=1440,
                    recurrencia_inicio=inicio_v.strftime(FORMATO_FECHA),
                    recurrencia_fin=(inicio_v + timedelta(minutes=1)).strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post("/api/horario/generar")
    recurrentes = [b for b in cliente_logueado.get("/api/horario/bloques").json()
                   if b["es_recurrente"]]
    assert recurrentes, "debe haber bloques recurrentes generados"

    destino = (inicio_v + timedelta(hours=2)).strftime(FORMATO_FECHA)
    respuesta = cliente_logueado.put(
        f"/api/horario/bloques/{recurrentes[0]['id']}/mover",
        json={"inicio": destino})
    assert respuesta.status_code == 409
    assert "ventana" in respuesta.json()["detail"].lower()


def test_ventana_efectiva_recurrente_se_desplaza_con_la_ocurrencia():
    """La ventana de un recurrente de la semana 2 es la de su ocurrencia."""
    from app.services import horario_service

    # Como un Post-estudio real: ventana de la tarea en la semana 1 y el
    # bloque en la ocurrencia de la semana 2 (7 días después).
    v_ini, v_fin = horario_service._ventana_efectiva(
        "2026-08-17 21:30:00", True,
        "2026-08-10 10:00:00", "2026-08-17 09:15:00",
        "2026-08-10 10:00:00", 10080,
    )
    assert v_ini == "2026-08-17 10:00:00"
    assert v_fin == "2026-08-24 09:15:00"

    # Ocurrencia 1: coincide con la ventana de la tarea
    v_ini, v_fin = horario_service._ventana_efectiva(
        "2026-08-10 20:00:00", True,
        "2026-08-10 10:00:00", "2026-08-17 09:15:00",
        "2026-08-10 10:00:00", 10080,
    )
    assert v_ini == "2026-08-10 10:00:00"
    assert v_fin == "2026-08-17 09:15:00"

    # No recurrente: su ventana es la de la tarea tal cual
    v_ini, v_fin = horario_service._ventana_efectiva(
        "2026-08-12 12:00:00", False,
        "2026-08-10 10:00:00", "2026-08-17 09:15:00",
        None, None,
    )
    assert (v_ini, v_fin) == ("2026-08-10 10:00:00", "2026-08-17 09:15:00")


def test_mover_bloque_a_hueco_ocupado_devuelve_409(cliente_logueado):
    inicio_v, fin_v = _ventana_futura()
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("A", 60, prioridad=1,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("B", 60, prioridad=2,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post("/api/horario/generar")
    bloques = cliente_logueado.get("/api/horario/bloques").json()
    bloque_a = next(b for b in bloques if b["titulo"] == "A")
    bloque_b = next(b for b in bloques if b["titulo"] == "B")

    respuesta = cliente_logueado.put(
        f"/api/horario/bloques/{bloque_a['id']}/mover",
        json={"inicio": bloque_b["inicio"]})
    assert respuesta.status_code == 409
    assert "solap" in respuesta.json()["detail"].lower() or \
           "otro bloque" in respuesta.json()["detail"].lower()


def test_mover_bloque_no_existente_devuelve_404(cliente_logueado):
    destino = (datetime.now() + timedelta(days=2)).replace(
        hour=9, minute=0, second=0, microsecond=0).strftime(FORMATO_FECHA)
    respuesta = cliente_logueado.put(
        "/api/horario/bloques/999999/mover", json={"inicio": destino})
    assert respuesta.status_code == 404


def test_mover_bloque_al_pasado_devuelve_400(cliente_logueado):
    inicio_v, fin_v = _ventana_futura()
    cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Pasado", 60,
                    fecha_inicio=inicio_v.strftime(FORMATO_FECHA),
                    fecha_fin=fin_v.strftime(FORMATO_FECHA)),
    )
    cliente_logueado.post("/api/horario/generar")
    bloque = cliente_logueado.get("/api/horario/bloques").json()[0]
    destino = (datetime.now() - timedelta(days=1)).strftime(FORMATO_FECHA)
    respuesta = cliente_logueado.put(
        f"/api/horario/bloques/{bloque['id']}/mover", json={"inicio": destino})
    assert respuesta.status_code == 400


def test_generar_reorganiza_tareas_no_recurrentes_vencidas(cliente_logueado):
    """Una pendiente no recurrente que vive en el pasado se reubica a partir
    de ahora conservando la duración de su ventana, y se le agenda bloque."""
    inicio_viejo = datetime.now() - timedelta(days=3)
    fin_viejo = inicio_viejo + timedelta(hours=4)
    antes = datetime.now() - timedelta(minutes=1)
    creada = cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Atrasada", 60,
                    fecha_inicio=inicio_viejo.strftime(FORMATO_FECHA),
                    fecha_fin=fin_viejo.strftime(FORMATO_FECHA)),
    ).json()

    respuesta = cliente_logueado.post("/api/horario/generar")
    assert respuesta.status_code == 200
    resumen = respuesta.json()
    assert resumen["tareas_reorganizadas"] == 1
    assert "reorganizadas" in resumen["mensaje"]

    tarea = cliente_logueado.get(f"/api/tareas/{creada['id']}").json()
    nuevo_inicio = datetime.strptime(tarea["fecha_inicio"], FORMATO_FECHA)
    nuevo_fin = datetime.strptime(tarea["fecha_fin"], FORMATO_FECHA)
    assert nuevo_inicio >= antes
    assert (nuevo_fin - nuevo_inicio) == (fin_viejo - inicio_viejo)
    assert tarea["estado"] == "pendiente"

    bloques = cliente_logueado.get("/api/horario/bloques").json()
    assert any(b["titulo"] == "Atrasada" for b in bloques)


def test_generar_no_reorganiza_completadas_ni_recurrentes(cliente_logueado):
    """Las completadas y las recurrentes pendientes no se tocan al generar."""
    inicio_viejo = datetime.now() - timedelta(days=3)
    fin_viejo = inicio_viejo + timedelta(hours=2)
    completada = cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Hecha", 30, estado="completada",
                    fecha_inicio=inicio_viejo.strftime(FORMATO_FECHA),
                    fecha_fin=fin_viejo.strftime(FORMATO_FECHA)),
    ).json()
    recurrente = cliente_logueado.post(
        "/api/tareas",
        json=_tarea("Rutina", 30,
                    fecha_inicio=inicio_viejo.strftime(FORMATO_FECHA),
                    fecha_fin=fin_viejo.strftime(FORMATO_FECHA),
                    es_recurrente=True, recurrencia_min=1440,
                    recurrencia_inicio=(datetime.now() - timedelta(days=1))
                    .strftime(FORMATO_FECHA),
                    recurrencia_fin=(datetime.now() + timedelta(days=7))
                    .strftime(FORMATO_FECHA)),
    ).json()

    resumen = cliente_logueado.post("/api/horario/generar").json()
    assert resumen["tareas_reorganizadas"] == 0

    for tarea_id in (completada["id"], recurrente["id"]):
        tarea = cliente_logueado.get(f"/api/tareas/{tarea_id}").json()
        assert tarea["fecha_inicio"] == inicio_viejo.strftime(FORMATO_FECHA)
        assert tarea["fecha_fin"] == fin_viejo.strftime(FORMATO_FECHA)


# ------------------------------ PDF ------------------------------

def _texto_pdf(datos: bytes) -> bytes:
    """Descomprime los streams del PDF para poder verificar su contenido.

    reportlab 5 escribe los streams como ASCII85 + Flate: primero se
    decodifica ASCII85 y después zlib.
    """
    import base64
    import re
    import zlib

    salida = []
    for m in re.finditer(rb"/Length\s+(\d+)", datos):
        n = int(m.group(1))
        idx = datos.find(b"stream", m.end())
        if idx < 0:
            continue
        ini = idx + 6
        if datos[ini:ini + 2] == b"\r\n":
            ini += 2
        elif datos[ini:ini + 1] == b"\n":
            ini += 1
        cuerpo = datos[ini:ini + n]
        try:
            salida.append(zlib.decompress(base64.a85decode(cuerpo, adobe=True)))
        except Exception:
            try:
                salida.append(zlib.decompress(cuerpo))
            except Exception:
                salida.append(cuerpo)
    return b"\n".join(salida)


def _rango_pdf(dias: int = 7) -> tuple[str, str]:
    """Rango de `dias` días a partir de mañana (para que haya bloques)."""
    inicio = datetime.now() + timedelta(days=1)
    fin = inicio + timedelta(days=dias)
    return inicio.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")


def test_pdf_exige_login(cliente):
    inicio, fin = _rango_pdf()
    respuesta = cliente.get("/api/horario/pdf", params={"inicio": inicio, "fin": fin})
    assert respuesta.status_code == 401


def test_pdf_falta_el_rango(cliente_logueado):
    assert cliente_logueado.get("/api/horario/pdf").status_code == 400
    respuesta = cliente_logueado.get("/api/horario/pdf", params={"inicio": "2026-08-10"})
    assert respuesta.status_code == 400


def test_pdf_rechaza_rango_invertido_o_enorme(cliente_logueado):
    invertido = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": "2026-08-20", "fin": "2026-08-10"}
    )
    assert invertido.status_code == 400
    enorme = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": "2026-08-01", "fin": "2026-09-01"}
    )
    assert enorme.status_code == 400


def test_pdf_acepta_fechas_con_hora_como_el_frontend(cliente_logueado):
    """El frontend a veces envía 'AAAA-MM-DD HH:MM:SS'; debe aceptarse."""
    inicio, fin = _rango_pdf()
    respuesta = cliente_logueado.get(
        "/api/horario/pdf",
        params={"inicio": inicio + " 00:00:00", "fin": fin + " 00:00:00"},
    )
    assert respuesta.status_code == 200
    assert respuesta.content[:5] == b"%PDF-"
    assert "horario_" in respuesta.headers["content-disposition"]
    assert ":" not in respuesta.headers["content-disposition"].split("filename=")[1]


def test_pdf_vacio_es_una_sola_hoja(cliente_logueado):
    import re

    inicio, fin = _rango_pdf()
    respuesta = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": inicio, "fin": fin}
    )
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "application/pdf"
    assert "attachment" in respuesta.headers["content-disposition"]
    assert respuesta.content[:5] == b"%PDF-"
    assert len(re.findall(rb"/Type\s*/Page[^s]", respuesta.content)) == 1
    assert b"Sin actividades en este rango" in _texto_pdf(respuesta.content)


def test_pdf_es_lamina_grande_estilo_infografia(cliente_logueado):
    """La hoja no es A4: es más grande y con letra de 12 pt para los títulos."""
    import re

    inicio, fin = _rango_pdf()
    datos = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": inicio, "fin": fin}
    ).content

    media = re.search(rb"/MediaBox\s*\[([^\]]+)\]", datos)
    assert media, "falta el MediaBox"
    numeros = [float(x) for x in media.group(1).split()]
    ancho, alto = numeros[2], numeros[3]
    # Bastante mayor que un A4 horizontal (842 x 595 pt)
    assert ancho * alto > 842 * 595 * 1.3, (ancho, alto)
    # Alto generoso para que los bloques no se solapen: al menos 60 pt por hora
    assert alto >= 24 * 60, (ancho, alto)

    texto = _texto_pdf(datos)
    tamanyos = [float(x) for x in re.findall(rb"([\d.]+)\s+Tf", texto)]
    assert max(tamanyos, default=0) >= 12, "la letra del título debe ser de 12 pt o más"


def test_pdf_columna_izquierda_muestra_horas(cliente_logueado):
    """La columna izquierda muestra horas '00:00'..'23:00', no números en orden."""
    inicio, fin = _rango_pdf()
    datos = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": inicio, "fin": fin}
    ).content
    texto = _texto_pdf(datos)
    assert b"HORA" in texto
    assert b"00:00" in texto
    assert b"12:00" in texto
    assert b"23:00" in texto


def test_pdf_titulo_largo_en_bloque_corto_cabe_dentro():
    """El título largo en mayúsculas cabe completo en su bloque de 45 min."""
    from app.services import pdf_horario

    titulo = "ARGUMENTACIÓN Y PENSAMIENTO CRÍTICO (TSM - 601)"
    ancho_texto = pdf_horario.ANCHO_COL_DIA - 9
    lineas = pdf_horario._envolver(titulo, "Helvetica-Bold", pdf_horario.TAM_TITULO, ancho_texto)
    interlinea = 1.2 * pdf_horario.TAM_TITULO
    alto_bloque = (45 / 60) * pdf_horario.ALTO_HORA  # bloque de 45 minutos
    # Las líneas del título caben holgadas dentro del bloque
    assert len(lineas) * interlinea <= alto_bloque - 3, (lineas, alto_bloque)


def test_pdf_incluye_titulo_completo_con_acentos(cliente_logueado):
    titulo = "Preparar presentación final de Sistemas"
    cliente_logueado.post("/api/tareas", json=_tarea(titulo, 60))
    cliente_logueado.post("/api/horario/generar")

    inicio, fin = _rango_pdf()
    respuesta = cliente_logueado.get(
        "/api/horario/pdf", params={"inicio": inicio, "fin": fin}
    )
    assert respuesta.status_code == 200
    texto = _texto_pdf(respuesta.content)
    # Los acentos se escriben escapados en octal dentro del stream (\363 = ó).
    assert b"Preparar presentaci" in texto
    assert b"\\363n" in texto
    assert b"final de Sistemas" in texto
    assert b"HORARIO GENERADO" in texto

