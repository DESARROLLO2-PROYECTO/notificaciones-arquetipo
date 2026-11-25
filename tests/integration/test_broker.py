"""Cola de mensajes con RabbitMQ real (testcontainers). Sin Docker, se omite (en CI falla)."""

import asyncio
import json
import time
from uuid import uuid4

import aio_pika
import pytest

from app.domain.errores import ColaNoDisponible
from app.domain.puertos import MensajeNotificacion
from app.infrastructure.broker import EXCHANGE, PublicadorAmqp, nombre_cola, sondear


async def _leer(url: str, destino: str) -> list[aio_pika.abc.AbstractIncomingMessage]:
    conexion = await aio_pika.connect_robust(url)
    try:
        canal = await conexion.channel()
        cola = await canal.declare_queue(nombre_cola(destino), passive=True)
        mensajes = []
        while True:
            recibido = await cola.get(fail=False, timeout=2)
            if recibido is None:
                return mensajes
            await recibido.ack()
            mensajes.append(recibido)
    finally:
        await conexion.close()


@pytest.fixture
def publicador(rabbitmq):
    publicador = PublicadorAmqp(rabbitmq, timeout_s=10)
    yield publicador
    publicador.cerrar()


def test_publica_en_la_cola_del_destino_con_id_y_tipo(rabbitmq, publicador):
    id = uuid4()
    publicador.publicar(MensajeNotificacion(id, "STOCK_BAJO_INSUMO", "inventario"))

    mensajes = asyncio.run(_leer(rabbitmq, "inventario"))

    assert [json.loads(m.body) for m in mensajes] == [{"id": str(id), "tipo": "STOCK_BAJO_INSUMO"}]
    assert mensajes[0].delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert mensajes[0].message_id == str(id)
    assert mensajes[0].routing_key == "inventario"
    assert mensajes[0].exchange == EXCHANGE


def test_cada_destino_solo_recibe_lo_suyo(rabbitmq, publicador):
    para_inventario, para_fabricacion = uuid4(), uuid4()
    publicador.publicar(MensajeNotificacion(para_inventario, "STOCK_BAJO_INSUMO", "inventario"))
    publicador.publicar(MensajeNotificacion(para_fabricacion, "STOCK_BAJO_PRODUCTO", "fabricacion"))

    inventario = asyncio.run(_leer(rabbitmq, "inventario"))
    fabricacion = asyncio.run(_leer(rabbitmq, "fabricacion"))

    assert [json.loads(m.body)["id"] for m in inventario] == [str(para_inventario)]
    assert [json.loads(m.body)["id"] for m in fabricacion] == [str(para_fabricacion)]


def test_los_mensajes_se_conservan_hasta_que_alguien_los_lee(rabbitmq, publicador):
    ids = [uuid4() for _ in range(3)]
    for id in ids:
        publicador.publicar(MensajeNotificacion(id, "STOCK_BAJO_INSUMO", "inventario"))

    mensajes = asyncio.run(_leer(rabbitmq, "inventario"))

    assert [json.loads(m.body)["id"] for m in mensajes] == [str(i) for i in ids]


def test_la_topologia_se_puede_declarar_varias_veces(rabbitmq):
    uno, otro = PublicadorAmqp(rabbitmq, timeout_s=10), PublicadorAmqp(rabbitmq, timeout_s=10)
    try:
        uno.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "inventario"))
        otro.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "inventario"))
    finally:
        uno.cerrar()
        otro.cerrar()

    assert len(asyncio.run(_leer(rabbitmq, "inventario"))) == 2


def test_broker_caido_lanza_cola_no_disponible_sin_colgarse():
    publicador = PublicadorAmqp("amqp://test:test@127.0.0.1:1/", timeout_s=1)
    inicio = time.monotonic()

    with pytest.raises(ColaNoDisponible, match="No fue posible publicar"):
        publicador.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "inventario"))

    assert time.monotonic() - inicio < 5
    publicador.cerrar()


def test_credenciales_incorrectas_lanzan_cola_no_disponible(rabbitmq):
    url_mala = rabbitmq.replace("test:test", "test:otra")
    publicador = PublicadorAmqp(url_mala, timeout_s=3)

    with pytest.raises(ColaNoDisponible):
        publicador.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "inventario"))
    publicador.cerrar()


def test_la_sonda_publica_y_consume_sin_tocar_las_colas_de_los_equipos(rabbitmq, publicador):
    publicador.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "inventario"))

    segundos = asyncio.run(sondear(rabbitmq))

    assert 0 < segundos < 5
    assert len(asyncio.run(_leer(rabbitmq, "inventario"))) == 1  # el mensaje real sigue ahí


def test_precalentar_deja_la_topologia_lista_sin_publicar(rabbitmq):
    publicador = PublicadorAmqp(rabbitmq, timeout_s=10)
    try:
        publicador.precalentar()
        for _ in range(50):
            try:
                asyncio.run(_leer(rabbitmq, "fabricacion"))  # cola pasiva: falla si no existe
                break
            except aio_pika.exceptions.AMQPError:
                time.sleep(0.2)
        else:
            pytest.fail("La topología no quedó declarada")
        inicio = time.monotonic()
        publicador.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_PRODUCTO", "fabricacion"))
        assert time.monotonic() - inicio < 1  # ya conectado: sin pagar la conexión
    finally:
        publicador.cerrar()
    assert len(asyncio.run(_leer(rabbitmq, "fabricacion"))) == 1
