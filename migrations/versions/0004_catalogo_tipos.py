"""siembra el catalogo de tipos de notificacion de stock bajo

Revision ID: 0004_catalogo_tipos
Revises: 9d656b50674b
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_catalogo_tipos"
down_revision: str | Sequence[str] | None = "9d656b50674b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAMPOS_STOCK = '["productoId", "nombre", "stockActual", "stockMinimo"]'

# (codigo, equipo emisor, equipo destino, ttl en minutos): 24 h por defecto (HU-NOT-02).
_TIPOS = (
    ("STOCK_BAJO_INSUMO", "inventario", "inventario", 1440),
    ("STOCK_BAJO_PRODUCTO", "inventario", "fabricacion", 1440),
)


def upgrade() -> None:
    for codigo, emisor, destino, ttl in _TIPOS:
        op.execute(
            sa.text(
                """
                INSERT INTO tipos_notificacion
                    (codigo, equipo_emisor_id, equipo_destino_id, schema,
                     campo_clave, ttl_alerta_min, activo)
                VALUES (
                    :codigo,
                    (SELECT id FROM equipos WHERE nombre = :emisor),
                    (SELECT id FROM equipos WHERE nombre = :destino),
                    CAST(:schema AS json),
                    'productoId',
                    :ttl,
                    true
                )
                ON CONFLICT (codigo) DO NOTHING
                """
            ).bindparams(
                codigo=codigo, emisor=emisor, destino=destino, schema=_CAMPOS_STOCK, ttl=ttl
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM tipos_notificacion WHERE codigo = ANY(:codigos)").bindparams(
            codigos=[t[0] for t in _TIPOS]
        )
    )
