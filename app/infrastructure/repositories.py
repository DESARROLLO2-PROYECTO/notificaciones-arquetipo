"""Repository/DAO: implementa los puertos de app/domain/puertos.py con SQLAlchemy."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import puertos
from app.domain.errores import NombreDuplicado, ClaveDuplicada
from app.infrastructure import models as m
from uuid import UUID


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
            raise NombreDuplicado("Ya existe un equipo con ese nombre") from e
        return _a_dominio(registro)

    def obtener(self, id: int) -> puertos.Equipo | None:
        r = self._s.get(m.Equipo, id)
        return None if r is None else _a_dominio(r)


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

    def crear(self, tipo: puertos.TipoNotificacion) -> puertos.TipoNotificacion:
        registro = m.TipoNotificacion(
        campo_clave=tipo.campo_clave,
        ttl_alerta_min=tipo.ttl_alerta_min,
        activo=tipo.activo,
        equipo_emisor_id=tipo.equipo_emisor_id,
        equipo_destino_id=tipo.equipo_destino_id,
        schema=tipo.schema,
    )
        try:
            self._s.add(registro)
            self._s.flush()
        except IntegrityError as e:  # Si hay repetición de campo_clave
            raise ClaveDuplicada("Ya existe un tipo de notificación con ese campo clave") from e
        return _tipo_notificacion_a_dominio(registro)

    def obtener(self, codigo: str) -> puertos.TipoNotificacion | None:
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
            None
            if r.motivo_resolucion is None
            else puertos.ResolucionAlerta(r.motivo_resolucion)
        ),
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
                None
                if alerta.motivo_resolucion is None
                else str(alerta.motivo_resolucion)
            ),
        )
        self._s.add(registro)
        self._s.flush()
        return _alerta_a_dominio(registro)

    def obtener(self, id: int) -> puertos.Alerta | None:
        r = self._s.get(m.Alerta, id)
        return None if r is None else _alerta_a_dominio(r)