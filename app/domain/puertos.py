"""Entidades y puertos del dominio. La infraestructura los implementa."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Equipo:
    nombre: str
    es_admin: bool
    id: int | None = None


class EquipoRepository(Protocol):
    def crear(self, equipo: Equipo) -> Equipo: ...

    def obtener(self, id: int) -> Equipo | None: ...
