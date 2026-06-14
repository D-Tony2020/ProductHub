"""part lead time (参考交期挂采购件：每件各自的标称交期)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-14

给 purchased_part 加 lead_time_days(每件参考交期·权威值在件上)。供应商
lead_time_days 退为"默认值"，新建采购件时预填、件可覆盖。纯元数据不入指纹。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchased_part", sa.Column("lead_time_days", sa.Integer(), nullable=True))
    op.execute(
        "ALTER TABLE purchased_part ADD CONSTRAINT ck_purchased_part_lead_time_non_negative "
        "CHECK (lead_time_days IS NULL OR lead_time_days >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE purchased_part DROP CONSTRAINT ck_purchased_part_lead_time_non_negative")
    op.drop_column("purchased_part", "lead_time_days")
