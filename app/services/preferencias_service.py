"""Preferencias del usuario (tema y visualización del horario).

Se guardan en la tabla `preferencias` como pares clave-valor, así persisten
entre sesiones y dispositivos (no dependen de localStorage del navegador).
"""
from __future__ import annotations

from datetime import datetime

from ..db import db
from ..tz import ahora_local

FORMATO_FECHA = "%Y-%m-%d"
CLAVES_PERMITIDAS = {"tema", "inicio_visible", "fin_visible"}


def _validar(clave: str, valor: str) -> str | None:
    """Devuelve un mensaje de error si el valor no es válido, o None."""
    if clave == "tema" and valor not in ("claro", "oscuro"):
        return "El tema debe ser 'claro' u 'oscuro'"
    if clave in ("inicio_visible", "fin_visible"):
        try:
            datetime.strptime(valor, FORMATO_FECHA)
        except ValueError:
            return f"{clave} debe ser una fecha AAAA-MM-DD"
    return None


def leer() -> dict[str, str]:
    """Devuelve todas las preferencias guardadas."""
    filas = db.fetch_all("SELECT clave, valor FROM preferencias")
    return {fila["clave"]: fila["valor"] for fila in filas}


def guardar(datos: dict[str, str]) -> dict[str, str]:
    """Guarda (o actualiza) las preferencias indicadas y devuelve el estado
    completo. Solo acepta claves conocidas y valores válidos."""
    for clave, valor in datos.items():
        if clave not in CLAVES_PERMITIDAS:
            raise ValueError(f"Preferencia desconocida: {clave}")
        error = _validar(clave, valor)
        if error:
            raise ValueError(error)

    # El rango visible debe ser coherente: inicio anterior al fin
    actuales = leer()
    ini = datos.get("inicio_visible", actuales.get("inicio_visible"))
    fin = datos.get("fin_visible", actuales.get("fin_visible"))
    if ini and fin and ini > fin:
        raise ValueError("El inicio de la vista no puede ser posterior al fin")

    ahora = ahora_local().strftime("%Y-%m-%d %H:%M:%S")
    for clave, valor in datos.items():
        db.conn.execute(
            "INSERT INTO preferencias (clave, valor, actualizado_en) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor, "
            "actualizado_en = excluded.actualizado_en",
            (clave, valor, ahora),
        )
    db.commit()
    return leer()
