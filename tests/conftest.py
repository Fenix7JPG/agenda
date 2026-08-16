"""Configuración común de los tests de la API.

Aísla la base de datos en un archivo temporal ANTES de importar la app,
de modo que los tests nunca toquen la base real ni la de desarrollo.
"""

import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="gestor_tests_")
os.environ["DB_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ["DB_MODE"] = "local"
os.environ["APP_PASSWORD"] = "clave-de-prueba"
os.environ.pop("TURSO_URL", None)
os.environ.pop("TURSO_AUTH_TOKEN", None)
os.environ["SECRET_KEY"] = "secret-de-prueba-solo-tests"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

CLAVE = "clave-de-prueba"


@pytest.fixture(autouse=True)
def limpiar_bd():
    """Deja las tablas vacías antes de cada test."""
    from app.db import db

    db.init_schema()
    for tabla in ("horario_generado", "tareas_no_programadas", "tareas"):
        db.conn.execute(f"DELETE FROM {tabla}")
    db.commit()
    db.close()
    yield
    db.close()


@pytest.fixture()
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def cliente_logueado(cliente):
    respuesta = cliente.post("/api/auth/login", json={"password": CLAVE})
    assert respuesta.status_code == 200, respuesta.text
    return cliente
