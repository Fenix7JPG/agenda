"""Endpoints CRUD de tareas (protegidos por sesión)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import requiere_login
from ..schemas import TareaCreate, TareaEstadoUpdate, TareaOut, TareaUpdate
from ..services import tareas_service
from ..services.tareas_service import ErrorNegocio

router = APIRouter(prefix="/api/tareas", tags=["tareas"])


@router.get("/no-programadas", response_model=list[dict])
def listar_no_programadas(_token: str = Depends(requiere_login)) -> list[dict]:
    """Tareas que el motor no pudo acomodar en el último intento."""
    return tareas_service.listar_no_programadas()


@router.get("", response_model=list[TareaOut])
def listar(
    estado: str | None = Query(default=None),
    _token: str = Depends(requiere_login),
) -> list[TareaOut]:
    return tareas_service.listar(estado)


@router.post("", response_model=TareaOut, status_code=status.HTTP_201_CREATED)
def crear(datos: TareaCreate, _token: str = Depends(requiere_login)) -> TareaOut:
    try:
        tarea = tareas_service.crear(datos)
    except ErrorNegocio as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return tarea


@router.get("/{tarea_id}", response_model=TareaOut)
def obtener(tarea_id: int, _token: str = Depends(requiere_login)) -> TareaOut:
    tarea = tareas_service.obtener(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    return tarea


@router.put("/{tarea_id}", response_model=TareaOut)
def actualizar(
    tarea_id: int, datos: TareaCreate, _token: str = Depends(requiere_login)
) -> TareaOut:
    """Actualización completa de la tarea."""
    tarea = tareas_service.obtener(tarea_id)
    if tarea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    cambios = TareaUpdate(**datos.model_dump())
    return tareas_service.actualizar(tarea_id, cambios)


@router.patch("/{tarea_id}", response_model=TareaOut)
def actualizar_parcial(
    tarea_id: int, datos: TareaUpdate, _token: str = Depends(requiere_login)
) -> TareaOut:
    tarea = tareas_service.actualizar(tarea_id, datos)
    if tarea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    return tarea


@router.post("/{tarea_id}/estado", response_model=TareaOut)
def cambiar_estado(
    tarea_id: int, datos: TareaEstadoUpdate, _token: str = Depends(requiere_login)
) -> TareaOut:
    try:
        tarea = tareas_service.cambiar_estado(tarea_id, datos.estado)
    except ErrorNegocio as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if tarea is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    return tarea


@router.delete("/{tarea_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(tarea_id: int, _token: str = Depends(requiere_login)) -> None:
    if not tareas_service.eliminar(tarea_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
