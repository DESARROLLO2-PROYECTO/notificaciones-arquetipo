"""Router/Controlador REST (MVC): POST /equipos, GET /equipos/{id}."""

from typing import Annotated

from fastapi import APIRouter, Path

from app.api.deps import ServicioDep
from app.security.schemas import EquipoIn, EquipoOut

router = APIRouter(prefix="/equipos", tags=["equipos"])


@router.post("", status_code=201, response_model=EquipoOut, response_model_by_alias=True)
def crear(datos: EquipoIn, servicio: ServicioDep) -> EquipoOut:
    e = servicio.crear(datos.nombre, datos.es_admin)
    return EquipoOut.model_validate(e, from_attributes=True)


@router.get("/{id}", response_model=EquipoOut, response_model_by_alias=True)
def obtener(id: Annotated[int, Path(ge=1, le=2**31 - 1)], servicio: ServicioDep) -> EquipoOut:
    return EquipoOut.model_validate(servicio.obtener(id), from_attributes=True)
