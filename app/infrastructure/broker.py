"""Adapter del broker (RabbitMQ en CloudAMQP) con aio-pika.

Topología (DAS): exchange "notificaciones" de tipo direct y una cola durable "notif.<destino>"
por equipo que recibe, enlazada con la clave de ruteo igual al destino. La API es síncrona y
el cliente asíncrono corre en un bucle propio, que mantiene una conexión robusta y reutilizable.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturoVencido
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import aio_pika
from aio_pika.abc import AbstractRobustChannel, AbstractRobustConnection
from aio_pika.exceptions import CONNECTION_EXCEPTIONS

from app.config import get_settings
from app.domain.errores import ColaNoDisponible
from app.domain.puertos import MensajeNotificacion

log = logging.getLogger(__name__)

EXCHANGE = "notificaciones"
DESTINOS = ("inventario", "fabricacion")  # equipos que reciben; el admin no recibe notificaciones
CLAVE_SONDA = "sonda"

_ERRORES_BROKER = (
    *CONNECTION_EXCEPTIONS,
    TimeoutError,
    FuturoVencido,
    aio_pika.exceptions.AMQPError,
)


def nombre_cola(destino: str) -> str:
    return f"notif.{destino}"


def construir_mensaje(mensaje: MensajeNotificacion) -> aio_pika.Message:
    """Persistente y con el id y el tipo (HU-NOT-03, criterio 1)."""
    cuerpo = json.dumps({"id": str(mensaje.notificacion_id), "tipo": mensaje.tipo})
    return aio_pika.Message(
        body=cuerpo.encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=str(mensaje.notificacion_id),
        type=mensaje.tipo,
        timestamp=datetime.now(UTC),
    )


class PublicadorAmqp:
    """Implementa el puerto Publicador; la conexión se abre al primer uso y se reabre sola."""

    def __init__(
        self, url: str, destinos: Sequence[str] = DESTINOS, timeout_s: float = 5.0
    ) -> None:
        self._url = url
        self._destinos = tuple(destinos)
        self._timeout_s = timeout_s
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._hilo: threading.Thread | None = None
        self._arranque = threading.Lock()
        self._conexion: AbstractRobustConnection | None = None
        self._canal: AbstractRobustChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._conectando: asyncio.Lock | None = None

    def publicar(self, mensaje: MensajeNotificacion) -> None:
        if mensaje.destino not in self._destinos:
            raise ColaNoDisponible(f"Destino sin cola: {mensaje.destino}")
        futuro = asyncio.run_coroutine_threadsafe(self._publicar(mensaje), self._obtener_bucle())
        try:
            futuro.result(timeout=2 * self._timeout_s)
        except _ERRORES_BROKER as error:
            futuro.cancel()
            raise ColaNoDisponible("No fue posible publicar en la cola") from error

    def precalentar(self) -> None:
        """Abre la conexión y declara la topología en segundo plano, sin esperar el resultado.

        La primera conexión tarda un par de segundos con CloudAMQP; así no la paga la primera
        solicitud. Si falla, solo se avisa en el log: publicar vuelve a intentarlo.
        """
        futuro = asyncio.run_coroutine_threadsafe(self._asegurar_topologia(), self._obtener_bucle())
        futuro.add_done_callback(self._registrar_precalentamiento)

    @staticmethod
    def _registrar_precalentamiento(futuro: Future[Any]) -> None:
        error = None if futuro.cancelled() else futuro.exception()
        if error is None:
            log.info("Cola de mensajes lista")
        else:  # solo el tipo: el mensaje del driver puede incluir datos de la conexión
            log.warning("Cola de mensajes no disponible al arrancar (%s)", type(error).__name__)

    def cerrar(self) -> None:
        bucle = self._bucle
        if bucle is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._cerrar(), bucle).result(timeout=self._timeout_s)
        except _ERRORES_BROKER:
            pass
        finally:
            bucle.call_soon_threadsafe(bucle.stop)
            if self._hilo is not None:
                self._hilo.join(timeout=self._timeout_s)
            self._bucle = self._hilo = None
            self._conexion = self._canal = self._exchange = self._conectando = None

    def _obtener_bucle(self) -> asyncio.AbstractEventLoop:
        with self._arranque:
            if self._bucle is None:
                bucle = asyncio.new_event_loop()
                hilo = threading.Thread(target=bucle.run_forever, name="amqp", daemon=True)
                hilo.start()
                self._bucle, self._hilo = bucle, hilo
            return self._bucle

    async def _publicar(self, mensaje: MensajeNotificacion) -> None:
        exchange = await self._asegurar_topologia()
        # mandatory: si ninguna cola recibe el mensaje, falla en vez de perderse sin aviso.
        await exchange.publish(
            construir_mensaje(mensaje),
            routing_key=mensaje.destino,
            mandatory=True,
            timeout=self._timeout_s,
        )

    async def _asegurar_topologia(self) -> aio_pika.abc.AbstractExchange:
        if self._conectando is None:
            self._conectando = asyncio.Lock()
        async with self._conectando:
            if self._exchange is not None and self._canal is not None and not self._canal.is_closed:
                return self._exchange
            self._conexion = await aio_pika.connect_robust(self._url, timeout=self._timeout_s)
            self._canal = await self._conexion.channel()  # con confirmaciones de publicación
            self._exchange = await self._canal.declare_exchange(
                EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
            )
            for destino in self._destinos:
                cola = await self._canal.declare_queue(nombre_cola(destino), durable=True)
                await cola.bind(self._exchange, routing_key=destino)
            return self._exchange

    async def _cerrar(self) -> None:
        if self._conexion is not None:
            await self._conexion.close()


async def sondear(url: str, timeout_s: float = 5.0) -> float:
    """Comprueba conexión, exchange, publicación y consumo con una cola temporal y exclusiva.

    No toca las colas de los equipos. Devuelve el tiempo de ida y vuelta en segundos.
    """
    inicio = time.monotonic()
    conexion = await aio_pika.connect_robust(url, timeout=timeout_s)
    try:
        canal = await conexion.channel()
        exchange = await canal.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        cola = await canal.declare_queue(exclusive=True, auto_delete=True)
        await cola.bind(exchange, routing_key=CLAVE_SONDA)
        await exchange.publish(
            aio_pika.Message(body=b"sonda"), routing_key=CLAVE_SONDA, timeout=timeout_s
        )
        recibido = await cola.get(timeout=timeout_s, fail=True)
        await recibido.ack()
    finally:
        await conexion.close()
    return time.monotonic() - inicio


@lru_cache
def obtener_publicador() -> PublicadorAmqp:
    """Publicador compartido por el proceso; falla con ColaNoDisponible si no hay AMQP_URL."""
    ajustes = get_settings()
    if not ajustes.amqp_url:
        raise ColaNoDisponible("AMQP_URL no está configurada")
    return PublicadorAmqp(ajustes.amqp_url, timeout_s=ajustes.amqp_timeout_s)


def precalentar_publicador() -> None:
    """Al arrancar la API: conecta en segundo plano si hay AMQP_URL; si no, no hace nada."""
    if get_settings().amqp_url:
        obtener_publicador().precalentar()


def cerrar_publicador() -> None:
    """Cierra la conexión al apagar la API; no crea una si nunca se usó."""
    if obtener_publicador.cache_info().currsize:
        obtener_publicador().cerrar()
        obtener_publicador.cache_clear()
