"""Caso de uso de Equipo. Sin FastAPI ni SQLAlchemy."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.domain import puertos
from app.domain.errores import (
    ErrorConcurrenciaAlerta,
    NoAutorizado,
    TipoNotificacionInvalido,
)

logger = logging.getLogger("notificaciones")


@dataclass(frozen=True)
class ResultadoRegistro:
    notificacion_id: UUID
    duplicada: bool
    tipo: str
    destino: str
    clave: str
    resultado_log: str


class ServicioNotificaciones:
    def __init__(self, uow_factory: Callable[[], puertos.UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def registrar_notificacion(
        self,
        tipo_codigo: str,
        evento: str,
        datos: dict[str, Any],
        equipo_emisor_id: int | None = None,
    ) -> ResultadoRegistro:
        ahora = datetime.now(UTC)
        clave = str(datos["productoId"])

        try:
            return self._intentar_registro(
                ahora=ahora,
                tipo_codigo=tipo_codigo,
                clave=clave,
                datos=datos,
                equipo_emisor_id=equipo_emisor_id,
            )
        except ErrorConcurrenciaAlerta:
            # Criterio 6: Dos requests llegaron al mismo tiempo sin alerta previa.
            # El otro request ganó el INSERT; leemos su alerta activa y respondemos 200.
            with self._uow_factory() as uow:
                destino = self._resolver_destino(uow, tipo_codigo)
                alerta = uow.alertas.obtener_activa(tipo=tipo_codigo, clave=clave)
                if alerta is None:
                    raise  # Falla inesperada -> 500
                res = ResultadoRegistro(
                    notificacion_id=alerta.notificacion_id,
                    duplicada=True,
                    tipo=tipo_codigo,
                    destino=destino,
                    clave=clave,
                    resultado_log="ALERTA_YA_ACTIVA",
                )
                self._log_resultado(res)
                return res

    def _intentar_registro(
        self,
        ahora: datetime,
        tipo_codigo: str,
        clave: str,
        datos: dict[str, Any],
        equipo_emisor_id: int | None,
    ) -> ResultadoRegistro:
        with self._uow_factory() as uow:
            tipo_notif = uow.tipos.obtener_por_codigo(tipo_codigo)
            # Si tipo de notificación no es válido
            if tipo_notif is None or not tipo_notif.activo:
                self._log_rechazo(tipo_codigo, "desconocido", clave)
                raise TipoNotificacionInvalido(
                    f"Tipo '{tipo_codigo}' fuera del catálogo o inactivo."
                )

            destino = self._resolver_destino_desde_tipo(uow, tipo_notif)
            if tipo_notif.equipo_emisor_id is not None and (
                tipo_notif.equipo_emisor_id != equipo_emisor_id
            ):
                self._log_rechazo(tipo_notif.codigo, destino, clave)
                raise NoAutorizado("emisor no permitido")

            # 1. Buscar alerta activa bloqueando fila si ya existe (FOR UPDATE)
            alerta = uow.alertas.obtener_activa(tipo=tipo_notif.codigo, clave=clave)

            if alerta is not None:
                res = ResultadoRegistro(
                    notificacion_id=alerta.notificacion_id,
                    duplicada=True,
                    tipo=tipo_notif.codigo,
                    destino=destino,
                    clave=clave,
                    resultado_log="ALERTA_YA_ACTIVA",
                )
                self._log_resultado(res)
                return res

            # 2. Calcular mensaje (máx 200 chars), pero NO guardarlo en payload
            _mensaje_calculado = self._armar_mensaje(tipo_notif.codigo, datos)

            notificacion = uow.notificaciones.crear(
                puertos.Notificacion(
                    tipo=tipo_notif.codigo,
                    creada_at=ahora,
                    equipo_emisor_id=equipo_emisor_id,
                    equipo_destino_id=tipo_notif.equipo_destino_id,
                    payload=datos,  # Solo los datos recibidos, sin 'mensaje'
                )
            )

            expira_at = (
                ahora + timedelta(minutes=tipo_notif.ttl_alerta_min)
                if tipo_notif.ttl_alerta_min > 0
                else None
            )
            uow.alertas.crear(
                puertos.Alerta(
                    tipo=tipo_notif.codigo,
                    clave=clave,
                    notificacion_id=notificacion.id,
                    creada_at=ahora,
                    expira_at=expira_at,
                )
            )

            # Si hay colisión concurrente aquí, uow.commit()
            # traduce IntegrityError -> ErrorConcurrenciaAlerta
            uow.commit()

        res = ResultadoRegistro(
            notificacion_id=notificacion.id,
            duplicada=False,
            tipo=tipo_notif.codigo,
            destino=destino,
            clave=clave,
            resultado_log="REGISTRADA",
        )
        self._log_resultado(res)
        return res

    def _armar_mensaje(self, tipo: str, datos: dict[str, Any]) -> str:
        texto = (
            f"[{tipo}] {datos['nombre']} ({datos['productoId']}): "
            f"stock actual {datos['stockActual']}, mínimo {datos['stockMinimo']}"
        )
        return texto[:200]

    def _log_resultado(self, res: ResultadoRegistro) -> None:
        logger.info(
            "resultado=%s tipo=%s destino=%s clave=%s notificacion_id=%s",
            res.resultado_log,
            res.tipo,
            res.destino,
            res.clave,
            res.notificacion_id,
        )

    def _log_rechazo(self, tipo: str, destino: str, clave: str) -> None:
        logger.info(
            "resultado=RECHAZADA tipo=%s destino=%s clave=%s notificacion_id=None",
            tipo,
            destino,
            clave,
        )

    def _resolver_destino(self, uow: puertos.UnitOfWork, tipo_codigo: str) -> str:
        tipo_notif = uow.tipos.obtener_por_codigo(tipo_codigo)
        if tipo_notif is None:
            return "desconocido"
        return self._resolver_destino_desde_tipo(uow, tipo_notif)

    def _resolver_destino_desde_tipo(
        self, uow: puertos.UnitOfWork, tipo_notif: puertos.TipoNotificacion
    ) -> str:
        if tipo_notif.equipo_destino_id is None:
            return "desconocido"
        equipo = uow.equipos.obtener(tipo_notif.equipo_destino_id)
        return equipo.nombre if equipo is not None else "desconocido"
