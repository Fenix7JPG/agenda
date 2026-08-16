"""Endpoints de autenticación (login simple por contraseña)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..deps import requiere_login
from ..schemas import LoginRequest, MeResponse
from ..security import (
    COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    crear_token_sesion,
    validar_token,
    verificar_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_FLAGS = {
    "httponly": True,
    "samesite": "lax",
    "max_age": SESSION_MAX_AGE_SECONDS,
}


@router.post("/login")
def login(datos: LoginRequest, response: Response) -> dict:
    """Valida la contraseña y emite la cookie de sesión."""
    if not verificar_password(datos.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta",
        )
    response.set_cookie(COOKIE_NAME, crear_token_sesion(), **COOKIE_FLAGS)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    token = request.cookies.get(COOKIE_NAME)
    autenticado = bool(token and validar_token(token))
    return MeResponse(autenticado=autenticado)


@router.get("/protegido")
def protegido(_token: str = Depends(requiere_login)) -> dict:
    """Ruta de verificación: solo responde con sesión válida."""
    return {"ok": True}
