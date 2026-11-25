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
    nombre: Annotated[
        str,
        Field(min_length=1, max_length=50, pattern=r"^[^\x00]+$", description="Nombre único"),
    ]
    es_admin: StrictBool = Field(description="Verdadero solo para el equipo de administración")


class EquipoOut(_Base):
    id: int = Field(description="Identificador del equipo")
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
    """Evento de stock bajo. REPUESTO y RESUELTA llevan los mismos datos de la activación."""

    model_config = ConfigDict(
        extra="forbid",  # Rechaza campos desconocidos
        json_schema_extra={
            "examples": [
                {
                    "tipo": "STOCK_BAJO_INSUMO",
                    "evento": "DETECTADA",
                    "productoId": "INS-001",
                    "nombre": "Acero inoxidable 304",
                    "stockActual": 4,
                    "stockMinimo": 10,
                },
                {
                    "tipo": "STOCK_BAJO_INSUMO",
                    "evento": "REPUESTO",
                    "productoId": "INS-001",
                    "nombre": "Acero inoxidable 304",
                    "stockActual": 40,
                    "stockMinimo": 10,
                },
            ]
        },
    )
    tipo: TipoStockBajo = Field(
        description=(
            "STOCK_BAJO_INSUMO para materias primas y artículos de terceros; "
            "STOCK_BAJO_PRODUCTO para cadenas y cuchillas"
        )
    )
    evento: EventoNotificacion = Field(
        default=EventoNotificacion.DETECTADA,
        description="DETECTADA activa la alerta; REPUESTO o RESUELTA la resuelven",
    )
    productoId: StrictInt | str = Field(
        description="Código del artículo: entero o texto de 1 a 50 (letras, números y guion)"
    )
    nombre: str = Field(min_length=1, max_length=100, description="Nombre del artículo")
    stockActual: Annotated[int, Field(strict=True, ge=0, le=1_000_000)] = Field(
        description="Existencia actual"
    )
    stockMinimo: Annotated[int, Field(strict=True, ge=0, le=1_000_000)] = Field(
        description="Mínimo establecido"
    )

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
    alertas_cerradas: int = Field(description="Alertas vencidas cerradas con motivo EXPIRACION")
    errores: list[str] = Field(description="Tareas del ciclo que fallaron; las demás continuaron")


class ErrorResponse(BaseModel):
    """Error sin detalle por campo: 401, 403, 404, 409 y 500."""

    mensaje: str


class ErrorCampo(BaseModel):
    campo: str = Field(description="Campo del cuerpo o parámetro con el problema")
    error: str


class ErrorValidacionResponse(BaseModel):
    mensaje: str
    errores: list[ErrorCampo]
