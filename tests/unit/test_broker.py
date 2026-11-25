import json
import time
from types import SimpleNamespace
from uuid import uuid4

import aio_pika
import pytest

from app.domain.errores import ColaNoDisponible
from app.domain.puertos import MensajeNotificacion
from app.infrastructure import broker
from scripts import verificar_cola


def test_el_mensaje_lleva_solo_el_id_y_el_tipo_y_es_persistente():
    id = uuid4()

    mensaje = broker.construir_mensaje(MensajeNotificacion(id, "STOCK_BAJO_INSUMO", "inventario"))

    assert json.loads(mensaje.body) == {"id": str(id), "tipo": "STOCK_BAJO_INSUMO"}
    assert mensaje.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    assert mensaje.content_type == "application/json"
    assert mensaje.message_id == str(id)


def test_cada_destino_tiene_su_cola():
    assert [broker.nombre_cola(d) for d in broker.DESTINOS] == [
        "notif.inventario",
        "notif.fabricacion",
    ]


def test_publicar_en_un_destino_sin_cola_falla_antes_de_conectar():
    publicador = broker.PublicadorAmqp("amqp://nadie@localhost:1/")

    with pytest.raises(ValueError, match="notificaciones"):
        publicador.publicar(MensajeNotificacion(uuid4(), "STOCK_BAJO_INSUMO", "notificaciones"))


def _con_ajustes(monkeypatch, amqp_url):
    monkeypatch.setattr(
        broker, "get_settings", lambda: SimpleNamespace(amqp_url=amqp_url, amqp_timeout_s=3.0)
    )
    broker.obtener_publicador.cache_clear()


def test_sin_amqp_url_no_hay_publicador(monkeypatch):
    _con_ajustes(monkeypatch, None)

    with pytest.raises(ColaNoDisponible, match="AMQP_URL"):
        broker.obtener_publicador()


def test_con_amqp_url_el_publicador_es_unico_y_no_conecta_al_crearse(monkeypatch):
    _con_ajustes(monkeypatch, "amqp://test:test@127.0.0.1:1/")

    assert broker.obtener_publicador() is broker.obtener_publicador()

    broker.cerrar_publicador()  # nunca conectó: no debe fallar
    assert broker.obtener_publicador.cache_info().currsize == 0


def test_cerrar_sin_haber_usado_la_cola_no_crea_nada():
    broker.obtener_publicador.cache_clear()

    broker.cerrar_publicador()

    assert broker.obtener_publicador.cache_info().currsize == 0


def test_la_sonda_sin_url_pide_configurarla(monkeypatch, capsys):
    monkeypatch.delenv("AMQP_URL", raising=False)

    assert verificar_cola.main([]) == 1
    assert "AMQP_URL" in capsys.readouterr().err


def test_la_sonda_no_imprime_la_clave_si_falla(capsys):
    codigo = verificar_cola.main(
        ["--url", "amqp://usuario:clave-secreta@localhost:1/", "--timeout", "1"]
    )

    salida = capsys.readouterr()
    assert codigo == 1
    assert "clave-secreta" not in salida.out + salida.err


def test_precalentar_sin_amqp_url_no_hace_nada(monkeypatch):
    _con_ajustes(monkeypatch, None)

    broker.precalentar_publicador()

    assert broker.obtener_publicador.cache_info().currsize == 0


def test_el_arranque_de_la_api_sigue_si_el_broker_no_responde(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    # Antes de importar app.main: al importarlo se crea la app y se lee la configuración.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from app.main import create_app

    _con_ajustes(monkeypatch, "amqp://test:clave-secreta@127.0.0.1:1/")
    caplog.set_level("INFO", logger="app.infrastructure.broker")

    with TestClient(create_app()) as cliente:
        assert cliente.get("/health").status_code == 200
        for _ in range(50):  # el aviso llega cuando vence el intento de conexión
            if "no disponible al arrancar" in caplog.text:
                break
            time.sleep(0.2)

    assert "Cola de mensajes no disponible al arrancar (" in caplog.text
    assert "clave-secreta" not in caplog.text
    assert broker.obtener_publicador.cache_info().currsize == 0  # lo cerró el apagado
