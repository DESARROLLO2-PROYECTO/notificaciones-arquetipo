"""Un suscriptor extra de la cola: ve los mensajes del demo sin quitárselos al worker real.

Crea una cola temporal y exclusiva enlazada al mismo exchange y a las mismas claves de ruteo
que usan las colas de los equipos. RabbitMQ le entrega una copia de cada mensaje y la borra al
terminar el demo.
"""

import asyncio
import json
import time
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractQueue

from app.infrastructure.broker import _ERRORES_BROKER, DESTINOS, EXCHANGE


class Escucha:
    def __init__(self, amqp_url: str | None, timeout_s: float = 8.0) -> None:
        self._url = amqp_url
        self._timeout_s = timeout_s
        self._bucle = asyncio.new_event_loop()
        self._conexion: AbstractConnection | None = None
        self._canal: AbstractChannel | None = None
        self._colas: dict[str, AbstractQueue] = {}
        self._vistos: dict[str, list[dict[str, Any]]] = {d: [] for d in DESTINOS}

    @property
    def activa(self) -> bool:
        return self._conexion is not None

    def abrir(self) -> str | None:
        """Conecta y se suscribe. Devuelve un motivo si no pudo, o None si quedó activa."""
        if not self._url:
            return "no hay AMQP_URL"
        try:
            self._bucle.run_until_complete(self._abrir())
        except _ERRORES_BROKER as error:
            self._conexion = None
            return f"no se pudo conectar al broker ({type(error).__name__})"
        return None

    def esperar(
        self, destino: str, notificacion_id: str, espera_s: float = 6.0
    ) -> dict[str, Any] | None:
        """Busca el mensaje de esa notificación en la copia de la cola del destino."""
        limite = time.monotonic() + espera_s
        while True:
            for mensaje in self._vistos[destino]:
                if mensaje.get("id") == notificacion_id:
                    return mensaje
            if time.monotonic() >= limite:
                return None
            try:
                self._bucle.run_until_complete(self._leer(destino))
            except _ERRORES_BROKER:
                # El broker se reinició: las colas temporales desaparecieron con él.
                if not self.reabrir(max(1.0, limite - time.monotonic())):
                    return None

    def reabrir(self, espera_s: float = 40.0) -> bool:
        """Vuelve a suscribirse (p. ej. tras reiniciar el broker). Reintenta hasta `espera_s`."""
        limite = time.monotonic() + espera_s
        while True:
            self._soltar()
            if self.abrir() is None:
                return True
            if time.monotonic() >= limite:
                return False
            time.sleep(2)

    def cerrar(self) -> None:
        self._soltar()
        self._bucle.close()

    def _soltar(self) -> None:
        if self._conexion is not None:
            try:
                self._bucle.run_until_complete(self._conexion.close())
            except _ERRORES_BROKER:
                pass
        self._conexion = self._canal = None
        self._colas = {}

    async def _abrir(self) -> None:
        self._conexion = await aio_pika.connect_robust(self._url, timeout=self._timeout_s)
        self._canal = await self._conexion.channel()
        exchange = await self._canal.declare_exchange(
            EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        for destino in DESTINOS:
            cola = await self._canal.declare_queue(exclusive=True, auto_delete=True)
            await cola.bind(exchange, routing_key=destino)
            self._colas[destino] = cola

    async def _leer(self, destino: str) -> None:
        recibido = await self._colas[destino].get(fail=False, timeout=1)
        if recibido is not None:
            await recibido.ack()
            self._vistos[destino].append(json.loads(recibido.body))
