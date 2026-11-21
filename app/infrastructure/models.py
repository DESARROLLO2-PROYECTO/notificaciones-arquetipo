"""Modelo ORM (ER del DAS)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
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
