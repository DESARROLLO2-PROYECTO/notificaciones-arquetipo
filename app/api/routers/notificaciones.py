from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.schemas import (
    CrearNotificacionRequest,
    ErrorCampo,
    ErrorValidacionResponse,
    EventoNotificacion,
    NotificacionCreadaResponse,
    NotificacionDuplicadaResponse,
)
from app.domain.notificacion_service import ServicioNotificaciones, TipoNotificacionInvalido

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": NotificacionDuplicadaResponse},
        201: {"model": NotificacionCreadaResponse},
        422: {"model": ErrorValidacionResponse},
    },
)
def crear_notificacion(
    body: CrearNotificacionRequest,
    response: Response,
    equipo_emisor_id: int,
    servicio: ServicioNotificaciones, 
):
    resultado = servicio.registrar_notificacion(
        tipo_codigo=body.tipo,
        evento=body.evento.value,
        datos=body.model_dump(mode="json"),
        equipo_emisor_id=equipo_emisor_id,
    )

    if resultado.duplicada:
        response.status_code = status.HTTP_200_OK
        return NotificacionDuplicadaResponse(
            id=resultado.notificacion_id,
            duplicada=True,
            mensaje="Ya existe una alerta activa para este artículo",
        )

    response.status_code = status.HTTP_201_CREATED
    return NotificacionCreadaResponse(
        id=resultado.notificacion_id,
        mensaje="Notificación registrada correctamente",
    )