"""Flujo de punta a punta con Postgres real (testcontainers). Sin Docker, se omite."""

import os
from uuid import uuid4

import pytest
from testcontainers.community.postgres import PostgresContainer

# Misma versión que docker-compose.yml.
IMAGEN_PG = "postgres:16.15-alpine"


@pytest.fixture(scope="module", autouse=True)
def _postgres():
    try:
        contenedor = PostgresContainer(IMAGEN_PG, driver="psycopg")
        contenedor.start()
    except Exception as e:  # Docker no disponible
        pytest.skip(f"Docker no disponible: {e}")
    os.environ["DATABASE_URL"] = contenedor.get_connection_url()
    yield
    contenedor.stop()


@pytest.fixture(scope="module")
def client(_postgres):
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    from app.main import create_app

    command.upgrade(Config("alembic.ini"), "head")
    with TestClient(create_app()) as c:
        yield c


def _cuerpo():
    return {"nombre": f"eq-{uuid4().hex[:12]}", "esAdmin": False}


def test_crear_y_obtener(client):
    # Arrange
    cuerpo = _cuerpo()

    # Act
    r = client.post("/equipos", json=cuerpo)
    g = client.get(f"/equipos/{r.json()['id']}")

    # Assert
    assert r.status_code == 201
    assert g.status_code == 200
    assert g.json() == {"id": r.json()["id"]} | cuerpo


def test_obtener_inexistente_404(client):
    r = client.get("/equipos/999999")
    assert r.status_code == 404
    assert r.json() == {"mensaje": "Equipo no encontrado"}


@pytest.mark.parametrize("id", [0, -1, 2**31])
def test_id_fuera_de_rango_422(client, id):
    r = client.get(f"/equipos/{id}")
    assert r.status_code == 422


def test_nombre_con_nul_422(client):
    r = client.post("/equipos", json={"nombre": "a\x00b", "esAdmin": False})
    assert r.status_code == 422
    assert r.json()["errores"][0]["campo"] == "nombre"


def test_nombre_duplicado_409(client):
    # Arrange
    cuerpo = _cuerpo()
    client.post("/equipos", json=cuerpo)

    # Act
    r = client.post("/equipos", json=cuerpo)

    # Assert
    assert r.status_code == 409
    assert r.json() == {"mensaje": "Ya existe un equipo con ese nombre"}


def test_cuerpo_invalido_422(client):
    r = client.post("/equipos", json={})
    assert r.status_code == 422
    assert r.json()["mensaje"] == "Los datos enviados no cumplen las reglas establecidas"
    assert {e["campo"] for e in r.json()["errores"]} == {"nombre", "esAdmin"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "UP"}
