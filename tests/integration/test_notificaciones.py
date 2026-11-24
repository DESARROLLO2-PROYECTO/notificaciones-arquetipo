from concurrent.futures import ThreadPoolExecutor
import os
from uuid import UUID, uuid4

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
        if os.environ.get("CI"):
            pytest.fail(f"Postgres no arrancó en CI: {e}")
        pytest.skip(f"Docker no disponible: {e}")
    os.environ["DATABASE_URL"] = contenedor.get_connection_url()
    yield
    contenedor.stop()


EMISOR_ID: int = 1


@pytest.fixture(scope="module")
def _setup_db(_postgres):
    global EMISOR_ID
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app.config import get_settings
    from app.infrastructure.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()

    command.upgrade(Config("alembic.ini"), "head")

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO equipos (nombre, es_admin)
                VALUES ('inventario', false), ('fabricacion', false)
                ON CONFLICT DO NOTHING
                """
            )
        )
        inv_id = conn.execute(
            text("SELECT id FROM equipos WHERE nombre = 'inventario'")
        ).scalar_one()
        fab_id = conn.execute(
            text("SELECT id FROM equipos WHERE nombre = 'fabricacion'")
        ).scalar_one()

        EMISOR_ID = inv_id

        conn.execute(
            text(
                """
                INSERT INTO tipos_notificacion
                    (codigo, campo_clave, ttl_alerta_min, activo, equipo_emisor_id, equipo_destino_id)
                VALUES
                    ('STOCK_BAJO_INSUMO', 'productoId', 60, true, :inv, :inv),
                    ('STOCK_BAJO_PRODUCTO', 'productoId', 60, true, :inv, :fab),
                    ('TIPO_INACTIVO_TEST', 'productoId', 60, false, :inv, :inv)
                ON CONFLICT (codigo) DO UPDATE SET
                    equipo_emisor_id = EXCLUDED.equipo_emisor_id,
                    equipo_destino_id = EXCLUDED.equipo_destino_id,
                    activo = EXCLUDED.activo
                """
            ),
            {"inv": inv_id, "fab": fab_id},
        )
    engine.dispose()


@pytest.fixture(scope="module")
def app(_setup_db):
    from app.main import create_app

    return create_app()


@pytest.fixture(scope="module")
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _cuerpo(**cambios) -> dict:
    base = {
        "tipo": "STOCK_BAJO_INSUMO",
        "evento": "DETECTADA",
        "productoId": f"INS-{uuid4().hex[:10]}",
        "nombre": "Acero inoxidable 304",
        "stockActual": 4,
        "stockMinimo": 10,
    }
    base.update(cambios)
    return base

def _post(client, cuerpo: dict, emisor_id: int | None = None):
    eid = EMISOR_ID if emisor_id is None else emisor_id
    return client.post("/notificaciones", params={"equipo_emisor_id": eid}, json=cuerpo)


# --- Criterio 2: Registro exitoso (HTTP 201) ---


def test_registrar_notificacion_201(client):
    # Arrange
    cuerpo = _cuerpo()

    # Act
    r = _post(client, cuerpo=cuerpo)
    data = r.json()

    # Assert
    assert r.status_code == 201
    assert data["mensaje"] == "Notificación registrada correctamente"
    assert UUID(data["id"])  # Valida que 'id' sea un UUID válido


# --- Criterio 3: Alerta ya activa / reintento (HTTP 200) ---


def test_registrar_duplicada_con_alerta_activa_200(client):
    # Arrange
    cuerpo = _cuerpo()
    primera = _post(client, cuerpo=cuerpo)
    assert primera.status_code == 201
    id_original = primera.json()["id"]

    # Act (segundo envío con el mismo tipo y productoId)
    segunda = _post(client, cuerpo=cuerpo | {"stockActual": 2})
    data = segunda.json()

    # Assert
    assert segunda.status_code == 200
    assert data == {
        "id": id_original,
        "duplicada": True,
        "mensaje": "Ya existe una alerta activa para este artículo",
    }


def test_mismo_producto_con_distinto_tipo_crea_201(client):
    # Arrange
    prod_id = f"PROD-{uuid4().hex[:8]}"
    r1 = _post(client, cuerpo=_cuerpo(tipo="STOCK_BAJO_INSUMO", productoId=prod_id))

    # Act
    r2 = _post(client, cuerpo=_cuerpo(tipo="STOCK_BAJO_PRODUCTO", productoId=prod_id))

    # Assert
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


# --- Criterio 4: Validación de forma y catálogo (HTTP 422) ---


def test_cuerpo_vacio_422(client):
    r = _post(client, cuerpo={})
    data = r.json()

    assert r.status_code == 422
    assert data["mensaje"] == "Los datos enviados no cumplen las reglas establecidas"
    assert {e["campo"] for e in data["errores"]} == {
        "tipo",
        "productoId",
        "nombre",
        "stockActual",
        "stockMinimo",
    }


@pytest.mark.parametrize(
    ("cambios", "campo_esperado"),
    [
        ({"productoId": "INS 001"}, "productoId"),
        ({"productoId": "A" * 51}, "productoId"),
        ({"nombre": ""}, "nombre"),
        ({"nombre": "x" * 101}, "nombre"),
        ({"stockActual": -1}, "stockActual"),
        ({"stockActual": 10.5}, "stockActual"),
        ({"stockMinimo": 1_000_001}, "stockMinimo"),
        ({"evento": "INVALIDO"}, "evento"),
    ],
)
def test_reglas_de_forma_invalidas_422(client, cambios, campo_esperado):
    # Act
    r = _post(client, cuerpo=_cuerpo(**cambios))
    data = r.json()

    # Assert
    assert r.status_code == 422
    assert data["mensaje"] == "Los datos enviados no cumplen las reglas establecidas"
    assert any(e["campo"] == campo_esperado for e in data["errores"])


@pytest.mark.parametrize("tipo_invalido", ["TIPO_INEXISTENTE", "TIPO_INACTIVO_TEST"])
def test_tipo_fuera_de_catalogo_o_inactivo_422(client, tipo_invalido):
    # Act
    r = _post(client, cuerpo=_cuerpo(tipo=tipo_invalido))
    data = r.json()

    # Assert
    assert r.status_code == 422
    assert data["mensaje"] == "Los datos enviados no cumplen las reglas establecidas"
    assert data["errores"][0]["campo"] == "tipo"


# --- Criterio 5: No valida coherencia de negocio entre stockActual y stockMinimo ---


def test_stock_actual_mayor_o_igual_a_minimo_se_procesa_201(client):
    # Arrange
    cuerpo = _cuerpo(stockActual=100, stockMinimo=10)

    # Act
    r = _post(client, cuerpo=cuerpo)

    # Assert
    assert r.status_code == 201
    assert r.json()["mensaje"] == "Notificación registrada correctamente"


# --- Criterio 6: Solicitudes simultáneas concurrentes (201 + 200 con mismo id) ---


def test_solicitudes_concurrentes_simultaneas_201_y_200(app):
    from fastapi.testclient import TestClient

    cuerpo = _cuerpo()

    def enviar():
        with TestClient(app) as c:
            return _post(c, cuerpo=cuerpo)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(enviar), pool.submit(enviar)]
        respuestas = [f.result() for f in futuros]

    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [200, 201]

    creada = next(r.json() for r in respuestas if r.status_code == 201)
    duplicada = next(r.json() for r in respuestas if r.status_code == 200)

    assert duplicada["id"] == creada["id"]
    assert duplicada["duplicada"] is True
    assert duplicada["mensaje"] == "Ya existe una alerta activa para este artículo"


# --- Criterio 7: Falla interna devuelve HTTP 500 con mensaje exacto ---


def test_falla_interna_500(app):
    from fastapi.testclient import TestClient
    from app.api.deps import get_servicio_notificaciones

    class ServicioRoto:
        def registrar_notificacion(self, *args, **kwargs):
            raise RuntimeError("Falla simulada de base de datos")

    app.dependency_overrides[get_servicio_notificaciones] = lambda: ServicioRoto()
    try:
        # raise_server_exceptions=False permite que TestClient capture el 500 del handler global
        with TestClient(app, raise_server_exceptions=False) as c:
            r = _post(c, cuerpo=_cuerpo())
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 500
    assert r.json() == {"mensaje": "No fue posible registrar la notificación, intente de nuevo"}