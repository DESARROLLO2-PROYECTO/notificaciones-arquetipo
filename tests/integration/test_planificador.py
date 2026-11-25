"""El planificador contra Postgres y RabbitMQ reales: cierra lo vencido y publica lo pendiente."""

import json

from sqlalchemy import text

from scripts import planificador


def test_un_ciclo_cierra_alertas_vencidas_y_publica_pendientes(postgres, rabbitmq, monkeypatch):
    from app.config import get_settings
    from app.infrastructure.broker import PublicadorAmqp
    from app.infrastructure.db import get_engine
    from tests.integration.test_broker import _leer

    # Otras pruebas dejan DATABASE_URL apuntando a su propio contenedor: se apunta a este.
    monkeypatch.setenv("DATABASE_URL", postgres.url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    get_engine.cache_clear()

    inventario = None
    with postgres.begin() as c:
        inventario = c.execute(
            text("SELECT id FROM equipos WHERE nombre = 'inventario'")
        ).scalar_one()
        ids = {}
        for clave, vencida in (("PLAN-VENCIDA", True), ("PLAN-PENDIENTE", False)):
            n = c.execute(
                text(
                    "INSERT INTO notificaciones (id, tipo, creada_at, intentos_publicacion, "
                    "intentos_entrega, equipo_emisor_id, equipo_destino_id, payload) VALUES "
                    "(gen_random_uuid(), 'STOCK_BAJO_INSUMO', now() - interval '3 minutes', 0, 0, "
                    ":e, :e, '{}') RETURNING id"
                ),
                {"e": inventario},
            ).scalar_one()
            ids[clave] = str(n)
            c.execute(
                text(
                    "INSERT INTO alertas (tipo, clave, notificacion_id, creada_at, expira_at) "
                    "VALUES ('STOCK_BAJO_INSUMO', :k, :n, now(), "
                    "now() + (CASE WHEN :v THEN interval '-1 minute' ELSE interval '1 hour' END))"
                ),
                {"k": clave, "n": n, "v": vencida},
            )
        # que solo estas dos entren al ciclo: aparta cualquier pendiente de otras pruebas
        c.execute(
            text(
                "UPDATE notificaciones SET intentos_publicacion = 3 "
                "WHERE publicada_at IS NULL AND id NOT IN (:a, :b)"
            ),
            {"a": ids["PLAN-VENCIDA"], "b": ids["PLAN-PENDIENTE"]},
        )

    publicador = PublicadorAmqp(rabbitmq, timeout_s=10)
    monkeypatch.setattr("app.api.deps.obtener_publicador", lambda: publicador)
    try:
        import asyncio

        codigo = planificador.main(["--una-vez"])
        publicados = [json.loads(m.body)["id"] for m in asyncio.run(_leer(rabbitmq, "inventario"))]
    finally:
        publicador.cerrar()

    assert codigo == 0
    with postgres.connect() as c:
        cierre = c.execute(
            text(
                "SELECT motivo_resolucion, cerrada_at IS NOT NULL "
                "FROM alertas WHERE clave = 'PLAN-VENCIDA'"
            )
        ).one()
        publicada = c.execute(
            text("SELECT publicada_at IS NOT NULL FROM notificaciones WHERE id = :i"),
            {"i": ids["PLAN-PENDIENTE"]},
        ).scalar_one()
    assert tuple(cierre) == ("EXPIRACION", True)
    assert publicada is True
    assert ids["PLAN-PENDIENTE"] in publicados
