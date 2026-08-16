"""Esquemas Pydantic de entrada/salida de la API.

Formato de fechas: "YYYY-MM-DD HH:MM:SS" en hora local (igual que la base
original). Ejemplo: "2026-08-15 09:30:00".
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

ESTADOS_TAREA = ("pendiente", "completada", "cancelada")

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


def _parse_fecha(valor: str) -> str:
    """Valida y normaliza una fecha a 'YYYY-MM-DD HH:MM:SS'."""
    try:
        dt = datetime.strptime(valor, FORMATO_FECHA)
    except ValueError as exc:
        raise ValueError(f"fecha inválida: '{valor}' (use el formato YYYY-MM-DD HH:MM:SS)") from exc
    return dt.strftime(FORMATO_FECHA)


# ---------------------------------------------------------------------------
# Tareas
# ---------------------------------------------------------------------------
class TareaBase(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=200)
    descripcion: str = Field(default="", max_length=2000)
    estado: str = Field(default="pendiente")
    prioridad: int = Field(default=3, ge=1, le=5)
    fecha_inicio: str
    fecha_fin: str
    duracion_min: int = Field(default=60, ge=1, le=2880)
    bloque_entero: bool = False
    es_recurrente: bool = False
    recurrencia_min: int | None = Field(default=None, ge=1)
    recurrencia_inicio: str | None = None
    recurrencia_fin: str | None = None

    @field_validator("estado")
    @classmethod
    def _validar_estado(cls, v: str) -> str:
        if v not in ESTADOS_TAREA:
            raise ValueError(f"estado inválido: {v}")
        return v

    @field_validator("fecha_inicio", "fecha_fin", "recurrencia_inicio", "recurrencia_fin")
    @classmethod
    def _validar_fechas(cls, v: str | None) -> str | None:
        return _parse_fecha(v) if v else None


class TareaCreate(TareaBase):
    """Creación de tarea. Recurrencia: si es_recurrente, exige
    recurrencia_min y rango recurrencia_inicio/fin."""
    pass


class TareaUpdate(BaseModel):
    """Actualización parcial: solo los campos enviados se modifican."""
    titulo: str | None = Field(default=None, min_length=1, max_length=200)
    descripcion: str | None = Field(default=None, max_length=2000)
    estado: str | None = None
    prioridad: int | None = Field(default=None, ge=1, le=5)
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    duracion_min: int | None = Field(default=None, ge=1, le=2880)
    bloque_entero: bool | None = None
    es_recurrente: bool | None = None
    recurrencia_min: int | None = Field(default=None, ge=1)
    recurrencia_inicio: str | None = None
    recurrencia_fin: str | None = None

    @field_validator("estado")
    @classmethod
    def _validar_estado(cls, v: str | None) -> str | None:
        if v is not None and v not in ESTADOS_TAREA:
            raise ValueError(f"estado inválido: {v}")
        return v

    @field_validator("fecha_inicio", "fecha_fin", "recurrencia_inicio", "recurrencia_fin")
    @classmethod
    def _validar_fechas(cls, v: str | None) -> str | None:
        return _parse_fecha(v) if v else None


class TareaOut(TareaBase):
    id: int
    creado_en: str
    actualizado_en: str

    model_config = {"from_attributes": True}


class TareaEstadoUpdate(BaseModel):
    estado: str

    @field_validator("estado")
    @classmethod
    def _validar_estado(cls, v: str) -> str:
        if v not in ESTADOS_TAREA:
            raise ValueError(f"estado inválido: {v}")
        return v


# ---------------------------------------------------------------------------
# Horario
# ---------------------------------------------------------------------------
class BloqueOut(BaseModel):
    id: int
    tarea_id: int
    inicio: str
    fin: str
    completado: bool
    titulo: str
    prioridad: int


class BloqueEstadoUpdate(BaseModel):
    completado: bool


class BloqueMoverRequest(BaseModel):
    """Nueva hora de inicio para mover un bloque (drag and drop)."""

    inicio: str

    @field_validator("inicio")
    @classmethod
    def _validar_inicio(cls, v: str) -> str:
        return _parse_fecha(v)


class NoProgramadaOut(BaseModel):
    id: int
    tarea_id: int
    fecha_intento: str
    motivo: str
    duracion_faltante_min: int
    detalles: str | None
    titulo: str


class ResultadoGeneracion(BaseModel):
    bloques_insertados: int
    bloques_eliminados: int
    no_programadas: int
    tareas_reorganizadas: int = 0
    mensaje: str


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


class MeResponse(BaseModel):
    autenticado: bool
