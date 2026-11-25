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


@pytest.fixture(scope="session")
def rabbitmq():
    """RabbitMQ desechable: misma versión que docker-compose.yml. Devuelve la URL AMQP."""
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    contenedor = (
        DockerContainer("rabbitmq:3.13.7-alpine")
        .with_env("RABBITMQ_DEFAULT_USER", "test")
        .with_env("RABBITMQ_DEFAULT_PASS", "test")
        .with_exposed_ports(5672)
        .waiting_for(LogMessageWaitStrategy("Server startup complete").with_startup_timeout(90))
    )
    try:
        contenedor.start()
    except Exception as exc:
        if os.environ.get("CI"):
            pytest.fail(f"RabbitMQ no arrancó en CI: {exc}")
        pytest.skip(f"Docker no disponible: {exc}")
    try:
        yield (
            f"amqp://test:test@{contenedor.get_container_host_ip()}"
            f":{contenedor.get_exposed_port(5672)}/"
        )
    finally:
        contenedor.stop()
