"""开发用：核对 schema 关键对象是否落库。"""
from sqlalchemy import text

from app.core.db import engine

CHECKS = [
    ("表数量", "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"),
    ("视图 v_sku_current_price", "select count(*) from information_schema.views where table_name='v_sku_current_price'"),
    ("EXCLUDE 约束", "select count(*) from pg_constraint where conname='excl_sku_price_overlap'"),
    ("复合FK 槽类型匹配", "select count(*) from pg_constraint where conname='fk_node_slot_type_match'"),
    ("复合FK 黑盒类型匹配", "select count(*) from pg_constraint where conname='fk_node_part_type_match'"),
    ("复合FK 选项属于属性", "select count(*) from pg_constraint where conname='fk_value_option_of_attribute'"),
    ("根唯一部分索引", "select count(*) from pg_indexes where indexname='uq_sku_config_node_single_root'"),
    ("trigram 索引", "select count(*) from pg_indexes where indexname in ('ix_purchased_part_name_trgm','ix_sku_name_trgm')"),
    ("btree_gist 扩展", "select count(*) from pg_extension where extname='btree_gist'"),
    ("pg_trgm 扩展", "select count(*) from pg_extension where extname='pg_trgm'"),
]

with engine.connect() as conn:
    for label, sql in CHECKS:
        print(f"{label}: {conn.execute(text(sql)).scalar()}")
