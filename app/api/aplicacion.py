"""Construye la API: rutas, manejadores de error y documentación (Swagger en /docs).

No lee la configuración ni se conecta a nada al importarse: sirve también para generar el contrato
OpenAPI sin base de datos (scripts/exportar_openapi.py)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import contrato
from app.api.routers import equipos, health, notificaciones
from app.api.webhooks import registrar_webhooks
from app.domain.errores import (
    ErrorDominio,
    NoAutenticado,
    NoAutorizado,
    NoEncontrado,
    NombreDuplicado,
    TipoNotificacionInvalido,
)
from app.infrastructure.broker import cerrar_publicador, precalentar_publicador

log = logging.getLogger(__name__)

_ESTADOS: dict[type[ErrorDominio], int] = {
    NoAutenticado: 401,
    NoAutorizado: 403,
    NoEncontrado: 404,
    NombreDuplicado: 409,
    TipoNotificacionInvalido: 422,
}


# Atrapa errores 500 de error de tipado
def _error_dominio(_: Request, e: Exception) -> JSONResponse:
    assert isinstance(e, ErrorDominio)
    status_code = _ESTADOS.get(type(e), 500)
    if isinstance(e, TipoNotificacionInvalido):
        return JSONResponse(
            {
                "mensaje": "Los datos enviados no cumplen las reglas establecidas",
                "errores": [{"campo": "tipo", "error": e.mensaje}],
            },
            status_code=422,
        )
    return JSONResponse({"mensaje": e.mensaje}, status_code=status_code)


def _error_validacion(request: Request, e: Exception) -> JSONResponse:
    assert isinstance(e, RequestValidationError)
    errores = e.errors()
    en_cuerpo = any(x["loc"][0] == "body" for x in errores)
    cuerpo = e.body if isinstance(e.body, dict) else {}
    if cuerpo.get("tipo") == "CONDICION_URGENTE":
        mensaje = "Información de la condición urgente incompleta o inválida"
    elif en_cuerpo:
        mensaje = "Los datos enviados no cumplen las reglas establecidas"
    else:
        mensaje = "Solicitud inválida: verifique los parámetros enviados"
    campos = [{"campo": str(x["loc"][-1]), "error": x["msg"]} for x in errores]
    ruta = request.scope.get("route")
    ruta_path = getattr(ruta, "path", request.url.path)

    if request.method == "POST" and ruta_path == "/notificaciones":
        # %r: tipo y clave llegan sin validar; así no se pueden inyectar líneas en el log
        log.warning(
            "resultado=RECHAZADA tipo=%r destino=desconocido clave=%r "
            "notificacion_id=None campos=%s",
            cuerpo.get("tipo", "DESCONOCIDO"),
            cuerpo.get(
                "codigoCondicion" if cuerpo.get("tipo") == "CONDICION_URGENTE" else "productoId",
                "None",
            ),
            [c["campo"] for c in campos],
        )
    else:
        log.warning(
            "RECHAZADA 422 endpoint=%s %s campos=%s",
            request.method,
            ruta_path,
            [c["campo"] for c in campos],
        )
    return JSONResponse({"mensaje": mensaje, "errores": campos}, status_code=422)


def _error_inesperado(request: Request, e: Exception) -> JSONResponse:
    log.error("Error no controlado en %r", request.url.path, exc_info=e)
    ruta = request.scope.get("route")
    mensaje = (
        "No fue posible registrar la notificación, intente de nuevo"
        if ruta and getattr(ruta, "path", None) == "/notificaciones"
        else "Error interno, intente de nuevo"
    )
    return JSONResponse({"mensaje": mensaje}, status_code=500)


def construir_app() -> FastAPI:
    """Crea la aplicación FastAPI con sus rutas y manejadores."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        precalentar_publicador()
        try:
            yield
        finally:
            cerrar_publicador()  # no hace nada si la cola nunca se usó

    app = FastAPI(
        title="API de Notificaciones",
        version=contrato.API_VERSION,
        description=contrato.DESCRIPCION,
        openapi_tags=contrato.ETIQUETAS,
        contact=contrato.CONTACTO,
        servers=[
            {"url": "http://localhost:8090", "description": "Desarrollo local (compose)"},
            {"url": "https://13-59-144-83.sslip.io", "description": "Producción (EC2, HTTPS)"},
        ],
        generate_unique_id_function=contrato.id_operacion,
        lifespan=lifespan,
    )
    registrar_webhooks(app)
    app.add_exception_handler(ErrorDominio, _error_dominio)
    app.add_exception_handler(NoEncontrado, _error_dominio)
    app.add_exception_handler(NombreDuplicado, _error_dominio)
    app.add_exception_handler(TipoNotificacionInvalido, _error_dominio)
    app.add_exception_handler(RequestValidationError, _error_validacion)
    app.add_exception_handler(Exception, _error_inesperado)
    app.include_router(health.router)
    app.include_router(equipos.router)
    app.include_router(notificaciones.router)
    return app
