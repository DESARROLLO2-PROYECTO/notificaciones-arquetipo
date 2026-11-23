"""Inyección de dependencias: sesión → repo → servicio (raíz de composición)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.domain.autenticacion_service import AutenticacionService
from app.domain.equipo_service import EquipoService
from app.infrastructure.api_key_repository import ApiKeyRepo
from app.infrastructure.db import transaccion
from app.infrastructure.repositories import EquipoRepo


def get_session() -> Iterator[Session]:
    with transaccion() as session:
        yield session


# scope="function": el commit ocurre antes de enviar la respuesta, no después.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_equipos(session: SessionDep) -> EquipoService:
    return EquipoService(EquipoRepo(session))


ServicioDep = Annotated[EquipoService, Depends(get_equipos)]


def get_autenticacion(session: SessionDep) -> AutenticacionService:
    return AutenticacionService(ApiKeyRepo(session))


AutenticacionDep = Annotated[AutenticacionService, Depends(get_autenticacion)]
