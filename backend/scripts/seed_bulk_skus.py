"""海量 SKU 仿真数据生成（压测数据管理能力）。

红线遵守：
- 一律走 services.config_engine.create_sku 落库——指纹/去重/校验/建树全部走规范路径，
  绝不手插 sku/指纹，保证"同配置必同指纹、异配置必异指纹"零破坏。
- 只清 SKU 业务数据（quote_item/quote/sku_price/sku_attribute_value/sku_config_node/sku），
  绝不动模板(node_type/属性/槽)、供应商、采购件。
- 价格走 append-only、不重叠日期段；历史段喂趋势图。

策略：
- 按"可售根"轮转采样随机合法配置（属性随机选、槽随机配/选成品件、白盒节点随机标供应商），
  靠 create_sku 指纹去重；某类型连续撞重达阈值即判为近枯竭、退出轮转。小类型自然跑满、
  大类型(干粉/CO2灭火器、阀门)承载主体量。
- 真实分布：~13% 作废(retired)、~12% 待录价、其余在售并随机录价(USD 为主/部分 CNY、
  不同生效日、约 30% 含 2~4 段历史改价→趋势图)、部分白盒节点标供应商。

性能：把 _load_type 换成内存缓存（纯读替换，不动校验/指纹逻辑），批量提交 + expunge_all 控内存。

执行（backend 目录）：
  python -m scripts.seed_bulk_skus --suppliers 30 --wipe --target 100000
  python -m scripts.seed_bulk_skus --target 1000          # 续铺到至少 1000（幂等、增量）
"""
import argparse
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

import app.services.config_engine as ce
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    AppUser,
    AttributeDef,
    ComponentSlot,
    NodeType,
    PurchasedPart,
    Sku,
    SkuPrice,
    Supplier,
)
from app.schemas.config import (
    AttributeSelection,
    ConfigNodeIn,
    ConfigPayload,
    SlotSelection,
)
from app.services.codes import next_code
from app.services.config_engine import IncompleteConfigError, create_sku
from app.services.slugs import unique_code

# ---- 内存类型缓存：纯读替换 _load_type，消除每次 create_sku 的 N+1 模板查询 ----
_TYPE_CACHE: dict[int, NodeType] = {}


def _patched_load_type(db, type_id, cache=None):  # noqa: ANN001
    return _TYPE_CACHE.get(type_id)


def _reload_cache(db) -> None:
    rows = db.execute(
        select(NodeType).options(
            selectinload(NodeType.attributes).selectinload(AttributeDef.options),
            selectinload(NodeType.slots),
        )
    ).scalars().all()
    _TYPE_CACHE.clear()
    _TYPE_CACHE.update({t.id: t for t in rows})


# ---- 随机供应商命名（地区 + 字号 + 行业 + 后缀） ----
_REGION = ["宁波", "温州", "台州", "杭州", "绍兴", "金华", "嘉兴", "湖州", "丽水", "衢州",
           "上海", "苏州", "无锡", "常州", "南通", "佛山", "东莞", "中山", "泉州", "潍坊"]
_ZIHAO = ["恒昌", "瑞丰", "鸿源", "盛达", "金鼎", "华盛", "永泰", "宏远", "立信", "国泰",
          "三鑫", "卓越", "明欣", "兴隆", "天成", "正大", "众诚", "联创", "德邦", "万达"]
_TRADE = ["阀门", "消防器材", "金属制品", "机械", "压力容器", "五金", "精密铸造",
          "气体设备", "安全设备", "工贸"]
_SUFFIX = ["有限公司", "股份有限公司", "制造有限公司", "实业有限公司", "科技有限公司"]
_PAYMENT = ["预付30%尾款发货前", "月结30天", "月结60天", "款到发货", "T/T 50%定金", "见提单付款"]


def _rand_supplier_name(rng: random.Random) -> str:
    return f"{rng.choice(_REGION)}{rng.choice(_ZIHAO)}{rng.choice(_TRADE)}{rng.choice(_SUFFIX)}"


