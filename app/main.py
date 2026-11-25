"""Bootstrap: crea FastAPI, registra routers y manejadores de error. Swagger en /docs."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routers import equipos, health, notificaciones
from app.config import get_settings
from app.domain.errores import (
    ErrorDominio,
    NoAutenticado,
    NoEncontrado,
    NombreDuplicado,
    TipoNotificacionInvalido,
)

log = logging.getLogger(__name__)

_ESTADOS: dict[type[ErrorDominio], int] = {
    NoAutenticado: 401,
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
    mensaje = (
        "Los datos enviados no cumplen las reglas establecidas"
        if en_cuerpo
        else "Solicitud inválida: verifique los parámetros enviados"
    )
    campos = [{"campo": str(x["loc"][-1]), "error": x["msg"]} for x in errores]
    ruta = request.scope.get("route")
    ruta_path = getattr(ruta, "path", request.url.path)

    if request.method == "POST" and ruta_path == "/notificaciones":
        cuerpo = e.body if isinstance(e.body, dict) else {}
        log.warning(
            "resultado=RECHAZADA tipo=%s destino=desconocido clave=%s "
            "notificacion_id=None campos=%s",
            cuerpo.get("tipo", "DESCONOCIDO"),
            cuerpo.get("productoId", "None"),
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


def create_app() -> FastAPI:
    logging.basicConfig(
        level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    app = FastAPI(title="Notificaciones", version="0.1.0")
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


app = create_app()
