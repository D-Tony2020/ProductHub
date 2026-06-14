"""part spec config (灰盒成品件：可选结构化规格 spec_config JSONB)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-14

给 purchased_part 加 spec_config(JSONB, nullable)：灰盒成品件的可选结构化规格树
(复用 ConfigPayload 形态、全不必配)。纯描述性元数据，🔴 永不入 SKU 指纹。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchased_part", sa.Column("spec_config", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchased_part", "spec_config")
