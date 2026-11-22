"""Modelo ORM (ER del DAS)."""

from typing import Any
from sqlalchemy import String, Integer, Boolean, ForeignKey, JSON
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

    codigo: Mapped[str] = mapped_column(primary_key=True)
    equipo_emisor_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    equipo_destino_id: Mapped[int | None] = mapped_column(ForeignKey("equipos.id"))
    schema: Mapped[dict[str, Any] | list[str] | None] = mapped_column(JSON)
    campo_clave: Mapped[str] = mapped_column(String(60), unique=True)
    ttl_alerta_min: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean)
