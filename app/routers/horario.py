"""Endpoints del horario generado (protegidos por sesión)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from ..deps import requiere_login
from ..schemas import BloqueEstadoUpdate, BloqueMoverRequest, ResultadoGeneracion
from ..services import horario_service, pdf_horario

router = APIRouter(prefix="/api/horario", tags=["horario"])


@router.post("/generar", response_model=ResultadoGeneracion)
def generar(_token: str = Depends(requiere_login)) -> ResultadoGeneracion:
    """Ejecuta el planificador y devuelve el resumen de cambios."""
    resumen = horario_service.generar()
    partes = [f"{resumen['bloques_insertados']} bloques agendados"]
    if resumen.get("tareas_reorganizadas"):
        partes.append(
            f"{resumen['tareas_reorganizadas']} tarea(s) atrasadas reorganizadas"
        )
    if resumen.get("bloques_pasados_reorganizados"):
        partes.append(
            f"{resumen['bloques_pasados_reorganizados']} pendiente(s) "
            "del pasado re-ubicado(s)"
        )
    partes.append(f"{resumen['no_programadas']} tarea(s) sin espacio")
    return ResultadoGeneracion(
        bloques_insertados=resumen["bloques_insertados"],
        bloques_eliminados=resumen["bloques_eliminados"],
        no_programadas=resumen["no_programadas"],
        tareas_reorganizadas=resumen.get("tareas_reorganizadas", 0),
        bloques_pasados_reorganizados=resumen.get(
            "bloques_pasados_reorganizados", 0),
        mensaje="Horario regenerado: " + ", ".join(partes) + ".",
    )


@router.get("/bloques", response_model=list[dict])
def listar_bloques(
    inicio: str | None = Query(default=None),
    fin: str | None = Query(default=None),
    _token: str = Depends(requiere_login),
) -> list[dict]:
    """Bloques del horario (opcionalmente filtrados por rango de fechas)."""
    return horario_service.listar_bloques(inicio, fin)


@router.get("/pdf")
def descargar_pdf(
    inicio: str | None = Query(default=None),
    fin: str | None = Query(default=None),
    _token: str = Depends(requiere_login),
) -> Response:
    """PDF de una sola hoja con la visualización actual del horario."""
    try:
        datos = pdf_horario.generar_pdf(inicio, fin)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    nombre = f"horario_{str(inicio)[:10]}_al_{str(fin)[:10]}.pdf"
    return Response(
        content=datos,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.patch("/bloques/{bloque_id}")
def actualizar_completado(
    bloque_id: int, datos: BloqueEstadoUpdate, _token: str = Depends(requiere_login)
) -> dict:
    try:
        actualizado = horario_service.actualizar_completado(bloque_id, datos.completado)
    except horario_service.ErrorMoverBloque as error:
        raise HTTPException(status_code=error.status_code, detail=error.mensaje)
    if not actualizado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloque no encontrado")
    return {"ok": True}


@router.put("/bloques/{bloque_id}/mover")
def mover_bloque(
    bloque_id: int, datos: BloqueMoverRequest, _token: str = Depends(requiere_login)
) -> dict:
    """Mueve un bloque a una hora nueva (gestión manual del horario)."""
    try:
        return horario_service.mover_bloque(bloque_id, datos.inicio)
    except horario_service.ErrorMoverBloque as error:
        raise HTTPException(status_code=error.status_code, detail=error.mensaje)


@router.delete("/bloques/{bloque_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_bloque(bloque_id: int, _token: str = Depends(requiere_login)) -> None:
    if not horario_service.eliminar_bloque(bloque_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bloque no encontrado")
