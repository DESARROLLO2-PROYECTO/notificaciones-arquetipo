"""HU-NOT-11: llaves y equipos de los tres roles permitidos.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    equipos = sa.table("equipos", sa.column("nombre", sa.String), sa.column("es_admin", sa.Boolean))
    # No modifica equipos preexistentes ni crea llaves automáticamente.
    op.execute(
        insert(equipos)
        .values(
            [
                {"nombre": "inventario", "es_admin": False},
                {"nombre": "fabricacion", "es_admin": False},
                {"nombre": "notificaciones", "es_admin": True},
            ]
        )
        .on_conflict_do_nothing(index_elements=["nombre"])
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("equipo_id", sa.Integer, sa.ForeignKey("equipos.id"), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefijo", sa.String(16), nullable=False),
        sa.Column("activa", sa.Boolean, nullable=False),
        sa.Column("creada_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_equipo_id_activa", "api_keys", ["equipo_id", "activa"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_equipo_id_activa", table_name="api_keys")
    op.drop_table("api_keys")
    # Se conservan equipos: podrían existir antes de esta revisión o tener otros usos.
