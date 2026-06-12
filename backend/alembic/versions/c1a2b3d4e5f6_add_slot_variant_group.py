"""add component_slot.variant_group (mutually exclusive slot groups / variants)

Revision ID: c1a2b3d4e5f6
Revises: b49c51d5498b
Create Date: 2026-06-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "b49c51d5498b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("component_slot", sa.Column("variant_group", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("component_slot", "variant_group")
