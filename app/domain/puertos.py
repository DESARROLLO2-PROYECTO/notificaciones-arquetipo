"""Entidades y puertos del dominio. La infraestructura los implementa."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID
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

@dataclass(frozen=True)
class Notificacion:
    tipo: str
    creada_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    intentos_publicacion: int = 0
    intentos_entrega: int = 0
    publicada_at: datetime | None = None
    ultimo_error_publicacion: str | None = None
    proximo_intento_entrega: datetime | None = None
    ultimo_error_entrega: str | None = None
    leida_at: datetime | None = None
    equipo_emisor_id: int | None = None
    equipo_destino_id: int | None = None
    payload: dict[str, Any] | list[str] | None = None
    id: UUID | None = None

