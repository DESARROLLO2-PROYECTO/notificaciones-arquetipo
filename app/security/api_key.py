"""Lee y verifica la llave enviada en X-API-Key."""

import logging
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.api.deps import AutenticacionDep
from app.domain.errores import NoAutenticado

log = logging.getLogger(__name__)
_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def exigir_api_key(
    request: Request,
    servicio: AutenticacionDep,
    llave: Annotated[str | None, Security(_header)],
) -> str:
    rol = servicio.autenticar(llave) if llave and llave.strip() else None
    if rol is not None:
        return rol

    motivo = "llave inválida o desactivada" if llave and llave.strip() else "sin llave"
    log.warning(
        "RECHAZADA 401 endpoint=%s %s motivo=%s",
        request.method,
        request.scope["route"].path,
        motivo,
    )
    raise NoAutenticado("Acceso denegado")
