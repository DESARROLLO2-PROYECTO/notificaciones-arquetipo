"""Repository/DAO: implementa los puertos de app/domain/puertos.py con SQLAlchemy."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import puertos
from app.domain.errores import NombreDuplicado, ClaveDuplicada
from app.infrastructure import models as m


def _a_dominio(r: m.Equipo) -> puertos.Equipo:
    return puertos.Equipo(r.nombre, r.es_admin, r.id)


class EquipoRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, equipo: puertos.Equipo) -> puertos.Equipo:
        registro = m.Equipo(nombre=equipo.nombre, es_admin=equipo.es_admin)
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as e:  # el único UNIQUE de la tabla es nombre
            raise NombreDuplicado("Ya existe un equipo con ese nombre") from e
        return _a_dominio(registro)

    def obtener(self, id: int) -> puertos.Equipo | None:
        r = self._s.get(m.Equipo, id)
        return None if r is None else _a_dominio(r)


def _tipo_notificacion_a_dominio(r: m.TipoNotificacion) -> puertos.TipoNotificacion:
    return puertos.TipoNotificacion(
        campo_clave=r.campo_clave,
        ttl_alerta_min=r.ttl_alerta_min,
        activo=r.activo,
        codigo=r.codigo,
        equipo_emisor_id=r.equipo_emisor_id,
        equipo_destino_id=r.equipo_destino_id,
        schema=r.schema,
    )

class TipoNotificacionRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, tipo: puertos.TipoNotificacion) -> puertos.TipoNotificacion:
        registro = m.TipoNotificacion(
        campo_clave=tipo.campo_clave,
        ttl_alerta_min=tipo.ttl_alerta_min,
        activo=tipo.activo,
        equipo_emisor_id=tipo.equipo_emisor_id,
        equipo_destino_id=tipo.equipo_destino_id,
        schema=tipo.schema,
    )
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as e:  # Si hay repetición de campo_clave
            raise ClaveDuplicada("Ya existe un tipo de notificación con ese campo clave") from e
        return _tipo_notificacion_a_dominio(registro)

    def obtener(self, codigo: str) -> puertos.TipoNotificacion | None:
        r = self._s.get(m.TipoNotificacion, codigo)
        return None if r is None else _tipo_notificacion_a_dominio(r)