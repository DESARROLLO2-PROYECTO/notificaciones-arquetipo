"""PostgreSQL desechable compartido por la suite de integración."""

import os

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres():
    try:
        contenedor = PostgresContainer("postgres:16.15-alpine", driver="psycopg")
        contenedor.start()
    except Exception as exc:
        if os.environ.get("CI"):
            pytest.fail(f"Postgres no arrancó en CI: {exc}")
        pytest.skip(f"Docker no disponible: {exc}")

    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    from app.infrastructure.db import get_engine

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", contenedor.get_connection_url())
        get_settings.cache_clear()
        get_engine.cache_clear()
        try:
            command.upgrade(Config("alembic.ini"), "head")
            yield get_engine()
        finally:
            get_engine().dispose()
            get_engine.cache_clear()
            get_settings.cache_clear()
            contenedor.stop()
