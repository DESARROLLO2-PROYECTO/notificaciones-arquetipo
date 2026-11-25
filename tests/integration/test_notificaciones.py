import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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
    assert r.json() == {"alertasCerradas": 3, "publicadas": 0, "errores": []}
    assert "Limpieza de alertas completada: 3 alertas expiradas" in caplog.text
    assert _sql(
        "SELECT motivo_resolucion FROM alertas WHERE clave = :c", c=vigente["productoId"]
    ) == [(None,)]
    assert _ciclo(client).json() == {"alertasCerradas": 0, "publicadas": 0, "errores": []}


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
        lambda: None,  # type: ignore[arg-type,return-value]
        None,  # type: ignore[arg-type]
    )
    try:
        with TestClient(app) as c:
            r = _ciclo(c)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert r.json() == {"alertasCerradas": 0, "publicadas": 0, "errores": ["alertas"]}


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


# --- HU-NOT-03: publicar en el broker ---


@pytest.fixture
def broker(rabbitmq, monkeypatch):
    from app.infrastructure.broker import PublicadorAmqp

    publicador = PublicadorAmqp(rabbitmq, timeout_s=10)
    monkeypatch.setattr("app.api.deps.obtener_publicador", lambda: publicador)
    # Aparta las pendientes de otras pruebas para que no entren en el ciclo
    _sql("UPDATE notificaciones SET intentos_publicacion = 3 WHERE publicada_at IS NULL")
    yield rabbitmq
    publicador.cerrar()


def _leer_cola(url: str, destino: str) -> list[dict]:
    import asyncio
    import json

    from tests.integration.test_broker import _leer

    return [json.loads(m.body) for m in asyncio.run(_leer(url, destino))]


def _fila(id: str):
    return _sql(
        "SELECT publicada_at, proximo_intento_entrega, intentos_publicacion, "
        "ultimo_error_publicacion FROM notificaciones WHERE id = :id",
        id=id,
    )[0]


def test_detectada_publica_en_la_cola_del_destino(client, broker):
    _leer_cola(broker, "inventario")  # vacía restos de otras pruebas

    r = _post(client, _cuerpo())

    assert r.status_code == 201
    id = r.json()["id"]
    assert _leer_cola(broker, "inventario") == [{"id": id, "tipo": "STOCK_BAJO_INSUMO"}]
    publicada_at, proximo, intentos, error = _fila(id)
    assert proximo - publicada_at == timedelta(minutes=5)
    assert (intentos, error) == (0, None)


def test_broker_no_disponible_responde_201_y_queda_pendiente(client, monkeypatch):
    from app.infrastructure.broker import PublicadorAmqp

    caido = PublicadorAmqp("amqp://x:x@127.0.0.1:1/", timeout_s=1)
    monkeypatch.setattr("app.api.deps.obtener_publicador", lambda: caido)

    r = _post(client, _cuerpo())
    caido.cerrar()

    assert r.status_code == 201
    publicada_at, proximo, intentos, error = _fila(r.json()["id"])
    assert (publicada_at, proximo, intentos) == (None, None, 1)
    assert error == "No fue posible publicar en la cola (AMQPConnectionError)"


def test_ciclo_publica_las_pendientes_de_mas_de_un_minuto(client, broker):
    _leer_cola(broker, "inventario")
    ids = []
    for _ in range(2):
        ids.append(_post(client, _cuerpo()).json()["id"])
    # Una pendiente vieja, otra reciente y otra ya publicada que no debe repetirse
    _sql("UPDATE notificaciones SET publicada_at = NULL WHERE id = :id", id=ids[0])
    _sql(
        "UPDATE notificaciones SET creada_at = now() - interval '2 minutes' WHERE id = :id",
        id=ids[0],
    )
    _sql("UPDATE notificaciones SET publicada_at = NULL WHERE id = :id", id=ids[1])
    _leer_cola(broker, "inventario")  # solo importa lo que publique el ciclo

    r = _ciclo(client)

    assert r.json() == {"alertasCerradas": 0, "publicadas": 1, "errores": []}
    assert [m["id"] for m in _leer_cola(broker, "inventario")] == [ids[0]]
    assert _fila(ids[0])[0] is not None
    assert _fila(ids[1])[0] is None
    assert _ciclo(client).json()["publicadas"] == 0


