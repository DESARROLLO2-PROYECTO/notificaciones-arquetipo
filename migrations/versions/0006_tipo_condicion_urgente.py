"""siembra el tipo de notificacion CONDICION_URGENTE

Revision ID: 0006_tipo_condicion_urgente
Revises: 0005_resuelta_at_alertas
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_tipo_condicion_urgente"
down_revision: str | Sequence[str] | None = "0005_resuelta_at_alertas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Emisor y destino: fabricacion; ttl de 60 min por defecto (HU-NOT-05).
    op.execute(
        sa.text(
            """
            INSERT INTO tipos_notificacion
                (codigo, equipo_emisor_id, equipo_destino_id, schema,
                 campo_clave, ttl_alerta_min, activo)
            VALUES (
                'CONDICION_URGENTE',
                (SELECT id FROM equipos WHERE nombre = 'fabricacion'),
                (SELECT id FROM equipos WHERE nombre = 'fabricacion'),
                CAST('["codigoCondicion", "descripcion"]' AS json),
                'codigoCondicion',
                60,
                true
            )
            ON CONFLICT (codigo) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM tipos_notificacion WHERE codigo = 'CONDICION_URGENTE'"))
