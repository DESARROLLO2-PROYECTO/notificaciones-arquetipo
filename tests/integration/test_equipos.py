"""Flujo de punta a punta con Postgres real (testcontainers). Sin Docker, se omite (en CI falla)."""

from uuid import uuid4

import pytest


@pytest.fixture(scope="module")
def client(postgres):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.domain.api_key_service import ApiKeyService
    from app.infrastructure.api_key_repository import ApiKeyRepo
    from app.main import create_app

    with Session(postgres) as session, session.begin():
        llave = ApiKeyService(ApiKeyRepo(session)).generar("notificaciones").llave

    with TestClient(create_app(), headers={"X-API-Key": llave}) as c:
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
