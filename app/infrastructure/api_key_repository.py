"""Persistencia de API Keys; el valor completo nunca llega al repositorio."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domain.api_key_service import NuevaApiKey
from app.domain.errores import NoEncontrado
from app.infrastructure.models import ApiKey, Equipo


class ApiKeyRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def bloquear_equipo(self, rol: str) -> int:
        id = self._s.scalar(select(Equipo.id).where(Equipo.nombre == rol).with_for_update())
        if id is None:
            raise NoEncontrado("Equipo del rol no encontrado; ejecute las migraciones")
        return id

    def contar_activas(self, equipo_id: int) -> int:
        return (
            self._s.scalar(
                select(func.count())
                .select_from(ApiKey)
                .where(ApiKey.equipo_id == equipo_id, ApiKey.activa.is_(True))
            )
            or 0
        )

    def crear(self, llave: NuevaApiKey) -> int:
        registro = ApiKey(
            equipo_id=llave.equipo_id,
            hash=llave.hash,
            prefijo=llave.prefijo,
            creada_at=llave.creada_at,
            activa=True,
        )
        self._s.add(registro)
        self._s.flush()
        return registro.id

    def desactivar(self, id: int) -> bool:
        actualizado = self._s.scalar(
            update(ApiKey).where(ApiKey.id == id).values(activa=False).returning(ApiKey.id)
        )
        return actualizado is not None

    def obtener_activa_por_hash(self, hash_llave: str) -> str | None:
        """Busca en la base de datos el hash correspondiente y devuelve el nombre del equipo de la hash si esta activa."""
        return self._s.scalar(
            select(Equipo.nombre)
            .select_from(ApiKey)
            .join(Equipo, ApiKey.equipo_id == Equipo.id)
            .where(ApiKey.hash == hash_llave, ApiKey.activa.is_(True))
        )
