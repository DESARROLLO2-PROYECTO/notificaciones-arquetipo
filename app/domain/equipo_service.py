"""Caso de uso de Equipo. Sin FastAPI ni SQLAlchemy."""

from app.domain.errores import NoEncontrado
from app.domain.puertos import Equipo, EquipoRepository


class EquipoService:
    def __init__(self, repo: EquipoRepository) -> None:
        self._repo = repo

    def crear(self, nombre: str, es_admin: bool) -> Equipo:
        return self._repo.crear(Equipo(nombre, es_admin))

    def obtener(self, id: int) -> Equipo:
        equipo = self._repo.obtener(id)
        if equipo is None:
            raise NoEncontrado("Equipo no encontrado")
        return equipo
