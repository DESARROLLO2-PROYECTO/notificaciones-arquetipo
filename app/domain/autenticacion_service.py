"""HU-NOT-12: Autenticacion de las llaves."""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.domain.errores import NoAutenticado


@dataclass(frozen=True)
class Identidad:
    """Equipo dueño de una llave activa; su nombre es el rol de la llave."""

    equipo_id: int
    rol: str


class AutenticacionRepository(Protocol):
    def obtener_por_hash(self, hash_llave: str) -> tuple[int, str, bool] | None:
        """Devuelve (id del equipo, rol, llave activa) o None si el hash no existe."""
        ...


class AutenticacionService:
    def __init__(self, repo: AutenticacionRepository) -> None:
        self._repo = repo

    def autenticar(self, llave: str | None) -> Identidad:
        if llave is None or not llave.strip():
            raise NoAutenticado("sin llave")

        hash_llave = hashlib.sha256(llave.encode("utf-8")).hexdigest()
        registro = self._repo.obtener_por_hash(hash_llave)
        if registro is None:
            raise NoAutenticado("llave inválida")

        equipo_id, rol, activa = registro
        if not activa:
            raise NoAutenticado("llave desactivada", rol)
        return Identidad(equipo_id, rol)
