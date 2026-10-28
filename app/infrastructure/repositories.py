"""Repository/DAO: implementa los puertos de app/domain/puertos.py con SQLAlchemy."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import puertos
from app.domain.errores import NombreDuplicado
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
