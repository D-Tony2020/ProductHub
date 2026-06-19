# -*- coding: utf-8 -*-
"""一次性回填：把所有 SKU 的展示名（"root_type.name（属性/部件摘要）"）重算到与当前
部件名/选项名/品类名一致——修复"加同步逻辑之前"的历史改名遗留的陈旧规格摘要。

复用 reconstruct_payload + validate_config（与创建/改名同步同一命名真源，零漂移）；
只改 sku.name，sku_code/fingerprint/配置一概不动（红线安全）。分批提交，可中断续跑（幂等）。

用法： .venv\\Scripts\\python.exe scripts\\backfill_sku_names.py
"""
import time

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.models import Sku, SkuConfigNode
from app.services.config_engine import validate_config
from app.services.health_engine import reconstruct_payload

BATCH = 500


def main() -> None:
    db = SessionLocal()
    ids = list(db.execute(select(Sku.id).order_by(Sku.id)).scalars())
    print(f"共 {len(ids)} 个 SKU，开始回填展示名…")
    type_cache: dict = {}
    changed = 0
    t0 = time.time()
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        skus = db.execute(
            select(Sku).where(Sku.id.in_(batch))
            .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
        ).scalars().all()
        for sku in skus:
            _, name = validate_config(db, reconstruct_payload(sku), lenient=True,
                                      type_cache=type_cache, skip_dedup=True)
            if name and name != sku.name:
                sku.name = name
                changed += 1
        db.commit()
        print(f"  {min(i + BATCH, len(ids))}/{len(ids)}  累计改名 {changed}  {time.time() - t0:.0f}s")
    print(f"完成：回填改名 {changed} 个，耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
