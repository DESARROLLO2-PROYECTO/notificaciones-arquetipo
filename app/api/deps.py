"""Inyección de dependencias: sesión → repo → servicio (raíz de composición)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.domain.equipo_service import EquipoService
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
