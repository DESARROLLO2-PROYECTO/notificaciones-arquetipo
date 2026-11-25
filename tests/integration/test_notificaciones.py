import os
from concurrent.futures import ThreadPoolExecutor
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


LLAVES: dict[str, str] = {}


@pytest.fixture(scope="module")
def _setup_db(_postgres):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

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
        conn.execute(
            text(
                """
                INSERT INTO tipos_notificacion
                    (codigo, campo_clave, ttl_alerta_min, activo, 
                    equipo_emisor_id, equipo_destino_id)
                VALUES
                    ('TIPO_INACTIVO_TEST', 'productoId', 60, false, :inv, :inv)
                ON CONFLICT (codigo) DO UPDATE SET
                    equipo_emisor_id = EXCLUDED.equipo_emisor_id,
                    equipo_destino_id = EXCLUDED.equipo_destino_id,
                    activo = EXCLUDED.activo
                """
            ),
            {"inv": inv_id},
        )
    engine.dispose()

    from app.domain.api_key_service import ApiKeyService
    from app.infrastructure.repositories import ApiKeyRepo

    with Session(get_engine()) as session, session.begin():
        servicio = ApiKeyService(ApiKeyRepo(session))
        for rol in ("inventario", "fabricacion", "notificaciones"):
            LLAVES[rol] = servicio.generar(rol).llave


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


def _post(client, cuerpo: dict, rol: str = "inventario"):
    return client.post("/notificaciones", headers={"X-API-Key": LLAVES[rol]}, json=cuerpo)


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


# --- HU-NOT-12 sobre POST /notificaciones: la llave identifica al emisor ---


def test_sin_llave_401(client):
    r = client.post("/notificaciones", json=_cuerpo())

    assert r.status_code == 401
    assert r.json() == {"mensaje": "Acceso denegado"}


def test_llave_invalida_401(client):
    r = client.post("/notificaciones", headers={"X-API-Key": "no-existe"}, json=_cuerpo())

    assert r.status_code == 401


def test_llave_en_la_url_se_ignora_401(client):
    r = client.post(f"/notificaciones?api_key={LLAVES['inventario']}", json=_cuerpo())

    assert r.status_code == 401


def test_emisor_distinto_al_del_tipo_403_y_no_registra(client):
    # Arrange: STOCK_BAJO_INSUMO lo emite inventario, no fabricacion
    cuerpo = _cuerpo()

    # Act
    r = _post(client, cuerpo=cuerpo, rol="fabricacion")
    reintento = _post(client, cuerpo=cuerpo)  # con la llave correcta sí se registra

    # Assert
    assert r.status_code == 403
    assert r.json() == {"mensaje": "Acceso denegado"}
    assert reintento.status_code == 201


def test_403_deja_el_motivo_y_el_rol_en_el_log_sin_la_llave(client, caplog):
    caplog.set_level("WARNING")

    _post(client, cuerpo=_cuerpo(), rol="fabricacion")

    assert "RECHAZADA 403 endpoint=POST /notificaciones motivo=emisor no permitido" in caplog.text
    assert "rol=fabricacion" in caplog.text
    assert LLAVES["fabricacion"] not in caplog.text


def test_catalogo_de_stock_bajo_lo_siembra_la_migracion(_setup_db):
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                """
                SELECT t.codigo, e.nombre, d.nombre, t.campo_clave, t.ttl_alerta_min, t.activo
                FROM tipos_notificacion t
                JOIN equipos e ON e.id = t.equipo_emisor_id
                JOIN equipos d ON d.id = t.equipo_destino_id
                WHERE t.codigo LIKE 'STOCK_BAJO_%'
                ORDER BY t.codigo
                """
            )
        ).all()
    engine.dispose()

    assert [tuple(f) for f in filas] == [
        ("STOCK_BAJO_INSUMO", "inventario", "inventario", "productoId", 1440, True),
        ("STOCK_BAJO_PRODUCTO", "inventario", "fabricacion", "productoId", 1440, True),
    ]


def test_colision_de_alerta_activa_en_flush_se_traduce_a_error_de_concurrencia(_setup_db):
    from sqlalchemy.orm import Session

    from app.domain import puertos
    from app.domain.errores import ErrorConcurrenciaAlerta
    from app.infrastructure.db import get_engine
    from app.infrastructure.repositories import AlertaRepo, NotificacionRepo

    clave = f"COL-{uuid4().hex[:10]}"
    with Session(get_engine()) as session:
        notificaciones = NotificacionRepo(session)
        alertas = AlertaRepo(session)
        primera = notificaciones.crear(puertos.Notificacion(tipo="STOCK_BAJO_INSUMO"))
        segunda = notificaciones.crear(puertos.Notificacion(tipo="STOCK_BAJO_INSUMO"))
        alertas.crear(
            puertos.Alerta(tipo="STOCK_BAJO_INSUMO", clave=clave, notificacion_id=primera.id)
        )

        with pytest.raises(ErrorConcurrenciaAlerta):
            alertas.crear(
                puertos.Alerta(tipo="STOCK_BAJO_INSUMO", clave=clave, notificacion_id=segunda.id)
            )
        session.rollback()


# --- HU-NOT-02: resolver alertas y ciclo de limpieza ---


def _sql(sentencia: str, **params):
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        resultado = conn.execute(text(sentencia), params)
        filas = resultado.all() if resultado.returns_rows else None
    engine.dispose()
    return filas


def _vencer(clave: str) -> None:
    _sql(
        "UPDATE alertas SET expira_at = now() - interval '1 minute' "
        "WHERE clave = :clave AND motivo_resolucion IS NULL",
        clave=clave,
    )


def _ciclo(client, rol: str = "notificaciones"):
    return client.post("/notificaciones/ciclo", headers={"X-API-Key": LLAVES[rol]})