def ensure_suppliers(db, target: int, rng: random.Random) -> list[int]:
    existing = db.execute(select(Supplier)).scalars().all()
    active_ids = [s.id for s in existing if s.is_active]
    have = len(existing)
    used_names = {s.name for s in existing}
    created = 0
    attempts = 0
    while have + created < target and attempts < target * 20:
        attempts += 1
        name = _rand_supplier_name(rng)
        if name in used_names:
            continue
        used_names.add(name)
        sup = Supplier(
            code=unique_code(db, Supplier, name),
            name=name,
            is_active=True,
            contact=f"采购联系人{rng.randint(100, 999)}",
            lead_time_days=rng.choice([7, 10, 14, 15, 20, 30, 45, 60]),
            payment_terms=rng.choice(_PAYMENT),
            rating=rng.randint(2, 5),
        )
        db.add(sup)
        db.flush()
        active_ids.append(sup.id)
        created += 1
    db.commit()
    print(f"[suppliers] 现有 {have} 家 → 新建 {created} 家 → 活跃供应商 {len(active_ids)} 家")
    return active_ids


# ---- 成品采购件（黑盒件）：供 ① 部件槽黑盒填充 ② 整机直采根 SKU ----
def ensure_purchased_parts(db, sup_ids, per_type, created_by, rng):
    """为每个节点类型补足 per_type 件成品采购件（幂等：已够则跳过）。
    含整机品类件→可作整机直采根；含部件类型件→可作槽黑盒填充。"""
    types = list(_TYPE_CACHE.values())
    have = {}
    for p in db.execute(select(PurchasedPart)).scalars().all():
        have[p.node_type_id] = have.get(p.node_type_id, 0) + 1
    created = 0
    for t in types:
        if not t.is_active:
            continue
        cur = have.get(t.id, 0)
        for i in range(cur, per_type):
            sup = rng.choice(sup_ids)
            name = f"{t.name}-{rng.choice(_ZIHAO)}{i + 1:02d}"
            db.add(PurchasedPart(
                code=next_code(db, "PP"),
                node_type_id=t.id, supplier_id=sup, name=name,
                lead_time_days=rng.choice([7, 15, 30, 45]),
                status="active", created_by=created_by,
            ))
            db.flush()
            created += 1
    db.commit()
    print(f"[parts] 新建成品采购件 {created} 件（每类型补足至 {per_type} 件）")


# ---- 只清 SKU 业务数据，模板/供应商/采购件保持不动 ----
_SKU_WIPE = "quote_item, quote, sku_price, sku_attribute_value, sku_config_node, sku"


def wipe_skus(db) -> None:
    db.execute(text(f"TRUNCATE TABLE {_SKU_WIPE} RESTART IDENTITY CASCADE"))
    # SKU 人读编码计数器归零，编码从 SKU-{year}-00001 重新起算
    db.execute(text("DELETE FROM code_counter WHERE kind = 'SKU'"))
    db.commit()
    print(f"[wipe] 已清空：{_SKU_WIPE} + 重置 SKU 编码计数器（模板/供应商/采购件保留）")


# ---- 随机合法配置生成 ----
def _active_attrs(t):
    return [a for a in t.attributes if a.is_active]


def _active_opts(a):
    return [o for o in a.options if o.is_active]


def _active_slots(t):
    return [s for s in t.slots if s.is_active]


