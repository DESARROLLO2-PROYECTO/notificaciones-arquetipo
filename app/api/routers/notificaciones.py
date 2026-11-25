import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import ServicioNotificacionesDep
from app.api.schemas import (
    CicloResponse,
    CrearNotificacionRequest,
    ErrorValidacionResponse,
    MensajeResponse,
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


def _log_403(request: Request, motivo: str, rol: str | None) -> None:
    log.warning(
        "RECHAZADA 403 endpoint=%s %s motivo=%s rol=%s",
        request.method,
        request.scope["route"].path,
        motivo,
        rol,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar o resolver una notificación de stock bajo",
    description=(
        "DETECTADA registra la notificación y activa la alerta del artículo; si ya hay una "
        "alerta activa responde 200 con el id original. REPUESTO o RESUELTA, con los mismos "
        "datos de la activación, resuelve la alerta activa (motivo EMISOR) y responde 200 "
        "aunque no hubiera alerta activa."
    ),
    responses={
        200: {
            "model": NotificacionDuplicadaResponse | MensajeResponse,
            "description": "Alerta ya activa (DETECTADA) o resultado de la resolución",
        },
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
) -> NotificacionCreadaResponse | NotificacionDuplicadaResponse | MensajeResponse:
    try:
        resultado = servicio.registrar_notificacion(
            tipo_codigo=body.tipo,
            evento=body.evento.value,
            datos=body.model_dump(mode="json"),
            equipo_emisor_id=identidad.equipo_id,
        )
    except NoAutorizado as error:
        _log_403(request, error.motivo, identidad.rol)
        raise

    if resultado.resultado_log == "SIN_ALERTA_ACTIVA":
        response.status_code = status.HTTP_200_OK
        return MensajeResponse(mensaje="No había una alerta activa")

    if resultado.resultado_log == "ALERTA_CERRADA":
        response.status_code = status.HTTP_200_OK
        return MensajeResponse(mensaje="Alerta resuelta correctamente")

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


@router.post(
    "/ciclo",
    summary="Ejecutar el ciclo de notificaciones",
    description=(
        "Corre las tareas periódicas; hoy cierra con motivo EXPIRACION las alertas vencidas. "
        "Solo la API Key del rol `notificaciones`; pensado para invocarse de forma externa "
        "y periódica. Ciclos simultáneos nunca procesan la misma alerta dos veces."
    ),
    response_model=CicloResponse,
    response_model_by_alias=True,
    responses={403: {"description": "Acceso denegado: la llave no es del rol `notificaciones`"}},
)
def ejecutar_ciclo(
    request: Request,
    identidad: Annotated[Identidad, Depends(exigir_api_key)],
    servicio: ServicioNotificacionesDep,
) -> CicloResponse:
    if identidad.rol != "notificaciones":
        _log_403(request, "endpoint de administración", identidad.rol)
        raise NoAutorizado("endpoint de administración")
    resumen, errores = servicio.ejecutar_ciclo()
    return CicloResponse(alertas_cerradas=resumen.get("alertas", 0), errores=errores)
