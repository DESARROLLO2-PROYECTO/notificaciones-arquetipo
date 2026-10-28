"""Tabla equipos del ER (ER del DAS), sin semillas.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "equipos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nombre", sa.String(50), nullable=False, unique=True),
        sa.Column("es_admin", sa.Boolean, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("equipos")