class Builder:
    def __init__(self, rng, parts_by_type, supplier_ids, max_depth, p_supplier, p_direct=0.04):
        self.rng = rng
        self.parts_by_type = parts_by_type  # type_id -> [part_id...]
        self.supplier_ids = supplier_ids
        self.max_depth = max_depth
        self.p_supplier = p_supplier
        self.p_direct = p_direct
        self._completable: dict[int, bool] = {}

    def completable(self, type_id: int, depth: int = 1) -> bool:
        """该类型能否在深度内被配置出一个完整白盒子树（保守判定，无供应商维度）。"""
        if type_id in self._completable:
            return self._completable[type_id]
        t = _TYPE_CACHE.get(type_id)
        if t is None or not t.is_active or depth > self.max_depth:
            return False
        self._completable[type_id] = True  # 占位防环
        ok = True
        for a in _active_attrs(t):
            if a.is_required and not _active_opts(a):
                ok = False
                break
        if ok:
            slots = _active_slots(t)
            groups: dict[str, list] = {}
            for s in slots:
                if s.variant_group:
                    groups.setdefault(s.variant_group, []).append(s)

            def fillable(s):
                if s.allow_blackbox and self.parts_by_type.get(s.child_type_id):
                    return True
                return self.completable(s.child_type_id, depth + 1)

            for s in slots:
                if s.variant_group:
                    continue
                if s.is_required and not fillable(s):
                    ok = False
                    break
            if ok:
                for _, members in groups.items():
                    if not any(fillable(s) for s in members):
                        ok = False
                        break
        self._completable[type_id] = ok
        return ok

    def _fill_slot(self, slot, depth: int) -> SlotSelection | None:
        cid = slot.child_type_id
        parts = self.parts_by_type.get(cid, [])
        modes = []
        if slot.allow_blackbox and parts:
            modes.append("purchased")
        if depth + 1 <= self.max_depth and self.completable(cid, depth + 1):
            modes.append("configured")
        if not modes:
            return None
        mode = self.rng.choice(modes)
        if mode == "purchased":
            return SlotSelection(
                slot_id=slot.id, mode="purchased",
                purchased_part_id=self.rng.choice(parts),
            )
        child = self.node(cid, depth + 1)
        if child is None:
            if slot.allow_blackbox and parts:
                return SlotSelection(
                    slot_id=slot.id, mode="purchased",
                    purchased_part_id=self.rng.choice(parts),
                )
            return None
        return SlotSelection(slot_id=slot.id, mode="configured", child=child)

    def node(self, type_id: int, depth: int) -> ConfigNodeIn | None:
        t = _TYPE_CACHE.get(type_id)
        if t is None:
            return None
        attrs = []
        for a in _active_attrs(t):
            opts = _active_opts(a)
            if a.is_required:
                attrs.append(AttributeSelection(attribute_id=a.id, option_id=self.rng.choice(opts).id))
            elif opts and self.rng.random() < 0.45:
                attrs.append(AttributeSelection(attribute_id=a.id, option_id=self.rng.choice(opts).id))

        slots = _active_slots(t)
        groups: dict[str, list] = {}
        for s in slots:
            if s.variant_group:
                groups.setdefault(s.variant_group, []).append(s)

        sels: list[SlotSelection] = []
        # 互斥组：恰好选一个成员并配满
        for _, members in groups.items():
            order = members[:]
            self.rng.shuffle(order)
            picked = None
            for m in order:
                picked = self._fill_slot(m, depth)
                if picked is not None:
                    break
            if picked is None:
                return None  # 必须的组无法满足 → 整个节点作废重来
            sels.append(picked)
        # 非互斥槽
        for s in slots:
            if s.variant_group:
                continue
            if s.is_required:
                sel = self._fill_slot(s, depth)
                if sel is None:
                    return None
                sels.append(sel)
            elif self.rng.random() < 0.5:
                sel = self._fill_slot(s, depth)
                if sel is not None:
                    sels.append(sel)

        supplier_id = None
        if self.supplier_ids and self.rng.random() < self.p_supplier:
            supplier_id = self.rng.choice(self.supplier_ids)
        return ConfigNodeIn(attributes=attrs, slots=sels, supplier_id=supplier_id)

    def payload(self, root_id: int) -> ConfigPayload | None:
        t = _TYPE_CACHE.get(root_id)
        parts = self.parts_by_type.get(root_id, [])
        # 整机直采：整机品类有成品件时，少量概率直接以黑盒整机件为根
        if t is not None and t.kind == "product" and parts and self.rng.random() < self.p_direct:
            return ConfigPayload(root_type_id=root_id, root_purchased_part_id=self.rng.choice(parts))
        node = self.node(root_id, 1)
        if node is None:
            return None
        return ConfigPayload(root_type_id=root_id, root=node)


