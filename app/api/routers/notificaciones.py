import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.contrato import respuestas
from app.api.deps import ServicioNotificacionesDep
from app.api.schemas import (
    CicloResponse,
    CrearNotificacionRequest,
    MensajeResponse,
    NotificacionCreadaResponse,
    NotificacionDuplicadaResponse,
)
from app.domain.autenticacion_service import Identidad
from app.domain.errores import NoAutorizado
from app.security.api_key import exigir_api_key

log = logging.getLogger(__name__)

router = APIRouter(prefix="/notificaciones")


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
    tags=["notificaciones"],
    summary="Registrar o resolver una notificación de stock bajo",
    description=(
        "El emisor reporta un evento sobre un artículo. Su llave debe ser del rol que emite el "
        "tipo (inventario para STOCK_BAJO_INSUMO y STOCK_BAJO_PRODUCTO).\n\n"
        "- **DETECTADA**: registra la notificación y activa la alerta del artículo (`201`). Si "
        "ya hay una alerta activa para ese tipo y `productoId`, no crea otra: responde `200` "
        "con el id original y `duplicada: true`. La alerta vence a las 24 h; el reenvío no "
        "renueva ese plazo.\n"
        "- **REPUESTO** o **RESUELTA**, con los mismos datos de la activación: resuelve la "
        "alerta activa (`200`, «Alerta resuelta correctamente»). Sin alerta activa no cambia "
        "nada (`200`, «No había una alerta activa»). Un nuevo DETECTADA vuelve a notificar.\n\n"
        "La respuesta no espera la entrega al equipo destino."
    ),
    responses={
        200: {
            "model": NotificacionDuplicadaResponse | MensajeResponse,
            "description": "Alerta ya activa (DETECTADA repetido) o resultado de una resolución",
            "content": {
                "application/json": {
                    "examples": {
                        "duplicada": {
                            "summary": "DETECTADA con alerta activa",
                            "value": {
                                "id": "0b6f1c7e-5f4e-4d62-9c1a-3f6d0f2f9a11",
                                "duplicada": True,
                                "mensaje": "Ya existe una alerta activa para este artículo",
                            },
                        },
                        "resuelta": {
                            "summary": "REPUESTO o RESUELTA con alerta activa",
                            "value": {"mensaje": "Alerta resuelta correctamente"},
                        },
                        "sinAlerta": {
                            "summary": "REPUESTO o RESUELTA sin alerta activa",
                            "value": {"mensaje": "No había una alerta activa"},
                        },
                    }
                }
            },
        },
        201: {
            "model": NotificacionCreadaResponse,
            "description": "Notificación registrada y alerta activada",
            "content": {
                "application/json": {
                    "example": {
                        "id": "0b6f1c7e-5f4e-4d62-9c1a-3f6d0f2f9a11",
                        "mensaje": "Notificación registrada correctamente",
                    }
                }
            },
        },
        **respuestas(401, 403, 422, 500),
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
    tags=["administración"],
    summary="Ejecutar el ciclo de notificaciones",
    description=(
        "Corre las tareas periódicas; hoy cierra con motivo EXPIRACION las alertas vencidas. "
        "Solo la API Key del rol `notificaciones`; pensado para invocarse de forma externa "
        "y periódica. Ciclos simultáneos nunca procesan la misma alerta dos veces."
    ),
    response_model=CicloResponse,
    response_model_by_alias=True,
    responses={
        200: {
            "description": "Resumen del ciclo",
            "content": {"application/json": {"example": {"alertasCerradas": 2, "errores": []}}},
        },
        **respuestas(401, 403, 500),
    },
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
