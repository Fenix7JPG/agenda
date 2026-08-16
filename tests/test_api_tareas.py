"""Tests del CRUD de tareas vía API."""

from datetime import datetime, timedelta

from app.schemas import FORMATO_FECHA


def _fechas_futuras(horas_ventana: int = 2):
    inicio = datetime.now() + timedelta(days=2)
    fin = inicio + timedelta(hours=horas_ventana)
    return inicio.strftime(FORMATO_FECHA), fin.strftime(FORMATO_FECHA)


def _tarea_valida(**cambios):
    inicio, fin = _fechas_futuras()
    datos = {
        "titulo": "Estudiar cálculo",
        "descripcion": "Repasar derivadas",
        "estado": "pendiente",
        "prioridad": 2,
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "duracion_min": 90,
        "bloque_entero": True,
        "es_recurrente": False,
    }
    datos.update(cambios)
    return datos


def test_crear_tarea(cliente_logueado):
    respuesta = cliente_logueado.post("/api/tareas", json=_tarea_valida())
    assert respuesta.status_code == 201, respuesta.text
    tarea = respuesta.json()
    assert tarea["id"] > 0
    assert tarea["titulo"] == "Estudiar cálculo"
    assert tarea["prioridad"] == 2
    assert tarea["bloque_entero"] is True


def test_crear_tarea_rechaza_fecha_fin_anterior(cliente_logueado):
    inicio, fin = _fechas_futuras()
    datos = _tarea_valida(fecha_inicio=fin, fecha_fin=inicio)
    respuesta = cliente_logueado.post("/api/tareas", json=datos)
    assert respuesta.status_code == 422


def test_crear_tarea_recurrente_exige_recurrencia(cliente_logueado):
    datos = _tarea_valida(es_recurrente=True)
    respuesta = cliente_logueado.post("/api/tareas", json=datos)
    assert respuesta.status_code == 422
    assert "recurrente" in respuesta.json()["detail"].lower()


def test_listar_y_obtener(cliente_logueado):
    creada = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()

    lista = cliente_logueado.get("/api/tareas").json()
    assert any(t["id"] == creada["id"] for t in lista)

    obtenida = cliente_logueado.get(f"/api/tareas/{creada['id']}")
    assert obtenida.status_code == 200
    assert obtenida.json()["titulo"] == "Estudiar cálculo"

    assert cliente_logueado.get("/api/tareas/99999").status_code == 404


def test_actualizar_tarea_parcial(cliente_logueado):
    creada = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()

    respuesta = cliente_logueado.patch(
        f"/api/tareas/{creada['id']}",
        json={"titulo": "Nuevo título", "prioridad": 5},
    )
    assert respuesta.status_code == 200
    tarea = respuesta.json()
    assert tarea["titulo"] == "Nuevo título"
    assert tarea["prioridad"] == 5
    # Lo no enviado se conserva
    assert tarea["descripcion"] == "Repasar derivadas"


def test_actualizar_tarea_completa(cliente_logueado):
    creada = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()
    datos = _tarea_valida(titulo="Versión 2", duracion_min=120)
    respuesta = cliente_logueado.put(f"/api/tareas/{creada['id']}", json=datos)
    assert respuesta.status_code == 200
    tarea = respuesta.json()
    assert tarea["titulo"] == "Versión 2"
    assert tarea["duracion_min"] == 120


def test_cambiar_estado(cliente_logueado):
    from app.db import db

    def insertar_bloque(tarea_id, inicio, fin):
        db.conn.execute(
            "INSERT INTO horario_generado "
            "(tarea_id, inicio, fin, completado, fijado) VALUES (?, ?, ?, 0, 0)",
            (tarea_id, inicio.strftime(FORMATO_FECHA), fin.strftime(FORMATO_FECHA)),
        )
        db.commit()

    # Una tarea cuyo bloque asignado aún no termina no se puede completar,
    # aunque su ventana de asignación sea amplia.
    creada = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()
    insertar_bloque(
        creada["id"], datetime.now() + timedelta(hours=1), datetime.now() + timedelta(hours=3)
    )
    respuesta = cliente_logueado.post(
        f"/api/tareas/{creada['id']}/estado", json={"estado": "completada"}
    )
    assert respuesta.status_code == 422

    # Una tarea sin horario asignado tampoco se puede completar.
    sin_bloque = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()
    respuesta = cliente_logueado.post(
        f"/api/tareas/{sin_bloque['id']}/estado", json={"estado": "completada"}
    )
    assert respuesta.status_code == 422

    # Una tarea cuyo bloque asignado ya pasó por completo sí se puede completar.
    inicio_viejo = datetime.now() - timedelta(days=2)
    fin_viejo = inicio_viejo + timedelta(hours=2)
    pasada = cliente_logueado.post(
        "/api/tareas",
        json=_tarea_valida(
            fecha_inicio=inicio_viejo.strftime(FORMATO_FECHA),
            fecha_fin=fin_viejo.strftime(FORMATO_FECHA),
        ),
    ).json()
    insertar_bloque(pasada["id"], inicio_viejo, fin_viejo)
    respuesta = cliente_logueado.post(
        f"/api/tareas/{pasada['id']}/estado", json={"estado": "completada"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "completada"

    filtradas = cliente_logueado.get("/api/tareas", params={"estado": "completada"}).json()
    assert [t for t in filtradas if t["id"] == pasada["id"]]

    # Reactivar (completada -> pendiente) sigue permitido.
    respuesta = cliente_logueado.post(
        f"/api/tareas/{pasada['id']}/estado", json={"estado": "pendiente"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "pendiente"


def test_eliminar_tarea_y_cascada(cliente_logueado):
    creada = cliente_logueado.post("/api/tareas", json=_tarea_valida()).json()
    respuesta = cliente_logueado.delete(f"/api/tareas/{creada['id']}")
    assert respuesta.status_code == 204
    assert cliente_logueado.get(f"/api/tareas/{creada['id']}").status_code == 404
