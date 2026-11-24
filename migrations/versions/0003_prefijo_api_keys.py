"""Deriva los prefijos existentes del hash SHA-256 de cada llave.

Revision ID: 0003_prefijo_api_keys
Revises: 0002
"""

from alembic import op

revision = "0003_prefijo_api_keys"
down_revision = "0002"


def upgrade() -> None:
    op.execute(
        "UPDATE api_keys SET prefijo = left(hash, 8) WHERE prefijo IS DISTINCT FROM left(hash, 8)"
    )


def downgrade() -> None:
    """Los prefijos originales no se pueden recuperar del hash."""
