"""agrega la fecha de resolución a las alertas

Revision ID: 0005_resuelta_at_alertas
Revises: 0004_catalogo_tipos
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_resuelta_at_alertas"
down_revision: str | Sequence[str] | None = "0004_catalogo_tipos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alertas", sa.Column("resuelta_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("alertas", "resuelta_at")
