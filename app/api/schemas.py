"""Validator / DTO (Pydantic v2). JSON en camelCase."""

import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from pydantic.alias_generators import to_camel


class _Base(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EquipoIn(_Base):
    nombre: Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[^\x00]+$")]
    es_admin: StrictBool


class EquipoOut(_Base):
    id: int
    nombre: str
    es_admin: bool


class TipoStockBajo(StrEnum):
    STOCK_BAJO_INSUMO = "STOCK_BAJO_INSUMO"
    STOCK_BAJO_PRODUCTO = "STOCK_BAJO_PRODUCTO"


class EventoNotificacion(StrEnum):
    DETECTADA = "DETECTADA"
    REPUESTO = "REPUESTO"
    RESUELTA = "RESUELTA"


# Permite validar la validez de un producto ID: SÓLO EN FORMATO

_PATRON_PRODUCTO_ID = re.compile(r"^[A-Za-z0-9-]{1,50}$")


class CrearNotificacionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # Rechaza campos desconocidos si aplica
    tipo: TipoStockBajo
    evento: EventoNotificacion = EventoNotificacion.DETECTADA
    productoId: StrictInt | str
    nombre: str = Field(min_length=1, max_length=100)
    stockActual: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
    stockMinimo: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]

    @field_validator("productoId")
    @classmethod
    def validar_producto_id(cls, v: int | str) -> str:
        # En Python bool es subclase de int; lo rechazamos explícitamente
        if isinstance(v, bool):
            raise ValueError("productoId debe ser entero o texto alfanumérico")
        texto = str(v)
        if not _PATRON_PRODUCTO_ID.fullmatch(texto):
            raise ValueError(
                "Debe tener entre 1 y 50 caracteres y contener solo letras, "
                "números y guion, sin espacios"
            )
        return texto

    @field_validator("nombre")
    @classmethod
    def validar_nombre_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El nombre no puede estar vacío o contener solo espacios")
        return v


class NotificacionCreadaResponse(BaseModel):
    id: UUID
    mensaje: str


class NotificacionDuplicadaResponse(BaseModel):
    id: UUID
    duplicada: bool = True
    mensaje: str


class MensajeResponse(BaseModel):
    mensaje: str


class CicloResponse(_Base):
    alertas_cerradas: int
    errores: list[str]


class ErrorCampo(BaseModel):
    campo: str
    error: str


class ErrorValidacionResponse(BaseModel):
    mensaje: str
    errores: list[ErrorCampo]
