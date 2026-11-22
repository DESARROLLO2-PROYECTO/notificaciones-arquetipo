"""Entidades y puertos del dominio. La infraestructura los implementa."""

from dataclasses import dataclass
from typing import Protocol, Any


@dataclass(frozen=True)
class Equipo:
    nombre: str
    es_admin: bool
    id: int | None = None


class EquipoRepository(Protocol):
    def crear(self, equipo: Equipo) -> Equipo: ...

    def obtener(self, id: int) -> Equipo | None: ...



@dataclass(frozen=True)
class TipoNotificacion:
    """Define un tipo de notificación entre equipos.
    """
    campo_clave: str
    ttl_alerta_min: int
    activo: bool
    codigo: str | None = None
    equipo_emisor_id: int | None = None
    equipo_destino_id: int | None = None
    schema: dict[str, Any] | list[str] | None = None

