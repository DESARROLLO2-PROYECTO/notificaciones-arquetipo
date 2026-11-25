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
    try:
        return servicio.autenticar(llave)
    except NoAutenticado as error:
        log.warning(
            "RECHAZADA 401 endpoint=%s %s motivo=%s rol=%s",
            request.method,
            request.scope["route"].path,
            error.motivo,
            error.rol or "desconocido",
        )
        raise
