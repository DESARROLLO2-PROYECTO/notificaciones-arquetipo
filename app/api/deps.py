"""Inyección de dependencias: sesión → repo → servicio (raíz de composición)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.domain.equipo_service import EquipoService
from app.domain.notificacion_service import ServicioNotificaciones
from app.infrastructure.db import transaccion, get_engine
from app.infrastructure.repositories import EquipoRepo
from app.infrastructure.repositories import SqlAlchemyUnitOfWork


def get_session() -> Iterator[Session]:
    with transaccion() as session:
        yield session


# scope="function": el commit ocurre antes de enviar la respuesta, no después.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_equipos(session: SessionDep) -> EquipoService:
    return EquipoService(EquipoRepo(session))


ServicioDep = Annotated[EquipoService, Depends(get_equipos)]

def get_servicio_notificaciones() -> ServicioNotificaciones:
    return ServicioNotificaciones(
        lambda: SqlAlchemyUnitOfWork(lambda: Session(get_engine()))
    )

ServicioNotificacionesDep = Annotated[
    ServicioNotificaciones, Depends(get_servicio_notificaciones)
]

