"""Endpoints de preferencias del usuario (protegidos por sesión)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, status

from ..deps import requiere_login
from ..services import preferencias_service

router = APIRouter(prefix="/api/preferencias", tags=["preferencias"])


@router.get("")
def leer(_token: str = Depends(requiere_login)) -> dict[str, str]:
    """Devuelve las preferencias guardadas como diccionario clave-valor."""
    return preferencias_service.leer()


@router.put("")
def guardar(
    datos: dict[str, str] = Body(...),
    _token: str = Depends(requiere_login),
) -> dict[str, str]:
    """Guarda (o actualiza) preferencias y devuelve el estado completo.

    Claves aceptadas: tema (claro|oscuro), inicio_visible y fin_visible
    (fechas AAAA-MM-DD que marcan los anillos verde y rojo de la vista).
    """
    try:
        return preferencias_service.guardar(datos)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        )
