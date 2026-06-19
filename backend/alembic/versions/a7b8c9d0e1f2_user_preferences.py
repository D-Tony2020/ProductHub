"""user preferences：per-user 界面偏好(产品库分面/默认币种排序每页视图)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-17

给 app_user 加 preferences JSONB(server_default '{}')，存 per-user 界面偏好。
纯展示偏好——不入指纹、不涉权限、不影响任何业务数据；缺省空对象由前端 catalog 合并补齐。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("preferences", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("app_user", "preferences")
