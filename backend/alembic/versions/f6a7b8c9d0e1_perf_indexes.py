"""perf indexes 批1·索引地基：补齐大表热点列 btree（CONCURRENTLY 在线建索引）

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-16

来自后端/DB 深度审计批1（红线 F2/F6）。canonical 迁移链对 sku / sku_price /
sku_config_node / sku_attribute_value 等大表的热点过滤·连接·排序列零二级索引——
PG 不为外键自动建索引，海量(10万~百万行)下 stats/overview/筛选/现价取数全退化为 Seq Scan，
正是现场"8000 条 >12s 超时"的地基根因。本迁移补齐之。

工程约束：① 全部 CREATE INDEX CONCURRENTLY（在线建、不长锁大表）→ 必须脱离迁移事务，
故包在 op.get_context().autocommit_block() 内逐条执行；② IF NOT EXISTS 保证可重入；
③ 多列用 partial（IS NOT NULL / 现价语义）压索引体积。
单 SKU 权威健康仍走 compute_health，不受影响；本迁移纯加索引、零数据/指纹改动。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (索引名, CREATE 语句)；DROP 由名字反推
_INDEXES = [
    # sku_config_node：FK 反查（reference_count / 按件·按供应商筛选 / _NONOK 供给族）+ 树遍历
    ("ix_scn_purchased_part_id",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scn_purchased_part_id "
     "ON sku_config_node (purchased_part_id) WHERE purchased_part_id IS NOT NULL"),
    ("ix_scn_supplier_id",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scn_supplier_id "
     "ON sku_config_node (supplier_id) WHERE supplier_id IS NOT NULL"),
    ("ix_scn_node_type_id",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scn_node_type_id "
     "ON sku_config_node (node_type_id)"),
    ("ix_scn_parent_node_id",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scn_parent_node_id "
     "ON sku_config_node (parent_node_id) WHERE parent_node_id IS NOT NULL"),
    # sku_attribute_value：按选项反查（option 多选过滤 + 停用选项 EXISTS）
    ("ix_sav_option_id",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sav_option_id "
     "ON sku_attribute_value (option_id)"),
    # sku：热点过滤/排序（overview 的 status='active' AND root_type_id=、近 7 天新增）
    ("ix_sku_root_type_status",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sku_root_type_status "
     "ON sku (root_type_id, status)"),
    ("ix_sku_created_at",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sku_created_at ON sku (created_at)"),
    # sku_price：现价取数 + stale_30d 范围，贴合"现价/开放价"语义的 partial
    ("ix_sku_price_current",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sku_price_current "
     "ON sku_price (sku_id, currency, valid_from) WHERE superseded_at IS NULL"),
    # purchased_part：件库按类型筛选（supplier_id 已被 (supplier_id,node_type_id,name) 唯一前导覆盖）
    ("ix_purchased_part_node_type",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_purchased_part_node_type "
     "ON purchased_part (node_type_id)"),
    # audit_log：增长最快，按实体/操作人检索
    ("ix_audit_entity",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_entity "
     "ON audit_log (entity_type, entity_id)"),
    ("ix_audit_actor",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_actor ON audit_log (actor_id)"),
    # quote_item：按 SKU 反查（父表 RESTRICT 删除校验亦受益）
    ("ix_quote_item_sku",
     "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_quote_item_sku ON quote_item (sku_id)"),
]


def upgrade() -> None:
    with op.get_context().autocommit_block():  # CONCURRENTLY 不能在事务内
        for _, sql in _INDEXES:
            op.execute(sql)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