@pytest.mark.parametrize("evento", ["REPUESTO", "RESUELTA"])
def test_evento_de_resolucion_cierra_la_alerta_200(client, evento):
    cuerpo = _cuerpo()
    creada = _post(client, cuerpo).json()

    r = _post(client, {**cuerpo, "evento": evento})

    assert r.status_code == 200
    assert r.json() == {"mensaje": "Alerta resuelta correctamente"}
    (fila,) = _sql(
        "SELECT motivo_resolucion, resuelta_at FROM alertas WHERE notificacion_id = :id",
        id=creada["id"],
    )
    assert fila[0] == "emisor"
    assert fila[1] is not None
    assert _sql("SELECT count(*) FROM notificaciones WHERE id = :id", id=creada["id"]) == [(1,)]


def test_resolver_sin_alerta_activa_200_sin_cambios(client):
    cuerpo = _cuerpo(evento="REPUESTO")
    antes = _sql("SELECT count(*) FROM notificaciones")

    r = _post(client, cuerpo)

    assert r.status_code == 200
    assert r.json() == {"mensaje": "No había una alerta activa"}
    assert _sql("SELECT count(*) FROM notificaciones") == antes
    assert _sql("SELECT count(*) FROM alertas WHERE clave = :c", c=cuerpo["productoId"]) == [(0,)]


def test_resolver_con_emisor_distinto_403(client):
    cuerpo = _cuerpo()
    _post(client, cuerpo)

    r = _post(client, {**cuerpo, "evento": "RESUELTA"}, rol="fabricacion")

    assert r.status_code == 403


def test_detectada_tras_resolver_crea_otra_notificacion_201(client):
    cuerpo = _cuerpo()
    primera = _post(client, cuerpo).json()
    _post(client, {**cuerpo, "evento": "RESUELTA"})

    r = _post(client, cuerpo)

    assert r.status_code == 201
    assert r.json()["id"] != primera["id"]


def test_detectada_con_alerta_vencida_sin_limpiar_201(client):
    cuerpo = _cuerpo()
    primera = _post(client, cuerpo).json()
    _vencer(cuerpo["productoId"])

    r = _post(client, cuerpo)

    assert r.status_code == 201
    assert r.json()["id"] != primera["id"]
    motivos = _sql(
        "SELECT motivo_resolucion FROM alertas WHERE clave = :c ORDER BY id",
        c=cuerpo["productoId"],
    )
    assert motivos == [("expiracion",), (None,)]


def test_ciclo_cierra_las_vencidas_y_registra_el_resumen(client, caplog):
    caplog.set_level("INFO")
    # El ciclo cierra todas las vencidas: se vacía la tabla de las de otras pruebas
    _sql("UPDATE alertas SET motivo_resolucion = 'emisor' WHERE motivo_resolucion IS NULL")
    claves = []
    for _ in range(3):
        cuerpo = _cuerpo()
        _post(client, cuerpo)
        claves.append(cuerpo["productoId"])
    vigente = _cuerpo()
    _post(client, vigente)
    for clave in claves:
        _vencer(clave)

    r = _ciclo(client)

    assert r.status_code == 200
    assert r.json() == {"alertasCerradas": 3, "errores": []}
    assert "Limpieza de alertas completada: 3 alertas expiradas" in caplog.text
    assert _sql(
        "SELECT motivo_resolucion FROM alertas WHERE clave = :c", c=vigente["productoId"]
    ) == [(None,)]
    assert _ciclo(client).json() == {"alertasCerradas": 0, "errores": []}


def test_ciclo_con_tarea_fallida_responde_200_con_errores(app):
    from fastapi.testclient import TestClient

    from app.api.deps import get_servicio_notificaciones
    from app.domain.notificacion_service import ServicioNotificaciones

    class ServicioConTareaRota(ServicioNotificaciones):
        def _tareas_ciclo(self):
            def rota() -> int:
                raise RuntimeError("falla simulada")

            return (("alertas", rota),)

    app.dependency_overrides[get_servicio_notificaciones] = lambda: ServicioConTareaRota(
        lambda: None  # type: ignore[arg-type,return-value]
    )
    try:
        with TestClient(app) as c:
            r = _ciclo(c)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"alertasCerradas": 0, "errores": ["alertas"]}


def test_ciclo_con_llave_de_otro_rol_403(client):
    r = _ciclo(client, rol="inventario")

    assert r.status_code == 403
    assert r.json() == {"mensaje": "Acceso denegado"}


def test_ciclo_sin_llave_401(client):
    assert client.post("/notificaciones/ciclo").status_code == 401


def test_ciclos_simultaneos_no_cierran_dos_veces_la_misma_alerta(app, client):
    from fastapi.testclient import TestClient

    _sql("UPDATE alertas SET motivo_resolucion = 'emisor' WHERE motivo_resolucion IS NULL")
    for _ in range(10):
        cuerpo = _cuerpo()
        _post(client, cuerpo)
        _vencer(cuerpo["productoId"])

    def correr():
        with TestClient(app) as c:
            return _ciclo(c).json()["alertasCerradas"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        cerradas = [f.result() for f in [pool.submit(correr), pool.submit(correr)]]

    assert sum(cerradas) == 10


def test_migracion_0005_agrega_y_quita_resuelta_at(_setup_db):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    config = Config("alembic.ini")
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        command.downgrade(config, "0004_catalogo_tipos")
        assert "resuelta_at" not in {c["name"] for c in inspect(engine).get_columns("alertas")}
    finally:
        command.upgrade(config, "head")
    assert "resuelta_at" in {c["name"] for c in inspect(engine).get_columns("alertas")}
    engine.dispose()
