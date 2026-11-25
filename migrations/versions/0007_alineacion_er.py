"""alinea el modelo con el ER del DAS

Revision ID: 0007_alineacion_er
Revises: 0006_tipo_condicion_urgente
Create Date: 2026-11-26

Nombres (cerrada_at, proximo_intento_entrega_at), entregada_at, restricciones NOT NULL y
UNIQUE, jsonb, indices de notificaciones y motivos en mayuscula, como en el diagrama.
Las tablas de destinatarios, envios de correo y callbacks llegan con sus historias.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_alineacion_er"
down_revision: str | Sequence[str] | None = "0006_tipo_condicion_urgente"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVA_NUEVA = "cerrada_at IS NULL"
_ACTIVA_ANTERIOR = "motivo_resolucion IS NULL"


def upgrade() -> None:
    # --- alertas
    op.alter_column("alertas", "resuelta_at", new_column_name="cerrada_at")
    op.execute("UPDATE alertas SET motivo_resolucion = upper(motivo_resolucion)")
    # Una alerta con motivo pero sin fecha de cierre (p. ej. tras bajar y subir 0005) no cuenta
    # como activa: se le da una fecha para que el indice unico parcial la excluya.
    op.execute(
        "UPDATE alertas SET cerrada_at = CASE WHEN motivo_resolucion = 'EXPIRACION' "
        "THEN expira_at ELSE creada_at END "
        "WHERE motivo_resolucion IS NOT NULL AND cerrada_at IS NULL"
    )
    op.drop_index(
        "uq_alerta_activa_tipo_clave",
        table_name="alertas",
        postgresql_where=_ACTIVA_ANTERIOR,
    )
    op.create_index(
        "uq_alerta_activa_tipo_clave",
        "alertas",
        ["tipo", "clave"],
        unique=True,
        postgresql_where=_ACTIVA_NUEVA,
    )
    # Una alerta sin vencimiento (TTL 0) ya no existe: se le da el plazo por defecto.
    op.execute(
        "UPDATE alertas SET expira_at = creada_at + interval '24 hours' WHERE expira_at IS NULL"
    )
    op.alter_column("alertas", "expira_at", nullable=False)
    op.create_unique_constraint("uq_alertas_notificacion_id", "alertas", ["notificacion_id"])
    op.create_check_constraint(
        "ck_alertas_motivo", "alertas", "motivo_resolucion IN ('EMISOR', 'EXPIRACION')"
    )
    op.create_check_constraint(
        "ck_alertas_cierre_coherente",
        "alertas",
        "(cerrada_at IS NULL) = (motivo_resolucion IS NULL)",
    )

    # --- tipos_notificacion
    op.execute("UPDATE tipos_notificacion SET schema = '[]' WHERE schema IS NULL")
    op.alter_column(
        "tipos_notificacion",
        "schema",
        type_=postgresql.JSONB(),
        postgresql_using="schema::jsonb",
        nullable=False,
    )
    op.alter_column("tipos_notificacion", "equipo_emisor_id", nullable=False)
    op.alter_column("tipos_notificacion", "equipo_destino_id", nullable=False)
    op.alter_column("tipos_notificacion", "campo_clave", nullable=True)  # sin clave: una alerta
    op.create_check_constraint("ck_tipos_ttl_positivo", "tipos_notificacion", "ttl_alerta_min >= 1")

    # --- notificaciones
    op.execute(
        "UPDATE notificaciones n SET equipo_emisor_id = t.equipo_emisor_id "
        "FROM tipos_notificacion t WHERE n.tipo = t.codigo AND n.equipo_emisor_id IS NULL"
    )
    op.execute(
        "UPDATE notificaciones n SET equipo_destino_id = t.equipo_destino_id "
        "FROM tipos_notificacion t WHERE n.tipo = t.codigo AND n.equipo_destino_id IS NULL"
    )
    op.execute("UPDATE notificaciones SET payload = '{}' WHERE payload IS NULL")
    op.alter_column(
        "notificaciones",
        "payload",
        type_=postgresql.JSONB(),
        postgresql_using="payload::jsonb",
        nullable=False,
    )
    op.alter_column("notificaciones", "equipo_emisor_id", nullable=False)
    op.alter_column("notificaciones", "equipo_destino_id", nullable=False)
    op.alter_column(
        "notificaciones", "proximo_intento_entrega", new_column_name="proximo_intento_entrega_at"
    )
    op.add_column("notificaciones", _entregada_at())
    op.create_index("ix_notificaciones_creada_at", "notificaciones", ["creada_at"])
    op.create_index("ix_notificaciones_tipo", "notificaciones", ["tipo"])
    op.create_index("ix_notificaciones_equipo_destino_id", "notificaciones", ["equipo_destino_id"])


def downgrade() -> None:
    # --- notificaciones
    op.drop_index("ix_notificaciones_equipo_destino_id", table_name="notificaciones")
    op.drop_index("ix_notificaciones_tipo", table_name="notificaciones")
    op.drop_index("ix_notificaciones_creada_at", table_name="notificaciones")
    op.drop_column("notificaciones", "entregada_at")
    op.alter_column(
        "notificaciones", "proximo_intento_entrega_at", new_column_name="proximo_intento_entrega"
    )
    op.alter_column("notificaciones", "equipo_destino_id", nullable=True)
    op.alter_column("notificaciones", "equipo_emisor_id", nullable=True)
    op.alter_column(
        "notificaciones",
        "payload",
        type_=postgresql.JSON(),
        postgresql_using="payload::json",
        nullable=True,
    )

    # --- tipos_notificacion
    op.drop_constraint("ck_tipos_ttl_positivo", "tipos_notificacion", type_="check")
    op.execute("UPDATE tipos_notificacion SET campo_clave = 'id' WHERE campo_clave IS NULL")
    op.alter_column("tipos_notificacion", "campo_clave", nullable=False)
    op.alter_column("tipos_notificacion", "equipo_destino_id", nullable=True)
    op.alter_column("tipos_notificacion", "equipo_emisor_id", nullable=True)
    op.alter_column(
        "tipos_notificacion",
        "schema",
        type_=postgresql.JSON(),
        postgresql_using="schema::json",
        nullable=True,
    )

    # --- alertas
    op.drop_constraint("ck_alertas_cierre_coherente", "alertas", type_="check")
    op.drop_constraint("ck_alertas_motivo", "alertas", type_="check")
    op.drop_constraint("uq_alertas_notificacion_id", "alertas", type_="unique")
    op.alter_column("alertas", "expira_at", nullable=True)
    op.drop_index(
        "uq_alerta_activa_tipo_clave",
        table_name="alertas",
        postgresql_where=_ACTIVA_NUEVA,
    )
    op.create_index(
        "uq_alerta_activa_tipo_clave",
        "alertas",
        ["tipo", "clave"],
        unique=True,
        postgresql_where=_ACTIVA_ANTERIOR,
    )
    op.execute("UPDATE alertas SET motivo_resolucion = lower(motivo_resolucion)")
    op.alter_column("alertas", "cerrada_at", new_column_name="resuelta_at")


def _entregada_at():  # type: ignore[no-untyped-def]
    import sqlalchemy as sa

    return sa.Column("entregada_at", sa.DateTime(timezone=True), nullable=True)
