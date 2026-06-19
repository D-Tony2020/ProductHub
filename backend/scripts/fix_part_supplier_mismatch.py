# -*- coding: utf-8 -*-
"""一次性修正：把采购件的 supplier_id 回正到"名称里含其字号的供应商"。
成因：seed 生成时件名字号与供应商各自独立随机，未对应（见 seed_bulk_skus.py）。

只改 purchased_part.supplier_id —— 黑盒件序列化只编 part.code（config_engine.py:233），
故不动任何 SKU 指纹/编码/规格摘要；来源地图/按供应商筛选/关联成品/概览计数皆查询时实时派生。

策略：字号→唯一供应商直接回正；字号→多供应商在候选间轮转均衡分配；
字号无对应供应商（联创/盛达，共 9 件）按用户选 (a) 留着不动。
"""
import re
from collections import defaultdict

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import PurchasedPart, Supplier

ZIHAO = ["恒昌", "瑞丰", "鸿源", "盛达", "金鼎", "华盛", "永泰", "宏远", "立信", "国泰",
         "三鑫", "卓越", "明欣", "兴隆", "天成", "正大", "众诚", "联创", "德邦", "万达"]


def part_zihao(name: str):
    if "-" not in name:
        return None
    z = re.sub(r"\d+$", "", name.rsplit("-", 1)[1])
    return z if z in ZIHAO else None


def main() -> None:
    db = SessionLocal()
    sups = db.execute(select(Supplier)).scalars().all()
    sup_name = {s.id: s.name for s in sups}
    by_zihao = defaultdict(list)
    for s in sups:
        if s.is_active:
            for z in ZIHAO:
                if z in s.name:
                    by_zihao[z].append(s.id)
    for z in by_zihao:
        by_zihao[z].sort()  # 稳定顺序，轮转可复现

    parts = db.execute(select(PurchasedPart).order_by(PurchasedPart.id)).scalars().all()
    rr = defaultdict(int)
    changed = 0
    skipped_no_sup = 0
    log = []
    for p in parts:
        z = part_zihao(p.name)
        if z is None:
            continue
        cands = by_zihao.get(z, [])
        if not cands:
            skipped_no_sup += 1   # 9 件：字号无供应商 → 选 (a) 不动
            continue
        if p.supplier_id in cands:
            continue              # 已正确
        target = cands[rr[z] % len(cands)]
        rr[z] += 1
        old = p.supplier_id
        p.supplier_id = target
        changed += 1
        if len(log) < 16:
            log.append(f"  {p.name}: [{sup_name.get(old)}] → [{sup_name.get(target)}]")

    db.commit()
    print(f"回正 {changed} 件；按(a)保留无供应商字号件 {skipped_no_sup} 件")
    for line in log:
        print(line)

    # 验证：改后仍"有字号但供应商名不含该字号"的件（应只剩无供应商的 9 件）
    db.expire_all()
    sup_name2 = {s.id: s.name for s in db.execute(select(Supplier)).scalars().all()}
    residual = 0
    for p in db.execute(select(PurchasedPart)).scalars().all():
        z = part_zihao(p.name)
        if z is None:
            continue
        if z not in by_zihao:
            continue              # 无供应商字号，已知保留
        if z not in (sup_name2.get(p.supplier_id) or ""):
            residual += 1
            print(f"  [仍不一致] {p.name} → {sup_name2.get(p.supplier_id)}")
    print(f"校验：可匹配字号中仍不一致 = {residual}（期望 0）")


if __name__ == "__main__":
    main()
