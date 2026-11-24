"""Modelo ORM (ER del DAS)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Equipo(Base):
    __tablename__ = "equipos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    es_admin: Mapped[bool]


class TipoNotificacion(Base):
    __tablename__ = "tipos_notificacion"

    codigo: Mapped[str] = mapped_column(String(60), primary_key=True)
    equipo_emisor_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    schema: Mapped[dict[str, Any] | list[str] | None] = mapped_column(JSON)
    campo_clave: Mapped[str] = mapped_column(String(60))
    ttl_alerta_min: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean)


class Notificacion(Base):
    __tablename__ = "notificaciones"

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
    proximo_intento_entrega: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error_entrega: Mapped[str | None] = mapped_column(Text)
    leida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    equipo_emisor_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    payload: Mapped[dict[str, Any] | list[str] | None] = mapped_column(JSON)


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
    expira_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motivo_resolucion: Mapped[str | None] = mapped_column(String(30))
    __table_args__ = (
        Index(
            "uq_alerta_activa_tipo_clave",
            "tipo",
            "clave",
            unique=True,
            postgresql_where=text("motivo_resolucion IS NULL"),
        ),
    )
