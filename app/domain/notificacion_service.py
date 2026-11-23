"""Caso de uso de Equipo. Sin FastAPI ni SQLAlchemy."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from collections.abc import Callable
from app.domain.errores import TipoNotificacionInvalido, ClaveAlertaFaltante

from app.domain import puertos

@dataclass(frozen=True)
class ResultadoRegistro:
    notificacion: puertos.Notificacion | None
    alerta: puertos.Alerta
    es_alerta_nueva: bool
    mensaje: str


class ServicioNotificaciones:
    def __init__(self, uow_factory: Callable[[], puertos.UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def registrar(
        self,
        tipo_codigo: str,
        payload: dict[str, Any],
        equipo_emisor_id: int | None = None,
    ) -> ResultadoRegistro | None:
        ahora = datetime.now(timezone.utc)

        with self._uow_factory() as uow:
            # 1. Validar tipo de notificación
            tipo_notif = uow.tipos.obtener_por_codigo(tipo_codigo)
            if tipo_notif is None or not tipo_notif.activo:
                raise TipoNotificacionInvalido(
                    f"El tipo de notificación {tipo_codigo} no existe o está inactivo."
                )

            # 2. Extraer la clave de deduplicación/agrupación desde el payload
            valor_clave = payload.get(tipo_notif.campo_clave)
            if valor_clave is None or str(valor_clave).strip() == "":
                raise ClaveAlertaFaltante(
                    f"El payload debe incluir el campo '{tipo_notif.campo_clave}'."
                )
            clave = str(valor_clave)

            # 3. Buscar alerta activa (con bloqueo en infraestructura para evitar race conditions)
            alerta = uow.alertas.obtener_activa(
                tipo=tipo_notif.codigo,
            )

            es_alerta_nueva = False

            # 4. Si ya existe y está viva: no registrar nada, devolver ID original
            if alerta is not None:
                notificacion = uow.notificaciones.obtener(alerta.notificacion_id)
                return ResultadoRegistro(
                    notificacion=notificacion,
                    alerta=alerta,
                    es_alerta_nueva=False,
                    mensaje=self._armar_mensaje(tipo_notif, clave, payload, es_alerta_nueva=False),
                )


            # 5. Si no existe: crear notificación + alerta nueva en una sola transacción
            mensaje = self._armar_mensaje(tipo_notif, clave, payload, es_alerta_nueva)

            notificacion = uow.notificaciones.crear(
                puertos.Notificacion(
                    tipo=tipo_notif.campo_clave,
                    creada_at=ahora,
                    equipo_emisor_id=equipo_emisor_id,
                    equipo_destino_id=tipo_notif.equipo_destino_id,
                    payload={**payload, "mensaje": mensaje},
                )
            )

            expira_at = (
                ahora + timedelta(minutes=tipo_notif.ttl_alerta_min)
                if tipo_notif.ttl_alerta_min > 0
                else None
            )
            alerta = uow.alertas.crear(
                puertos.Alerta(
                    clave=clave,
                    tipo=tipo_notif.codigo,
                    notificacion_id=notificacion.id,
                    creada_at=ahora,
                    expira_at=expira_at,
                )
            )
            es_alerta_nueva = True

            # 5. Una sola transacción para alerta + notificación
            uow.commit()


    def _armar_mensaje(
        self,
        tipo_notif: puertos.TipoNotificacion,
        clave: str,
        payload: dict[str, Any],
        es_alerta_nueva: bool,
    ) -> str:
        estado = "Nueva alerta" if es_alerta_nueva else "Alerta activa"
        detalle = payload.get("detalle") or payload.get("descripcion") or ""
        base = f"[{estado}] {tipo_notif.campo_clave}={clave}"
        return f"{base}: {detalle}" if detalle else base