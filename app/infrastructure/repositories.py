"""Repository/DAO: implementa los puertos de app/domain/puertos.py con SQLAlchemy."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import puertos
from app.domain.errores import NoEncontrado, NombreDuplicado
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


class ApiKeyRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def bloquear_equipo(self, rol: str) -> int:
        id = self._s.scalar(select(m.Equipo.id).where(m.Equipo.nombre == rol).with_for_update())
        if id is None:
            raise NoEncontrado("Equipo del rol no encontrado; ejecute las migraciones")
        return id

    def contar_activas(self, equipo_id: int) -> int:
        return (
            self._s.scalar(
                select(func.count())
                .select_from(m.ApiKey)
                .where(m.ApiKey.equipo_id == equipo_id, m.ApiKey.activa.is_(True))
            )
            or 0
        )

    def crear(self, llave: puertos.NuevaApiKey) -> int:
        registro = m.ApiKey(
            equipo_id=llave.equipo_id,
            hash=llave.hash,
            prefijo=llave.hash[:8],
            creada_at=llave.creada_at,
            activa=True,
        )
        self._s.add(registro)
        self._s.flush()
        return registro.id

    def desactivar(self, id: int) -> bool:
        actualizado = self._s.scalar(
            update(m.ApiKey).where(m.ApiKey.id == id).values(activa=False).returning(m.ApiKey.id)
        )
        return actualizado is not None

    def obtener_rol_y_estado_por_hash(self, hash_llave: str) -> tuple[str, bool] | None:
        """Devuelve el rol y el estado de la llave identificada por el hash."""
        registro = self._s.execute(
            select(m.Equipo.nombre, m.ApiKey.activa)
            .select_from(m.ApiKey)
            .join(m.Equipo, m.ApiKey.equipo_id == m.Equipo.id)
            .where(m.ApiKey.hash == hash_llave)
        ).one_or_none()
        if registro is None:
            return None
        rol, activa = registro
        return rol, activa
