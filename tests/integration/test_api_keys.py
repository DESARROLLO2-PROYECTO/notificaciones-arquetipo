import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.domain.api_key_service import ApiKeyService, LimiteLlavesActivas
from app.domain.errores import NoEncontrado
from app.infrastructure.models import ApiKey, Base, Equipo
from app.infrastructure.repositories import ApiKeyRepo


@pytest.fixture(autouse=True)
def limpiar_llaves(postgres):
    with postgres.begin() as connection:
        connection.execute(text("TRUNCATE api_keys RESTART IDENTITY"))


def test_cli_generar_rotar_y_desactivar_con_persistencia_real(postgres):
    def cli(modulo, *args):
        return subprocess.run(
            [sys.executable, "-m", f"scripts.{modulo}", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def generar():
        resultado = cli("crear_api_key", "--rol", "notificaciones")
        assert resultado.returncode == 0, resultado.stderr
        lineas = resultado.stdout.splitlines()
        id = int(lineas[0].split(": ", 1)[1])
        llave = lineas[-1].split(": ", 1)[1]
        assert resultado.stdout.count(llave) == 1
        return id, llave

    id, llave = generar()
    _, segunda = generar()
    fallo = cli("crear_api_key", "--rol", "notificaciones")
    assert fallo.returncode == 1
    assert "Ya existen dos llaves activas para este rol" in fallo.stderr
    assert fallo.stdout == ""

    hash_llave = hashlib.sha256(llave.encode()).hexdigest()
    with Session(postgres) as session:
        repo = ApiKeyRepo(session)
        assert repo.obtener_rol_y_estado_por_hash(hash_llave) == ("notificaciones", True)
        registro = session.get(ApiKey, id)
        assert registro is not None
        assert registro.hash == hash_llave
        assert registro.prefijo == hash_llave[:8]
        assert registro.activa is True
        assert registro.creada_at.utcoffset().total_seconds() == 0
        assert session.get(Equipo, registro.equipo_id).nombre == "notificaciones"
        assert session.get(Equipo, registro.equipo_id).es_admin is True
        valores = session.execute(text("SELECT * FROM api_keys")).all()
        assert llave not in str(valores)
        assert segunda not in str(valores)

    baja = cli("desactivar_api_key", "--id", str(id))
    assert baja.returncode == 0
    assert llave not in baja.stdout + baja.stderr
    assert cli("desactivar_api_key", "--id", str(id)).returncode == 0
    assert cli("desactivar_api_key", "--id", "999999").returncode == 1
    with Session(postgres) as session:
        repo = ApiKeyRepo(session)
        assert repo.obtener_rol_y_estado_por_hash(hash_llave) == ("notificaciones", False)
        assert repo.obtener_rol_y_estado_por_hash("0" * 64) is None
        hash_segunda = hashlib.sha256(segunda.encode()).hexdigest()
        assert repo.obtener_rol_y_estado_por_hash(hash_segunda) == ("notificaciones", True)
        assert session.get(ApiKey, id).activa is False
    generar()


def test_generaciones_simultaneas_no_superan_dos_activas(postgres):
    barrera = Barrier(5)

    def generar(_):
        barrera.wait(timeout=10)
        try:
            with Session(postgres) as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '10s'"))
                ApiKeyService(ApiKeyRepo(session)).generar("inventario")
            return "creada"
        except LimiteLlavesActivas:
            return "limite"

    with ThreadPoolExecutor(max_workers=5) as executor:
        resultados = list(executor.map(generar, range(5)))
    assert resultados.count("creada") == 2
    assert resultados.count("limite") == 3
    with Session(postgres) as session:
        llaves = session.scalars(select(ApiKey)).all()
        assert len(llaves) == 2
        assert len({llave.hash for llave in llaves}) == 2


def test_rollback_no_deja_llave_parcial(postgres):
    with pytest.raises(RuntimeError), Session(postgres) as session, session.begin():
        ApiKeyService(ApiKeyRepo(session)).generar("fabricacion")
        raise RuntimeError("Fallo antes del commit")
    with Session(postgres) as session:
        assert session.scalars(select(ApiKey)).all() == []


def test_equipo_ausente_no_se_crea_silenciosamente(postgres):
    with Session(postgres) as session, session.begin(), pytest.raises(NoEncontrado):
        ApiKeyRepo(session).bloquear_equipo("equipo-inexistente")


def test_migracion_reversible_y_modelos_coinciden(postgres):
    config = Config("alembic.ini")
    with postgres.connect() as connection:
        equipos = connection.execute(select(Equipo.id, Equipo.nombre, Equipo.es_admin)).all()
    try:
        command.downgrade(config, "0001")
        assert "api_keys" not in inspect(postgres).get_table_names()
    finally:
        command.upgrade(config, "head")
    with postgres.connect() as connection:
        assert (
            connection.execute(select(Equipo.id, Equipo.nombre, Equipo.es_admin)).all() == equipos
        )
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_migracion_reemplaza_prefijos_antiguos_sin_invalidar_llaves(postgres):
    config = Config("alembic.ini")
    hash_llave = hashlib.sha256(b"llave-de-prueba").hexdigest()
    command.downgrade(config, "0002")
    try:
        with Session(postgres) as session, session.begin():
            equipo_id = session.scalar(select(Equipo.id).where(Equipo.nombre == "inventario"))
            registro = ApiKey(
                equipo_id=equipo_id,
                hash=hash_llave,
                prefijo="llave-de",
                activa=True,
                creada_at=datetime.now(UTC),
            )
            session.add(registro)
            session.flush()
            id = registro.id
    finally:
        command.upgrade(config, "head")

    with Session(postgres) as session:
        registro = session.get(ApiKey, id)
        assert registro is not None
        assert registro.hash == hash_llave
        assert registro.activa is True
        assert registro.prefijo == hash_llave[:8]
