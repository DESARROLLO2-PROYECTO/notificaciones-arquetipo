"""Webhook que Notificaciones envía al equipo destino (HU-NOT-17).

Solo documenta el contrato para que los demás equipos construyan su receptor: la entrega real la
hará el worker. No es una ruta de esta API.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Header
from pydantic import ConfigDict, Field

from app.api.schemas import _Base


class NotificacionEntregada(_Base):
    """Cuerpo del POST que recibe el callback del equipo destino."""

    model_config = ConfigDict(
        alias_generator=_Base.model_config["alias_generator"],
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "0b6f1c7e-5f4e-4d62-9c1a-3f6d0f2f9a11",
                    "tipo": "STOCK_BAJO_INSUMO",
                    "equipoEmisor": "inventario",
                    "equipoDestino": "inventario",
                    "fechaRegistro": "2026-11-25T14:30:00Z",
                    "mensaje": "[STOCK_BAJO_INSUMO] Acero 304 (INS-001): stock 4, mínimo 10",
                    "datos": {
                        "productoId": "INS-001",
                        "nombre": "Acero inoxidable 304",
                        "stockActual": 4,
                        "stockMinimo": 10,
                    },
                }
            ]
        },
    )
    id: UUID = Field(description="Identificador de la notificación; igual a `X-Notification-Id`")
    tipo: str = Field(description="Tipo del catálogo, por ejemplo STOCK_BAJO_INSUMO")
    equipo_emisor: str = Field(description="Rol que reportó el evento")
    equipo_destino: str = Field(description="Rol que debe atenderlo")
    fecha_registro: datetime = Field(description="Cuándo se registró, en UTC ISO 8601")
    mensaje: str = Field(max_length=200, description="Texto legible, de máximo 200 caracteres")
    datos: dict[str, Any] = Field(
        description="Datos propios del tipo, tal como los envió el emisor"
    )


def registrar_webhooks(app: FastAPI) -> None:
    @app.webhooks.post(
        "notificacion",
        summary="Entrega de una notificación (disponible desde HU-NOT-17, Sprint 3)",
        description=(
            "Notificaciones envía este POST a la URL que el equipo destino registró (HU-NOT-16), "
            "con un tiempo de espera de 10 segundos.\n\n"
            "- `X-Signature` es el HMAC SHA-256 en hexadecimal, con el secreto del callback, de "
            "`X-Timestamp`, un punto y el cuerpo crudo (`<timestamp>.<cuerpo>`). Rechace la "
            "solicitud si la firma no coincide o si `X-Timestamp` tiene más de 5 minutos.\n"
            "- Responda **cualquier 2xx** para confirmar. Otro código, un tiempo de espera o un "
            "error de conexión se reintentan a los 5 minutos, hasta 3 intentos.\n"
            "- La entrega es *al menos una vez*: use `X-Notification-Id` para ignorar repetidas."
        ),
        tags=["notificaciones"],
        operation_id="recibirNotificacion",
    )
    def notificacion(
        cuerpo: NotificacionEntregada,
        x_notification_id: Annotated[
            UUID, Header(alias="X-Notification-Id", description="Id de la notificación")
        ],
        x_timestamp: Annotated[
            datetime, Header(alias="X-Timestamp", description="Fecha de envío, UTC ISO 8601")
        ],
        x_signature: Annotated[
            str, Header(alias="X-Signature", description="HMAC SHA-256 hexadecimal")
        ],
    ) -> None:
        """Contrato del receptor: la API no ejecuta esta función."""
