"""Inyección de dependencias: sesión → repo → servicio (raíz de composición)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.domain.autenticacion_service import AutenticacionService
from app.domain.equipo_service import EquipoService
from app.domain.notificacion_service import ServicioNotificaciones
from app.domain.puertos import MensajeNotificacion
from app.infrastructure.broker import obtener_publicador
from app.infrastructure.db import get_engine, transaccion
from app.infrastructure.repositories import ApiKeyRepo, EquipoRepo, SqlAlchemyUnitOfWork


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


class _PublicadorPerezoso:
    """Resuelve el publicador al publicar: sin AMQP_URL la API arranca y queda pendiente."""

    def publicar(self, mensaje: MensajeNotificacion) -> None:
        obtener_publicador().publicar(mensaje)


def get_servicio_notificaciones() -> ServicioNotificaciones:
    return ServicioNotificaciones(
        lambda: SqlAlchemyUnitOfWork(lambda: Session(get_engine())), _PublicadorPerezoso()
    )


ServicioNotificacionesDep = Annotated[ServicioNotificaciones, Depends(get_servicio_notificaciones)]
