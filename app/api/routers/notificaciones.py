import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import ServicioNotificacionesDep
from app.api.schemas import (
    CrearNotificacionRequest,
    ErrorValidacionResponse,
    NotificacionCreadaResponse,
    NotificacionDuplicadaResponse,
)
from app.domain.autenticacion_service import Identidad
from app.domain.errores import NoAutorizado
from app.security.api_key import exigir_api_key

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notificaciones",
    tags=["notificaciones"],
    responses={401: {"description": "Acceso denegado"}},
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": NotificacionDuplicadaResponse},
        201: {"model": NotificacionCreadaResponse},
        403: {"description": "Acceso denegado: el tipo pertenece a otro equipo emisor"},
        422: {"model": ErrorValidacionResponse},
    },
)
def crear_notificacion(
    request: Request,
    body: CrearNotificacionRequest,
    response: Response,
    identidad: Annotated[Identidad, Depends(exigir_api_key)],
    servicio: ServicioNotificacionesDep,
) -> NotificacionCreadaResponse | NotificacionDuplicadaResponse:
    try:
        resultado = servicio.registrar_notificacion(
            tipo_codigo=body.tipo,
            evento=body.evento.value,
            datos=body.model_dump(mode="json"),
            equipo_emisor_id=identidad.equipo_id,
        )
    except NoAutorizado as error:
        log.warning(
            "RECHAZADA 403 endpoint=%s %s motivo=%s rol=%s",
            request.method,
            request.scope["route"].path,
            error.motivo,
            identidad.rol,
        )
        raise

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
