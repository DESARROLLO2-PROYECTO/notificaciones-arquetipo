"""Entidades y puertos del dominio. La infraestructura los implementa."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol
from uuid import UUID, uuid4


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


@dataclass(frozen=True)
class TipoNotificacion:
    """Define un tipo de notificación entre equipos."""

    campo_clave: str
    ttl_alerta_min: int
    activo: bool
    codigo: str
    equipo_emisor_id: int | None = None
    equipo_destino_id: int | None = None
    schema: dict[str, Any] | list[str] | None = None


class TipoNotificacionRepository(Protocol):
    def crear(self, tipo_notificacion: TipoNotificacion) -> TipoNotificacion: ...
    def obtener_por_codigo(self, codigo: str) -> TipoNotificacion | None: ...


@dataclass(frozen=True)
class Notificacion:
    tipo: str
    id: UUID = field(default_factory=uuid4)
    creada_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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


class NotificacionRepository(Protocol):
    def crear(self, notificacion: Notificacion) -> Notificacion: ...
    def obtener(self, id: UUID) -> Notificacion | None: ...


"""
Listado ENUM de motivos válidos para la resolución de la alerta
"""


class ResolucionAlerta(StrEnum):
    EMISOR = "emisor"
    EXPIRACION = "expiracion"


@dataclass(frozen=True)
class Alerta:
    tipo: str
    clave: str
    notificacion_id: UUID
    creada_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expira_at: datetime | None = None
    motivo_resolucion: ResolucionAlerta | None = None
    resuelta_at: datetime | None = None
    id: int | None = None


class AlertaRepository(Protocol):
    def crear(self, alerta: Alerta) -> Alerta: ...
    def obtener_activa(self, tipo: str, clave: str, ahora: datetime) -> Alerta | None: ...

    def resolver(self, id: int, motivo: ResolucionAlerta, ahora: datetime) -> None: ...

    def expirar_vencidas(
        self, ahora: datetime, tipo: str | None = None, clave: str | None = None
    ) -> list[Alerta]:
        """Cierra con motivo EXPIRACION las vencidas en una sola sentencia atómica."""
        ...


"""
Permite garantizar unicidad de transacción
"""


class UnitOfWork(Protocol):
    equipos: EquipoRepository
    tipos: TipoNotificacionRepository
    notificaciones: NotificacionRepository
    alertas: AlertaRepository

    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
