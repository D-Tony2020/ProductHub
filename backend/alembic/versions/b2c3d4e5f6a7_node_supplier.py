"""node supplier (采购溯源升级·方案甲：白盒节点级供应商，code 入指纹)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14

给 sku_config_node 加 supplier_id（nullable，FK→supplier，RESTRICT）。
白盒节点可标采购来源；供应商 code 进指纹序列化（仅在标注时追加，未标注=今日空值
逐字节不变，既有 SKU 指纹零变化，由 golden 回归守）。黑盒节点供应商仍由 part 决定。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sku_config_node", sa.Column("supplier_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_sku_config_node_supplier_id", "sku_config_node", "supplier",
        ["supplier_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sku_config_node_supplier_id", "sku_config_node", type_="foreignkey")
    op.drop_column("sku_config_node", "supplier_id")
