"""Router/Controlador REST (MVC): POST /equipos, GET /equipos/{id}."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.contrato import respuestas
from app.api.deps import ServicioDep
from app.api.schemas import EquipoIn, EquipoOut
from app.security.api_key import exigir_api_key

router = APIRouter(
    prefix="/equipos",
    tags=["administración"],
    dependencies=[Depends(exigir_api_key)],
)


@router.post(
    "",
    status_code=201,
    response_model=EquipoOut,
    response_model_by_alias=True,
    summary="Crear un equipo",
    description="Registra un equipo. El nombre debe ser único (409 si ya existe).",
    responses={
        409: {"description": "Ya existe un equipo con ese nombre"},
        **respuestas(401, 422, 500),
    },
)
def crear_equipo(datos: EquipoIn, servicio: ServicioDep) -> EquipoOut:
    e = servicio.crear(datos.nombre, datos.es_admin)
    return EquipoOut.model_validate(e, from_attributes=True)


@router.get(
    "/{id}",
    response_model=EquipoOut,
    response_model_by_alias=True,
    summary="Consultar un equipo",
    description="Devuelve el equipo por su identificador (404 si no existe).",
    responses={404: {"description": "Equipo no encontrado"}, **respuestas(401, 422, 500)},
)
def obtener_equipo(
    id: Annotated[int, Path(ge=1, le=2**31 - 1)], servicio: ServicioDep
) -> EquipoOut:
    return EquipoOut.model_validate(servicio.obtener(id), from_attributes=True)
