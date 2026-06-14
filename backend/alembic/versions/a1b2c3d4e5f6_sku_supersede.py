"""sku supersede (治理血缘：修改既有 SKU → 新建 SKU + 旧 SKU 留痕指向)

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-14

手写迁移：给 sku 加 superseded_by_sku_id(自指 FK) + superseded_at，
与价格层 superseded 同范式。被取代的旧 SKU 仍可保活在售，故不强制 retired，
仅约束两列同生同灭、不可自指。约束名写死以匹配模型元数据(红线测试断言对象)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sku", sa.Column("superseded_by_sku_id", sa.BigInteger(), nullable=True))
    op.add_column("sku", sa.Column("superseded_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_sku_superseded_by_sku_id", "sku", "sku",
        ["superseded_by_sku_id"], ["id"], ondelete="SET NULL",
    )
    op.execute(
        "ALTER TABLE sku ADD CONSTRAINT ck_sku_supersede_consistency "
        "CHECK ((superseded_by_sku_id IS NULL) = (superseded_at IS NULL))"
    )
    op.execute(
        "ALTER TABLE sku ADD CONSTRAINT ck_sku_supersede_not_self "
        "CHECK (superseded_by_sku_id IS NULL OR superseded_by_sku_id <> id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sku DROP CONSTRAINT ck_sku_supersede_not_self")
    op.execute("ALTER TABLE sku DROP CONSTRAINT ck_sku_supersede_consistency")
    op.drop_constraint("fk_sku_superseded_by_sku_id", "sku", type_="foreignkey")
    op.drop_column("sku", "superseded_at")
    op.drop_column("sku", "superseded_by_sku_id")
