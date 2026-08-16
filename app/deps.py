"""Dependencias de FastAPI (protección de rutas)."""

from __future__ import annotations

from fastapi import Cookie, HTTPException, status

from .security import COOKIE_NAME, validar_token


def requiere_login(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> str:
    """Dependencia: exige cookie de sesión válida; lanza 401 en caso contrario."""
    if not token or not validar_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
        )
    return token
