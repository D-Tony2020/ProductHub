"""supplier metadata (供应商管理 P2：交期/付款条件/评级，纯运营元数据)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14

给 supplier 加 lead_time_days / payment_terms / rating（均 nullable，纯运营元数据，
不入指纹）。约束名写死以匹配模型元数据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("supplier", sa.Column("lead_time_days", sa.Integer(), nullable=True))
    op.add_column("supplier", sa.Column("payment_terms", sa.String(length=200), nullable=True))
    op.add_column("supplier", sa.Column("rating", sa.SmallInteger(), nullable=True))
    op.execute(
        "ALTER TABLE supplier ADD CONSTRAINT ck_supplier_rating_range "
        "CHECK (rating IS NULL OR rating BETWEEN 1 AND 5)"
    )
    op.execute(
        "ALTER TABLE supplier ADD CONSTRAINT ck_supplier_lead_time_non_negative "
        "CHECK (lead_time_days IS NULL OR lead_time_days >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE supplier DROP CONSTRAINT ck_supplier_lead_time_non_negative")
    op.execute("ALTER TABLE supplier DROP CONSTRAINT ck_supplier_rating_range")
    op.drop_column("supplier", "rating")
    op.drop_column("supplier", "payment_terms")
    op.drop_column("supplier", "lead_time_days")
