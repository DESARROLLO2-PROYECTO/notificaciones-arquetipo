"""Modelo ORM (ER del DAS)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Equipo(Base):
    __tablename__ = "equipos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    es_admin: Mapped[bool]


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_equipo_id_activa", "equipo_id", "activa"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    equipo_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefijo: Mapped[str] = mapped_column(String(16))
    activa: Mapped[bool]
    creada_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TipoNotificacion(Base):
    __tablename__ = "tipos_notificacion"
    __table_args__ = (CheckConstraint("ttl_alerta_min >= 1", name="ck_tipos_ttl_positivo"),)

    codigo: Mapped[str] = mapped_column(String(60), primary_key=True)
    equipo_emisor_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    schema: Mapped[dict[str, Any] | list[str]] = mapped_column(JSONB)
    campo_clave: Mapped[str | None] = mapped_column(String(60))  # sin clave: una alerta por tipo
    ttl_alerta_min: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean)


class Notificacion(Base):
    __tablename__ = "notificaciones"
    __table_args__ = (
        Index("ix_notificaciones_creada_at", "creada_at"),
        Index("ix_notificaciones_tipo", "tipo"),
        Index("ix_notificaciones_equipo_destino_id", "equipo_destino_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tipo: Mapped[str] = mapped_column(String(60), ForeignKey("tipos_notificacion.codigo"))
    creada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    intentos_publicacion: Mapped[int] = mapped_column(Integer, default=0)
    intentos_entrega: Mapped[int] = mapped_column(Integer, default=0)
    publicada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error_publicacion: Mapped[str | None] = mapped_column(Text)
    entregada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proximo_intento_entrega_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error_entrega: Mapped[str | None] = mapped_column(Text)
    leida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    equipo_emisor_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int] = mapped_column(ForeignKey("equipos.id"))
    payload: Mapped[dict[str, Any] | list[str]] = mapped_column(JSONB)


class Alerta(Base):
    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(60), ForeignKey("tipos_notificacion.codigo"))
    clave: Mapped[str] = mapped_column(String(100), index=True)
    notificacion_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("notificaciones.id"))
    creada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_resolucion: Mapped[str | None] = mapped_column(String(30))  # EMISOR | EXPIRACION
    __table_args__ = (
        Index(
            "uq_alerta_activa_tipo_clave",
            "tipo",
            "clave",
            unique=True,
            postgresql_where=text("cerrada_at IS NULL"),
        ),
        UniqueConstraint("notificacion_id", name="uq_alertas_notificacion_id"),
        CheckConstraint("motivo_resolucion IN ('EMISOR', 'EXPIRACION')", name="ck_alertas_motivo"),
        CheckConstraint(
            "(cerrada_at IS NULL) = (motivo_resolucion IS NULL)", name="ck_alertas_cierre_coherente"
        ),
    )
