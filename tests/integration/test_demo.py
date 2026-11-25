"""El demo completo contra la API real (Postgres y RabbitMQ desechables): si el comportamiento
de la API cambia y el guion deja de cumplirse, esta prueba lo avisa."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.demo.principal import main


@pytest.fixture
def entorno(postgres, rabbitmq, monkeypatch):
    from fastapi.testclient import TestClient

    from app.domain.api_key_service import ApiKeyService
    from app.infrastructure.broker import PublicadorAmqp
    from app.infrastructure.repositories import ApiKeyRepo
    from app.main import create_app

    # Cada rol admite dos llaves activas: se retiran las que dejaron otras pruebas de la sesión.
    with postgres.begin() as c:
        c.execute(text("UPDATE api_keys SET activa = false"))
    with Session(postgres) as session, session.begin():
        servicio = ApiKeyService(ApiKeyRepo(session))
        for variable, rol in (
            ("DEMO_LLAVE_INVENTARIO", "inventario"),
            ("DEMO_LLAVE_FABRICACION", "fabricacion"),
            ("DEMO_LLAVE_ADMIN", "notificaciones"),
        ):
            monkeypatch.setenv(variable, servicio.generar(rol).llave)
    monkeypatch.setenv("AMQP_URL", rabbitmq)

    sano = PublicadorAmqp(rabbitmq, timeout_s=10)
    caido = PublicadorAmqp("amqp://test:test@127.0.0.1:1/", timeout_s=1)
    estado = {"publicador": sano}
    monkeypatch.setattr("app.api.deps.obtener_publicador", lambda: estado["publicador"])

    def leer(mensaje: str) -> str:  # el presentador "apaga" y "enciende" RabbitMQ
        if "Apague" in mensaje:
            estado["publicador"] = caido
        elif "encender" in mensaje:
            estado["publicador"] = sano
        return ""

    def dormir(_: float) -> None:  # el ciclo solo reintenta lo registrado hace más de 1 minuto
        with postgres.begin() as c:
            c.execute(
                text(
                    "UPDATE notificaciones SET creada_at = now() - interval '2 minutes' "
                    "WHERE publicada_at IS NULL"
                )
            )

    with TestClient(create_app()) as cliente:
        yield cliente, leer, dormir
    sano.cerrar()
    caido.cerrar()
    with postgres.begin() as c:  # que el demo no deje llaves activas para las demás pruebas
        c.execute(text("UPDATE api_keys SET activa = false"))


def test_el_demo_completo_cumple_todas_sus_comprobaciones(entorno, monkeypatch, tmp_path):
    cliente, leer, dormir = entorno
    monkeypatch.chdir(tmp_path)  # sin un .demo.env propio
    lineas: list[str] = []

    codigo = main(
        [
            "--rapido",
            "--sin-color",
            "--broker-caido",
            "--espera-reintento",
            "10",
            "--url",
            "http://testserver",
        ],
        http=cliente,
        escribir=lineas.append,
        leer=leer,
        dormir=dormir,
    )

    salida = "\n".join(lineas)
    assert codigo == 0, salida
    assert "Todo salió como se esperaba" in salida
    for comprobacion in (
        "stock bajo registrado (201)",
        "el reintento no duplica",
        "llegó a notif.inventario",
        "llegó a notif.fabricacion",
        "nuevo aviso tras la reposición",
        "con la cola caída el POST responde 201",
        "el ciclo publicó la pendiente",
        "el mensaje llegó a la cola",
    ):
        assert comprobacion in salida
    assert "✗" not in salida


def test_sin_cola_el_demo_omite_esa_escena_y_sigue(entorno, monkeypatch, tmp_path):
    cliente, leer, dormir = entorno
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AMQP_URL")
    lineas: list[str] = []

    codigo = main(
        ["--rapido", "--sin-color", "--url", "http://testserver"],
        http=cliente,
        escribir=lineas.append,
        leer=leer,
        dormir=dormir,
    )

    salida = "\n".join(lineas)
    assert codigo == 0, salida
    assert "omitida (no hay AMQP_URL)" in salida
    assert "llegó a notif." not in salida
