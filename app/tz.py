"""Reloj de la aplicación.

La app trabaja con fechas naive 'YYYY-MM-DD HH:MM:SS' en hora local del
usuario (Perú, UTC-5 fijo, sin horario de verano). En un servidor remoto
(Render y similares) el sistema corre en UTC, y datetime.now() devolvería
una hora 5 horas adelantada: por eso TODO el código que necesita «ahora»
debe pasar por aquí.

El offset se puede cambiar con la variable de entorno APP_UTC_OFFSET
(horas, entero; por defecto -5 para Perú).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


def _offset_horas() -> int:
    try:
        return int(os.getenv("APP_UTC_OFFSET", "-5"))
    except ValueError:
        return -5


def zona_local() -> timezone:
    """Zona horaria local de la app (timezone fija, sin DST)."""
    return timezone(timedelta(hours=_offset_horas()), name="LOCAL")


def ahora_local() -> datetime:
    """«Ahora» en hora local de la app, como datetime naive.

    El resto del código y la base de datos usan datetime naive con hora
    local, así que se devuelve sin tzinfo. Da el mismo resultado en la PC
    del usuario y en cualquier servidor remoto, sin depender de la zona
    horaria del sistema.
    """
    return datetime.now(zona_local()).replace(tzinfo=None)
