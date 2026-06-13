"""price supersede (软作废 + 部分 EXCLUDE + 现价视图收口)

Revision ID: f1a2b3c4d5e6
Revises: c1a2b3d4e5f6
Create Date: 2026-06-13

手写迁移：autogenerate 无法正确 diff 部分约束的 WHERE 谓词与视图。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sku_price", sa.Column("superseded_at", sa.DateTime(), nullable=True))
    op.add_column("sku_price", sa.Column("superseded_by", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_sku_price_superseded_by", "sku_price", "sku_price",
        ["superseded_by"], ["id"], ondelete="SET NULL",
    )
    # EXCLUDE 改为部分约束：软作废行退出重叠判定，可与同日新价共存；活跃行重叠仍被拒
    op.execute("ALTER TABLE sku_price DROP CONSTRAINT excl_sku_price_overlap")
    op.execute(
        "ALTER TABLE sku_price ADD CONSTRAINT excl_sku_price_overlap "
        "EXCLUDE USING gist (sku_id WITH =, currency WITH =, "
        "daterange(valid_from, valid_to, '[]') WITH &&) "
        "WHERE (superseded_at IS NULL)"
    )
    # 现价视图收口：作废行不得进现价（否则错价泄漏进报价单）
    op.execute("DROP VIEW IF EXISTS v_sku_current_price")
    op.execute(
        """
        CREATE VIEW v_sku_current_price AS
        SELECT sp.sku_id, sp.currency, sp.price, sp.valid_from, sp.valid_to, sp.id AS price_id
        FROM sku_price sp
        WHERE sp.superseded_at IS NULL
          AND sp.valid_from <= CURRENT_DATE
          AND (sp.valid_to IS NULL OR sp.valid_to >= CURRENT_DATE)
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_sku_current_price")
    op.execute(
        """
        CREATE VIEW v_sku_current_price AS
        SELECT sp.sku_id, sp.currency, sp.price, sp.valid_from, sp.valid_to, sp.id AS price_id
        FROM sku_price sp
        WHERE sp.valid_from <= CURRENT_DATE
          AND (sp.valid_to IS NULL OR sp.valid_to >= CURRENT_DATE)
        """
    )
    op.execute("ALTER TABLE sku_price DROP CONSTRAINT excl_sku_price_overlap")
    op.execute(
        "ALTER TABLE sku_price ADD CONSTRAINT excl_sku_price_overlap "
        "EXCLUDE USING gist (sku_id WITH =, currency WITH =, "
        "daterange(valid_from, valid_to, '[]') WITH &&)"
    )
    op.drop_constraint("fk_sku_price_superseded_by", "sku_price", type_="foreignkey")
    op.drop_column("sku_price", "superseded_by")
    op.drop_column("sku_price", "superseded_at")