# ---- 真实价格/状态分布 ----
def assign_realism(db, sku, rng: random.Random) -> None:
    today = date.today()
    is_retired = rng.random() < 0.13
    if is_retired:
        sku.status = "retired"
    price_prob = 0.90 if is_retired else 0.88
    if rng.random() >= price_prob:
        return  # 待录价
    currencies = ["USD"] if rng.random() < 0.75 else ["CNY"]
    if rng.random() < 0.15:  # 少量双币种
        currencies.append("USD" if currencies[0] == "CNY" else "CNY")
    for cur in set(currencies):
        base = Decimal(str(round(rng.uniform(3, 300), 2)))
        if rng.random() < 0.30:  # 含历史改价 → 趋势图
            n = rng.randint(2, 4)
            # 生成 n 段升序、不重叠的日期段；最后一段开口
            starts = sorted(rng.sample(range(20, 760), n))  # 距今天的天数（越大越早）
            starts = [today - timedelta(days=d) for d in sorted(starts, reverse=True)]
            price = base
            for i, vf in enumerate(starts):
                vt = (starts[i + 1] - timedelta(days=1)) if i + 1 < len(starts) else None
                db.add(SkuPrice(sku_id=sku.id, price=price, currency=cur, valid_from=vf, valid_to=vt))
                price = (price * Decimal(str(round(rng.uniform(0.9, 1.2), 3)))).quantize(Decimal("0.01"))
        else:
            vf = today - timedelta(days=rng.randint(1, 400))
            db.add(SkuPrice(sku_id=sku.id, price=base, currency=cur, valid_from=vf, valid_to=None))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suppliers", type=int, default=30)
    ap.add_argument("--target", type=int, default=100000)
    ap.add_argument("--wipe", action="store_true")
    ap.add_argument("--batch", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260616)
    ap.add_argument("--p-supplier", type=float, default=0.5, help="白盒节点标供应商概率")
    ap.add_argument("--p-direct", type=float, default=0.04, help="整机品类走直采黑盒根概率")
    ap.add_argument("--parts-per-type", type=int, default=4, help="每节点类型补足的成品采购件数")
    ap.add_argument("--dup-limit", type=int, default=400, help="单类型连续撞重阈值→判枯竭")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    ce._load_type = _patched_load_type  # 装上内存缓存（纯读替换）

    db = SessionLocal()
    db.expire_on_commit = False
    settings = get_settings()
    try:
        admin = db.execute(select(AppUser).limit(1)).scalar_one_or_none()
        created_by = admin.id if admin else None

        sup_ids = ensure_suppliers(db, args.suppliers, rng)
        _reload_cache(db)
        if args.parts_per_type > 0:
            ensure_purchased_parts(db, sup_ids, args.parts_per_type, created_by, rng)
        if args.wipe:
            wipe_skus(db)

        parts = db.execute(select(PurchasedPart)).scalars().all()
        parts_by_type: dict[int, list[int]] = {}
        for p in parts:
            if p.status in ("draft", "active"):
                parts_by_type.setdefault(p.node_type_id, []).append(p.id)

        builder = Builder(rng, parts_by_type, sup_ids, settings.max_config_depth,
                          args.p_supplier, args.p_direct)

        roots = [t.id for t in _TYPE_CACHE.values()
                 if t.is_sellable_root and t.is_active and builder.completable(t.id)]
        roots.sort()
        names = {t.id: t.name for t in _TYPE_CACHE.values()}

        current = db.execute(select(func.count()).select_from(Sku)).scalar_one()
        need = max(0, args.target - current)
        print(f"[gen] 现有 SKU {current} → 目标 {args.target} → 需新增 {need}；可铺品类 {len(roots)} 个")
        if need == 0:
            print("[gen] 已达目标，无需生成。")
            return

        active = list(roots)
        dups = {r: 0 for r in roots}
        per_type_made = {r: 0 for r in roots}
        made = 0
        since_commit = 0
        while made < need and active:
            for rid in list(active):
                if made >= need:
                    break
                payload = None
                for _ in range(8):  # 单次最多 8 试，避开偶发不可完成的随机组合
                    payload = builder.payload(rid)
                    if payload is not None:
                        break
                if payload is None:
                    active.remove(rid)
                    continue
                try:
                    sku, was_created = create_sku(db, payload, created_by=created_by)
                except IncompleteConfigError:
                    dups[rid] += 1
                    if dups[rid] > args.dup_limit:
                        active.remove(rid)
                    continue
                if was_created:
                    assign_realism(db, sku, rng)
                    made += 1
                    per_type_made[rid] += 1
                    dups[rid] = 0
                    since_commit += 1
                    if since_commit >= args.batch:
                        db.commit()
                        db.expunge_all()
                        _reload_cache(db)
                        since_commit = 0
                        print(f"[gen] 进度 {made}/{need}  (+{args.batch})  活跃品类 {len(active)}")
                else:
                    dups[rid] += 1
                    if dups[rid] > args.dup_limit:
                        active.remove(rid)
        db.commit()
        total = db.execute(select(func.count()).select_from(Sku)).scalar_one()
        print(f"[gen] 完成：本次新增 {made}，库内 SKU 合计 {total}")
        print("[gen] 各品类新增：")
        for rid in roots:
            if per_type_made[rid]:
                print(f"   {names.get(rid, rid):<16} +{per_type_made[rid]}"
                      + ("  (枯竭)" if rid not in active else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main()