def test_ciclos_simultaneos_publican_cada_notificacion_una_vez(app, client, broker):
    from fastapi.testclient import TestClient

    ids = [_post(client, _cuerpo()).json()["id"] for _ in range(6)]
    for id in ids:
        _sql(
            "UPDATE notificaciones SET publicada_at = NULL, "
            "creada_at = now() - interval '2 minutes' WHERE id = :id",
            id=id,
        )
    _leer_cola(broker, "inventario")

    def correr():
        with TestClient(app) as c:
            return _ciclo(c).json()["publicadas"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        publicadas = [f.result() for f in [pool.submit(correr), pool.submit(correr)]]

    assert sum(publicadas) == 6
    assert sorted(m["id"] for m in _leer_cola(broker, "inventario")) == sorted(ids)


# --- HU-NOT-05: condición urgente ---

MENSAJE_CU_INVALIDA = "Información de la condición urgente incompleta o inválida"


def _cu(**cambios) -> dict:
    base = {
        "tipo": "CONDICION_URGENTE",
        "codigoCondicion": f"CU-{uuid4().hex[:10]}",
        "descripcion": "Horno por encima de la temperatura máxima",
    }
    base.update(cambios)
    return base


def test_condicion_urgente_201_se_publica_en_la_cola_de_fabricacion(client, broker):
    _leer_cola(broker, "fabricacion")  # vacía restos de otras pruebas
    cuerpo = _cu()

    r = _post(client, cuerpo, rol="fabricacion")

    assert r.status_code == 201
    id = r.json()["id"]
    assert r.json()["mensaje"] == "Notificación registrada correctamente"
    assert _leer_cola(broker, "fabricacion") == [{"id": id, "tipo": "CONDICION_URGENTE"}]
    (fila,) = _sql(
        "SELECT payload, creada_at FROM notificaciones WHERE id = :id",
        id=id,
    )
    assert fila[0]["codigoCondicion"] == cuerpo["codigoCondicion"]
    assert fila[0]["descripcion"] == cuerpo["descripcion"]
    assert "mensaje" not in fila[0]


def test_condicion_urgente_duplicada_200_con_id_original(client):
    cuerpo = _cu()
    creada = _post(client, cuerpo, rol="fabricacion").json()

    r = _post(client, cuerpo, rol="fabricacion")

    assert r.status_code == 200
    assert r.json() == {
        "id": creada["id"],
        "duplicada": True,
        "mensaje": "Ya existe una alerta activa para esta condición",
    }


def test_condicion_urgente_resuelta_y_nueva_detectada_201(client):
    cuerpo = _cu()
    primera = _post(client, cuerpo, rol="fabricacion").json()

    resuelta = _post(client, {**cuerpo, "evento": "RESUELTA"}, rol="fabricacion")
    nueva = _post(client, cuerpo, rol="fabricacion")

    assert resuelta.status_code == 200
    assert resuelta.json() == {"mensaje": "Alerta resuelta correctamente"}
    assert nueva.status_code == 201
    assert nueva.json()["id"] != primera["id"]


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"codigoCondicion": ""}, "codigoCondicion"),
        ({"codigoCondicion": "A" * 31}, "codigoCondicion"),
        ({"codigoCondicion": "TEMP 01"}, "codigoCondicion"),
        ({"descripcion": ""}, "descripcion"),
        ({"descripcion": "   "}, "descripcion"),
        ({"descripcion": "x" * 101}, "descripcion"),
    ],
)
def test_condicion_urgente_invalida_422(client, cambios, campo):
    r = _post(client, _cu(**cambios), rol="fabricacion")

    assert r.status_code == 422
    assert r.json()["mensaje"] == MENSAJE_CU_INVALIDA
    assert [e["campo"] for e in r.json()["errores"]] == [campo]


@pytest.mark.parametrize("faltante", ["codigoCondicion", "descripcion"])
def test_condicion_urgente_incompleta_422(client, faltante):
    cuerpo = _cu()
    del cuerpo[faltante]

    r = _post(client, cuerpo, rol="fabricacion")

    assert r.status_code == 422
    assert r.json()["mensaje"] == MENSAJE_CU_INVALIDA
    assert [e["campo"] for e in r.json()["errores"]] == [faltante]


def test_condicion_urgente_con_llave_de_inventario_403(client):
    r = _post(client, _cu(), rol="inventario")

    assert r.status_code == 403


def test_migracion_0006_siembra_condicion_urgente(_setup_db):
    from alembic import command
    from alembic.config import Config

    consulta = (
        "SELECT t.campo_clave, t.ttl_alerta_min, e.nombre, d.nombre, t.activo "
        "FROM tipos_notificacion t "
        "JOIN equipos e ON e.id = t.equipo_emisor_id "
        "JOIN equipos d ON d.id = t.equipo_destino_id "
        "WHERE t.codigo = 'CONDICION_URGENTE'"
    )
    assert [tuple(f) for f in _sql(consulta)] == [
        ("codigoCondicion", 60, "fabricacion", "fabricacion", True)
    ]
    config = Config("alembic.ini")
    # El downgrade no puede borrar un tipo con notificaciones registradas
    _sql("DELETE FROM alertas WHERE tipo = 'CONDICION_URGENTE'")
    _sql("DELETE FROM notificaciones WHERE tipo = 'CONDICION_URGENTE'")
    try:
        command.downgrade(config, "0005_resuelta_at_alertas")
        assert _sql(consulta) == []
    finally:
        command.upgrade(config, "head")
    assert len(_sql(consulta)) == 1
