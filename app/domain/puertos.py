"""Entidades y puertos del dominio. La infraestructura los implementa."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Equipo:
    nombre: str
    es_admin: bool
    id: int | None = None


class EquipoRepository(Protocol):
    def crear(self, equipo: Equipo) -> Equipo: ...

    def obtener(self, id: int) -> Equipo | None: ...


@dataclass(frozen=True)
class NuevaApiKey:
    equipo_id: int
    hash: str = field(repr=False)
    creada_at: datetime


class ApiKeyRepository(Protocol):
    def bloquear_equipo(self, rol: str) -> int:
        """Bloquea el equipo hasta terminar la transacción de generación."""
        ...

    def contar_activas(self, equipo_id: int) -> int: ...

    def crear(self, llave: NuevaApiKey) -> int: ...

    def desactivar(self, id: int) -> bool:
        """Devuelve False si no existe; desactivar otra vez es idempotente."""
        ...
