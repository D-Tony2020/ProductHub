"""仿真数据体检（只读）：核对红线与真实分布。"""
from sqlalchemy import func, select, text

from app.core.db import SessionLocal
from app.models import Sku, SkuConfigNode, SkuPrice


def main() -> None:
    db = SessionLocal()
    try:
        total = db.execute(select(func.count()).select_from(Sku)).scalar_one()
        distinct_fp = db.execute(select(func.count(func.distinct(Sku.fingerprint)))).scalar_one()
        active = db.execute(select(func.count()).select_from(Sku).where(Sku.status == "active")).scalar_one()
        retired = db.execute(select(func.count()).select_from(Sku).where(Sku.status == "retired")).scalar_one()
        priced = db.execute(text(
            "SELECT count(DISTINCT sku_id) FROM sku_price WHERE superseded_at IS NULL"
        )).scalar()
        nodes = db.execute(select(func.count()).select_from(SkuConfigNode)).scalar_one()
        nodes_with_sup = db.execute(
            select(func.count()).select_from(SkuConfigNode).where(SkuConfigNode.supplier_id.isnot(None))
        ).scalar_one()
        price_rows = db.execute(select(func.count()).select_from(SkuPrice)).scalar_one()
        # 趋势候选：同 SKU+币种 有 >=2 条未作废价
        trend = db.execute(text(
            "SELECT count(*) FROM (SELECT sku_id, currency FROM sku_price "
            "WHERE superseded_at IS NULL GROUP BY sku_id, currency HAVING count(*) >= 2) q"
        )).scalar()
        # 整机直采黑盒根 SKU
        direct = db.execute(text(
            "SELECT count(*) FROM sku_config_node WHERE parent_node_id IS NULL AND mode='purchased'"
        )).scalar()
        codes = db.execute(select(Sku.sku_code).order_by(Sku.id).limit(3)).scalars().all()
        last_codes = db.execute(select(Sku.sku_code).order_by(Sku.id.desc()).limit(2)).scalars().all()

        print("=" * 60)
        print(f"SKU 总数            : {total}")
        print(f"不同指纹数(应=总数) : {distinct_fp}   {'✅ 指纹全唯一' if distinct_fp == total else '❌ 有重复指纹!'}")
        print(f"在售 active         : {active}  ({active/total*100:.1f}%)" if total else "在售: 0")
        print(f"作废 retired        : {retired}  ({retired/total*100:.1f}%)" if total else "")
        print(f"已录价 SKU          : {priced}  ({priced/total*100:.1f}%)" if total else "")
        print(f"待录价 SKU          : {total - priced}  ({(total-priced)/total*100:.1f}%)" if total else "")
        print(f"含价格历史(趋势)条目: {trend}")
        print(f"整机直采黑盒根 SKU  : {direct}")
        print(f"价格行总数          : {price_rows}")
        print(f"配置节点总数        : {nodes}  (均 {nodes/total:.1f} 节点/SKU)" if total else "")
        print(f"标了供应商的节点    : {nodes_with_sup}  ({nodes_with_sup/nodes*100:.1f}%)" if nodes else "")
        print(f"前 3 个编码         : {codes}")
        print(f"末 2 个编码         : {last_codes}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    main()
