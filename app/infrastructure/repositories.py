"""Repository/DAO: implementa los puertos de app/domain/puertos.py con SQLAlchemy."""

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import puertos
from app.domain.errores import (
    ClaveDuplicada,
    ErrorConcurrenciaAlerta,
    NoEncontrado,
    NombreDuplicado,
)
from app.infrastructure import models as m


def _a_dominio(r: m.Equipo) -> puertos.Equipo:
    return puertos.Equipo(r.nombre, r.es_admin, r.id)


class EquipoRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, equipo: puertos.Equipo) -> puertos.Equipo:
        registro = m.Equipo(nombre=equipo.nombre, es_admin=equipo.es_admin)
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as e:  # el único UNIQUE de la tabla es nombre
            self._s.rollback()
            raise NombreDuplicado("Ya existe un equipo con ese nombre") from e
        return _a_dominio(registro)

    def obtener(self, id: int) -> puertos.Equipo | None:
        r = self._s.get(m.Equipo, id)
        return None if r is None else _a_dominio(r)


class ApiKeyRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def bloquear_equipo(self, rol: str) -> int:
        id = self._s.scalar(select(m.Equipo.id).where(m.Equipo.nombre == rol).with_for_update())
        if id is None:
            raise NoEncontrado("Equipo del rol no encontrado; ejecute las migraciones")
        return id

    def contar_activas(self, equipo_id: int) -> int:
        return (
            self._s.scalar(
                select(func.count())
                .select_from(m.ApiKey)
                .where(m.ApiKey.equipo_id == equipo_id, m.ApiKey.activa.is_(True))
            )
            or 0
        )

    def crear(self, llave: puertos.NuevaApiKey) -> int:
        registro = m.ApiKey(
            equipo_id=llave.equipo_id,
            hash=llave.hash,
            prefijo=llave.hash[:8],
            creada_at=llave.creada_at,
            activa=True,
        )
        self._s.add(registro)
        self._s.flush()
        return registro.id

    def desactivar(self, id: int) -> bool:
        actualizado = self._s.scalar(
            update(m.ApiKey).where(m.ApiKey.id == id).values(activa=False).returning(m.ApiKey.id)
        )
        return actualizado is not None

    def obtener_por_hash(self, hash_llave: str) -> tuple[int, str, bool] | None:
        """Devuelve el equipo, el rol y el estado de la llave identificada por el hash."""
        registro = self._s.execute(
            select(m.Equipo.id, m.Equipo.nombre, m.ApiKey.activa)
            .select_from(m.ApiKey)
            .join(m.Equipo, m.ApiKey.equipo_id == m.Equipo.id)
            .where(m.ApiKey.hash == hash_llave)
        ).one_or_none()
        if registro is None:
            return None
        equipo_id, rol, activa = registro
        return equipo_id, rol, activa


def _tipo_notificacion_a_dominio(r: m.TipoNotificacion) -> puertos.TipoNotificacion:
    return puertos.TipoNotificacion(
        campo_clave=r.campo_clave,
        ttl_alerta_min=r.ttl_alerta_min,
        activo=r.activo,
        codigo=r.codigo,
        equipo_emisor_id=r.equipo_emisor_id,
        equipo_destino_id=r.equipo_destino_id,
        schema=r.schema,
    )


class TipoNotificacionRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, tipo_notificacion: puertos.TipoNotificacion) -> puertos.TipoNotificacion:
        registro = m.TipoNotificacion(
            codigo=tipo_notificacion.codigo,
            campo_clave=tipo_notificacion.campo_clave,
            ttl_alerta_min=tipo_notificacion.ttl_alerta_min,
            activo=tipo_notificacion.activo,
            equipo_emisor_id=tipo_notificacion.equipo_emisor_id,
            equipo_destino_id=tipo_notificacion.equipo_destino_id,
            schema=tipo_notificacion.schema,
        )
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as e:  # Si hay repetición de campo_clave
            raise ClaveDuplicada("Ya existe un tipo de notificación con ese campo clave") from e
        return _tipo_notificacion_a_dominio(registro)

    def obtener_por_codigo(self, codigo: str) -> puertos.TipoNotificacion | None:
        r = self._s.get(m.TipoNotificacion, codigo)
        return None if r is None else _tipo_notificacion_a_dominio(r)


def _notificacion_a_dominio(r: m.Notificacion) -> puertos.Notificacion:
    return puertos.Notificacion(
        id=r.id,
        tipo=r.tipo,
        creada_at=r.creada_at,
        intentos_publicacion=r.intentos_publicacion,
        intentos_entrega=r.intentos_entrega,
        publicada_at=r.publicada_at,
        ultimo_error_publicacion=r.ultimo_error_publicacion,
        proximo_intento_entrega=r.proximo_intento_entrega,
        ultimo_error_entrega=r.ultimo_error_entrega,
        leida_at=r.leida_at,
        equipo_emisor_id=r.equipo_emisor_id,
        equipo_destino_id=r.equipo_destino_id,
        payload=r.payload,
    )


class NotificacionRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, notificacion: puertos.Notificacion) -> puertos.Notificacion:
        registro = m.Notificacion(
            tipo=notificacion.tipo,
            creada_at=notificacion.creada_at,
            intentos_publicacion=notificacion.intentos_publicacion,
            intentos_entrega=notificacion.intentos_entrega,
            publicada_at=notificacion.publicada_at,
            ultimo_error_publicacion=notificacion.ultimo_error_publicacion,
            proximo_intento_entrega=notificacion.proximo_intento_entrega,
            ultimo_error_entrega=notificacion.ultimo_error_entrega,
            leida_at=notificacion.leida_at,
            equipo_emisor_id=notificacion.equipo_emisor_id,
            equipo_destino_id=notificacion.equipo_destino_id,
            payload=notificacion.payload,
        )
        if notificacion.id is not None:
            registro.id = notificacion.id

        self._s.add(registro)
        self._s.flush()
        return _notificacion_a_dominio(registro)

    def obtener(self, id: UUID) -> puertos.Notificacion | None:
        r = self._s.get(m.Notificacion, id)
        return None if r is None else _notificacion_a_dominio(r)


def _alerta_a_dominio(r: m.Alerta) -> puertos.Alerta:
    return puertos.Alerta(
        id=r.id,
        tipo=r.tipo,
        clave=r.clave,
        notificacion_id=r.notificacion_id,
        creada_at=r.creada_at,
        expira_at=r.expira_at,
        motivo_resolucion=(
            None if r.motivo_resolucion is None else puertos.ResolucionAlerta(r.motivo_resolucion)
        ),
        resuelta_at=r.resuelta_at,
    )


class AlertaRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def crear(self, alerta: puertos.Alerta) -> puertos.Alerta:
        registro = m.Alerta(
            tipo=alerta.tipo,
            clave=alerta.clave,
            notificacion_id=alerta.notificacion_id,
            creada_at=alerta.creada_at,
            expira_at=alerta.expira_at,
            motivo_resolucion=(
                None if alerta.motivo_resolucion is None else str(alerta.motivo_resolucion)
            ),
        )
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as exc:
            # Otra solicitud activó la misma alerta justo antes (índice único parcial).
            if "unique" not in str(exc.orig).lower():
                raise
            raise ErrorConcurrenciaAlerta("Ya existe una alerta activa concurrente") from exc
        return _alerta_a_dominio(registro)

    def obtener(self, id: int) -> puertos.Alerta | None:
        r = self._s.get(m.Alerta, id)
        return None if r is None else _alerta_a_dominio(r)

    def obtener_activa(self, tipo: str, clave: str, ahora: datetime) -> puertos.Alerta | None:
        stmt = (
            select(m.Alerta)
            .where(
                m.Alerta.tipo == tipo,
                m.Alerta.clave == clave,
                m.Alerta.motivo_resolucion.is_(None),
                or_(m.Alerta.expira_at.is_(None), m.Alerta.expira_at > ahora),
            )
            .with_for_update()
        )
        r = self._s.execute(stmt).scalar_one_or_none()
        return None if r is None else _alerta_a_dominio(r)

    def resolver(self, id: int, motivo: puertos.ResolucionAlerta, ahora: datetime) -> None:
        self._s.execute(
            update(m.Alerta)
            .where(m.Alerta.id == id)
            .values(motivo_resolucion=str(motivo), resuelta_at=ahora)
        )

    def expirar_vencidas(
        self, ahora: datetime, tipo: str | None = None, clave: str | None = None
    ) -> list[puertos.Alerta]:
        # Un solo UPDATE ... RETURNING: dos ciclos simultáneos nunca cierran la misma fila.
        stmt = update(m.Alerta).where(
            m.Alerta.motivo_resolucion.is_(None), m.Alerta.expira_at <= ahora
        )
        if tipo is not None:
            stmt = stmt.where(m.Alerta.tipo == tipo)
        if clave is not None:
            stmt = stmt.where(m.Alerta.clave == clave)
        filas = self._s.scalars(
            stmt.values(
                motivo_resolucion=str(puertos.ResolucionAlerta.EXPIRACION), resuelta_at=ahora
            ).returning(m.Alerta)
        ).all()
        return [_alerta_a_dominio(r) for r in filas]


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        session = self._session_factory()
        self._session = session
        self.equipos: puertos.EquipoRepository = EquipoRepo(session)
        self.tipos: puertos.TipoNotificacionRepository = TipoNotificacionRepo(session)
        self.notificaciones: puertos.NotificacionRepository = NotificacionRepo(session)
        self.alertas: puertos.AlertaRepository = AlertaRepo(session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self._session.close()
            self._session = None

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UnitOfWork no inicializado")
        try:
            self._session.commit()
        except IntegrityError as exc:
            self.rollback()
            if "uq_alertas_activa" in str(exc.orig) or "unique" in str(exc.orig).lower():
                raise ErrorConcurrenciaAlerta("Ya existe una alerta activa concurrente") from exc
            raise

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()
