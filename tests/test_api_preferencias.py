"""Tests de la API de preferencias (tabla clave-valor persistente)."""

from datetime import datetime, timedelta

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


def _dia(delta=0):
    fecha = datetime.now() + timedelta(days=delta)
    return fecha.strftime("%Y-%m-%d")


def test_preferencias_empiezan_vacias(cliente_logueado):
    respuesta = cliente_logueado.get("/api/preferencias")
    assert respuesta.status_code == 200
    assert respuesta.json() == {}


def test_guardar_y_leer_preferencias(cliente_logueado):
    hoy = _dia()
    semana = _dia(6)
    respuesta = cliente_logueado.put(
        "/api/preferencias",
        json={"tema": "oscuro", "inicio_visible": hoy,
              "fin_visible": semana},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "tema": "oscuro", "inicio_visible": hoy, "fin_visible": semana,
    }

    # La lectura devuelve lo mismo
    leido = cliente_logueado.get("/api/preferencias")
    assert leido.status_code == 200
    assert leido.json()["tema"] == "oscuro"


def test_actualizar_una_sola_preferencia_conserva_el_resto(cliente_logueado):
    cliente_logueado.put(
        "/api/preferencias",
        json={"tema": "oscuro", "inicio_visible": _dia()},
    )
    respuesta = cliente_logueado.put(
        "/api/preferencias", json={"tema": "claro"},
    )
    assert respuesta.status_code == 200
    estado = respuesta.json()
    assert estado["tema"] == "claro"
    assert estado["inicio_visible"] == _dia()


def test_tema_invalido_se_rechaza(cliente_logueado):
    respuesta = cliente_logueado.put(
        "/api/preferencias", json={"tema": "azul"},
    )
    assert respuesta.status_code == 422
    assert "tema" in respuesta.json()["detail"]


def test_fecha_invalida_se_rechaza(cliente_logueado):
    respuesta = cliente_logueado.put(
        "/api/preferencias", json={"inicio_visible": "16/08/2026"},
    )
    assert respuesta.status_code == 422


def test_clave_desconocida_se_rechaza(cliente_logueado):
    respuesta = cliente_logueado.put(
        "/api/preferencias", json={"tamano_letra": "grande"},
    )
    assert respuesta.status_code == 422


def test_rango_invertido_se_rechaza(cliente_logueado):
    respuesta = cliente_logueado.put(
        "/api/preferencias",
        json={"inicio_visible": _dia(6), "fin_visible": _dia()},
    )
    assert respuesta.status_code == 422


def test_requiere_login(cliente):
    assert cliente.get("/api/preferencias").status_code == 401
    assert cliente.put("/api/preferencias", json={"tema": "claro"}).status_code == 401
