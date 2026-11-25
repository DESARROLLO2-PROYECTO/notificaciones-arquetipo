"""La demo por criterios contra la API real (Postgres desechable), sin Docker Compose.

Las herramientas de consola, el SQL de evidencia y los registros se resuelven en proceso, para que
el guion de cada historia siga cumpliéndose cuando el servicio cambie.
"""

import contextlib
import io
import json
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts import api_keys
from scripts.demo import criterios


def _como_psql(valor):
    """El texto que imprimiría psql -tA: t y f para los booleanos, JSON para los objetos."""
    if isinstance(valor, bool):
        return "t" if valor else "f"
    return json.dumps(valor) if isinstance(valor, dict | list) else str(valor)


class EntornoEnProceso:
    disponible = True

    def __init__(self, postgres, registros):
        self._postgres = postgres
        self._registros = registros

    def cli(self, *args):
        modulo, *resto = args
        comando = {"crear_api_key": "generar", "desactivar_api_key": "desactivar"}.get(
            modulo.rsplit(".", 1)[-1], "listar"
        )
        salida, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = api_keys.main(
                resto if comando != "listar" else ["listar"],
                comando=None if comando == "listar" else comando,
            )  # noqa: E501
        return codigo, salida.getvalue(), errores.getvalue()

    def texto_cli(self, *args):
        return f"docker compose exec -T api python -m {' '.join(args)}"

    def sql(self, consulta):
        with self._postgres.connect() as c:
            return [[_como_psql(v) for v in fila] for fila in c.execute(text(consulta)).all()]

    def registros(self):
        return self._registros()

    def parar_bd(self):
        return False

    def iniciar_bd(self):
        return True


@pytest.fixture
def entorno(postgres, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.domain.api_key_service import ApiKeyService
    from app.infrastructure.db import get_engine
    from app.infrastructure.repositories import ApiKeyRepo
    from app.main import create_app

    # Otras pruebas dejan DATABASE_URL apuntando a su propio contenedor: se apunta a este.
    monkeypatch.setenv("DATABASE_URL", postgres.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    get_engine.cache_clear()
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
    caplog.set_level(logging.INFO)
    with TestClient(create_app()) as cliente:
        yield cliente, EntornoEnProceso(postgres, lambda: caplog.text)
    with postgres.begin() as c:  # que la demo no deje datos a las pruebas que migran hacia atrás
        c.execute(text("UPDATE api_keys SET activa = false"))
        c.execute(text("TRUNCATE alertas, notificaciones"))
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.mark.parametrize("historia", ["11", "01"])
def test_cada_historia_cumple_todos_sus_criterios(entorno, historia, monkeypatch, tmp_path):
    cliente, env = entorno
    monkeypatch.chdir(tmp_path)  # sin un .demo.env propio
    lineas: list[str] = []

    codigo = criterios.main(
        ["--hu", historia, "--rapido", "--sin-color", "--sin-parar-bd", "--hilos", "1",
         "--url", "http://testserver"],
        http=cliente, entorno=env, escribir=lineas.append, leer=lambda _: "",
    )  # fmt: skip

    salida = "\n".join(lineas)
    assert codigo == 0, salida
    assert "Todo salió como se esperaba" in salida
    assert "✗" not in salida
    assert "curl equivalente" in salida


def test_solo_ejecuta_los_criterios_pedidos(entorno, monkeypatch, tmp_path):
    cliente, env = entorno
    monkeypatch.chdir(tmp_path)
    lineas: list[str] = []

    codigo = criterios.main(
        ["--hu", "01", "--solo", "2,3", "--rapido", "--sin-color", "--url", "http://testserver"],
        http=cliente, entorno=env, escribir=lineas.append, leer=lambda _: "",
    )  # fmt: skip

    salida = "\n".join(lineas)
    assert codigo == 0, salida
    assert "━━ Criterio 2" in salida and "━━ Criterio 3" in salida
    assert "━━ Criterio 1" not in salida and "━━ Criterio 4" not in salida


def test_la_historia_11_deja_las_llaves_como_estaban(entorno, monkeypatch, tmp_path):
    cliente, env = entorno
    monkeypatch.chdir(tmp_path)
    antes = env.sql("select count(*) from api_keys where activa")

    criterios.main(
        ["--hu", "11", "--rapido", "--sin-color", "--url", "http://testserver"],
        http=cliente, entorno=env, escribir=lambda _: None, leer=lambda _: "",
    )  # fmt: skip

    assert env.sql("select count(*) from api_keys where activa") == antes
