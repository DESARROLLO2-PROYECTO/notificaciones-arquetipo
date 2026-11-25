"""El esquema real coincide con el ER del DAS (docs: 04 Modelo entidad-relación).

Cubre las tablas ya implementadas. Las de destinatarios, envíos de correo y callbacks se
agregan a este archivo cuando llegue su historia (HU-NOT-13, HU-NOT-04 y HU-NOT-16).
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

# tabla: {columna: (tipo base, obligatoria)}
ER: dict[str, dict[str, tuple[str, bool]]] = {
    "equipos": {
        "id": ("INTEGER", True),
        "nombre": ("VARCHAR", True),
        "es_admin": ("BOOLEAN", True),
    },
    "api_keys": {
        "id": ("INTEGER", True),
        "equipo_id": ("INTEGER", True),
        "hash": ("VARCHAR", True),
        "prefijo": ("VARCHAR", True),
        "activa": ("BOOLEAN", True),
        "creada_at": ("TIMESTAMP", True),
    },
    "tipos_notificacion": {
        "codigo": ("VARCHAR", True),
        "equipo_emisor_id": ("INTEGER", True),
        "equipo_destino_id": ("INTEGER", True),
        "schema": ("JSONB", True),
        "campo_clave": ("VARCHAR", False),
        "ttl_alerta_min": ("INTEGER", True),
        "activo": ("BOOLEAN", True),
    },
    "notificaciones": {
        "id": ("UUID", True),
        "tipo": ("VARCHAR", True),
        "equipo_emisor_id": ("INTEGER", True),
        "equipo_destino_id": ("INTEGER", True),
        "payload": ("JSONB", True),
        "creada_at": ("TIMESTAMP", True),
        "publicada_at": ("TIMESTAMP", False),
        "intentos_publicacion": ("INTEGER", True),
        "ultimo_error_publicacion": ("TEXT", False),
        "entregada_at": ("TIMESTAMP", False),
        "intentos_entrega": ("INTEGER", True),
        "proximo_intento_entrega_at": ("TIMESTAMP", False),
        "ultimo_error_entrega": ("TEXT", False),
        "leida_at": ("TIMESTAMP", False),
    },
    "alertas": {
        "id": ("INTEGER", True),
        "tipo": ("VARCHAR", True),
        "clave": ("VARCHAR", True),
        "notificacion_id": ("UUID", True),
        "creada_at": ("TIMESTAMP", True),
        "expira_at": ("TIMESTAMP", True),
        "cerrada_at": ("TIMESTAMP", False),
        "motivo_resolucion": ("VARCHAR", False),
    },
}


@pytest.mark.parametrize("tabla", ER)
def test_columnas_tipos_y_obligatoriedad_del_er(postgres, tabla):
    columnas = {c["name"]: c for c in inspect(postgres).get_columns(tabla)}

    assert set(columnas) == set(ER[tabla])
    for nombre, (tipo, obligatoria) in ER[tabla].items():
        assert str(columnas[nombre]["type"]).split("(")[0] == tipo, f"{tabla}.{nombre}: tipo"
        assert (not columnas[nombre]["nullable"]) is obligatoria, f"{tabla}.{nombre}: nulabilidad"


def test_indices_de_notificaciones_del_er(postgres):
    indices = {
        i["name"]: i["column_names"] for i in inspect(postgres).get_indexes("notificaciones")
    }

    assert indices["ix_notificaciones_creada_at"] == ["creada_at"]
    assert indices["ix_notificaciones_tipo"] == ["tipo"]
    assert indices["ix_notificaciones_equipo_destino_id"] == ["equipo_destino_id"]


def test_alertas_una_por_notificacion_y_una_activa_por_tipo_y_clave(postgres):
    inspector = inspect(postgres)
    unicas = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("alertas")}
    parcial = next(
        i for i in inspector.get_indexes("alertas") if i["name"] == "uq_alerta_activa_tipo_clave"
    )

    assert ("notificacion_id",) in unicas
    assert parcial["unique"] and parcial["column_names"] == ["tipo", "clave"]
    assert parcial["dialect_options"]["postgresql_where"] == "(cerrada_at IS NULL)"


def test_el_motivo_de_cierre_solo_admite_emisor_o_expiracion(postgres):
    with postgres.connect() as conexion:
        restricciones = conexion.execute(
            text("SELECT conname FROM pg_constraint WHERE conrelid = 'alertas'::regclass")
        ).scalars()
        assert {"ck_alertas_motivo", "ck_alertas_cierre_coherente"} <= set(restricciones)


def test_la_migracion_0007_corrige_datos_existentes(postgres):
    """Sube desde 0006 con filas como las dejaba el esquema anterior."""
    config = Config("alembic.ini")
    command.downgrade(config, "0006_tipo_condicion_urgente")
    try:
        with postgres.begin() as c:
            for clave, motivo in [("MIG-ACTIVA", "NULL"), ("MIG-CERRADA", "'emisor'")]:
                notificacion = c.execute(
                    text(
                        "INSERT INTO notificaciones (id, tipo, creada_at, intentos_publicacion, "
                        "intentos_entrega) VALUES (gen_random_uuid(), 'STOCK_BAJO_INSUMO', now(), "
                        "0, 0) RETURNING id"
                    )
                ).scalar_one()
                cierre = "NULL" if motivo == "NULL" else "now()"
                c.execute(
                    text(
                        "INSERT INTO alertas (tipo, clave, notificacion_id, creada_at, "
                        f"motivo_resolucion, resuelta_at) VALUES ('STOCK_BAJO_INSUMO', '{clave}', "
                        f":n, now(), {motivo}, {cierre})"
                    ),
                    {"n": notificacion},
                )
    finally:
        command.upgrade(config, "head")

    with postgres.connect() as c:
        filas = c.execute(
            text(
                "SELECT a.clave, a.motivo_resolucion, a.cerrada_at IS NOT NULL, "
                "a.expira_at IS NOT NULL, n.equipo_emisor_id = t.equipo_emisor_id, "
                "n.equipo_destino_id = t.equipo_destino_id, n.payload "
                "FROM alertas a JOIN notificaciones n ON n.id = a.notificacion_id "
                "JOIN tipos_notificacion t ON t.codigo = n.tipo "
                "WHERE a.clave IN ('MIG-ACTIVA', 'MIG-CERRADA') ORDER BY a.clave"
            )
        ).all()
    # emisor y destino salen del catálogo, el payload queda vacío, la alerta sin vencimiento
    # recibe uno y el motivo pasa a mayúscula
    assert [tuple(f) for f in filas] == [
        ("MIG-ACTIVA", None, False, True, True, True, {}),
        ("MIG-CERRADA", "EMISOR", True, True, True, True, {}),
    ]
