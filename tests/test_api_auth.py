"""Tests del login y la protección de rutas."""

CLAVE = "clave-de-prueba"


def test_login_clave_incorrecta_rechazada(cliente):
    respuesta = cliente.post("/api/auth/login", json={"password": "clave-mala"})
    assert respuesta.status_code == 401


def test_login_clave_correcta_emite_cookie(cliente):
    respuesta = cliente.post("/api/auth/login", json={"password": CLAVE})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert "gestor_session" in respuesta.cookies


def test_me_sin_sesion(cliente):
    respuesta = cliente.get("/api/auth/me")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"autenticado": False}


def test_me_con_sesion(cliente_logueado):
    respuesta = cliente_logueado.get("/api/auth/me")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"autenticado": True}


def test_rutas_protegidas_sin_sesion_devuelven_401(cliente):
    for ruta in ("/api/tareas", "/api/horario/bloques", "/api/auth/protegido"):
        assert cliente.get(ruta).status_code == 401, ruta


def test_rutas_protegidas_con_sesion(cliente_logueado):
    for ruta in ("/api/tareas", "/api/horario/bloques", "/api/auth/protegido"):
        assert cliente_logueado.get(ruta).status_code == 200, ruta


def test_logout_invalida_la_sesion(cliente_logueado):
    respuesta = cliente_logueado.post("/api/auth/logout")
    assert respuesta.status_code == 200
    # La cookie queda sin valor válido: las rutas protegidas vuelven a pedir login
    assert cliente_logueado.get("/api/auth/me").json() == {"autenticado": False}
