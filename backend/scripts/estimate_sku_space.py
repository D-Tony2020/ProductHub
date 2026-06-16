"""精确枚举【当前模板】的 SKU 组合上限（只读·绝不写库）。

口径与配置引擎 services/config_engine 完全一致：
- 白盒配置 configs(T)：节点 T 作为子树的完整白盒配置数
    = Π(必选属性·活跃选项数) × Π(可选属性·(选项数+1)) ×
      Π(非互斥槽: 必配=填法数 / 可选=填法数+1) × Π(互斥组: Σ成员填法数)
- 单槽填法 slot_choices(子类型 C) = configs(C)[白盒逐项] + 活跃成品件数(C)[黑盒，若允许]
- 可售根 R 的 SKU 空间 = configs(R)[白盒整机] + 该根类型的活跃整机采购件数[整机直采]
- 受 settings.max_config_depth 限制；DAG 无环。

供应商维度单列报告（不计入结构上限）：白盒每个节点可选标供应商，
每节点 ×(活跃供应商数+1)，仅作"真实度可放大空间"的参考量级。

执行：在 backend 目录运行  python -m scripts.estimate_sku_space
"""
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    AttributeDef,
    ComponentSlot,
    NodeType,
    PurchasedPart,
    Supplier,
)

CAP = 10 ** 15  # 上限封顶值：超过即视为"实质无界"，避免天文数字刷屏


def _clamp(n: int) -> int:
    return min(n, CAP)


def main() -> None:
    settings = get_settings()
    max_depth = settings.max_config_depth
    db = SessionLocal()
    try:
        types = db.execute(
            select(NodeType).options(
                selectinload(NodeType.attributes).selectinload(AttributeDef.options),
                selectinload(NodeType.slots),
            )
        ).scalars().all()
        by_id = {t.id: t for t in types}

        # 活跃成品采购件按类型计数（draft/active 可用于配置）
        parts = db.execute(select(PurchasedPart)).scalars().all()
        parts_by_type: dict[int, int] = {}
        for p in parts:
            if p.status in ("draft", "active"):
                parts_by_type[p.node_type_id] = parts_by_type.get(p.node_type_id, 0) + 1

        n_suppliers = sum(
            1 for s in db.execute(select(Supplier)).scalars().all() if s.is_active
        )

        def active_attrs(t):
            return [a for a in t.attributes if a.is_active]

        def active_opts(a):
            return [o for o in a.options if o.is_active]

        def active_slots(t):
            return [s for s in t.slots if s.is_active]

        # configs(type_id) 按 depth 记忆化（depth 影响截断）
        memo: dict[tuple[int, int], int] = {}

        def configs(type_id: int, depth: int) -> int:
            t = by_id.get(type_id)
            if t is None or not t.is_active:
                return 0
            if depth > max_depth:
                return 0
            key = (type_id, depth)
            if key in memo:
                return memo[key]
            memo[key] = 0  # 占位防环（DAG 理论无环，稳妥起见）

            n = 1
            for a in active_attrs(t):
                k = len(active_opts(a))
                if a.is_required:
                    if k == 0:
                        memo[key] = 0
                        return 0
                    n = _clamp(n * k)
                else:
                    n = _clamp(n * (k + 1))

            # 槽：非互斥逐个相乘；互斥组成员填法相加
            slots = active_slots(t)
            groups: dict[str, list] = {}
            for s in slots:
                if s.variant_group:
                    groups.setdefault(s.variant_group, []).append(s)

            def slot_choices(s) -> int:
                c = configs(s.child_type_id, depth + 1)
                p = parts_by_type.get(s.child_type_id, 0) if s.allow_blackbox else 0
                return c + p

            for s in slots:
                if s.variant_group:
                    continue
                ch = slot_choices(s)
                if s.is_required:
                    if ch == 0:
                        memo[key] = 0
                        return 0
                    n = _clamp(n * ch)
                else:
                    n = _clamp(n * (ch + 1))

            for gname, gslots in groups.items():
                gsum = sum(slot_choices(s) for s in gslots)
                if gsum == 0:
                    memo[key] = 0
                    return 0
                n = _clamp(n * gsum)

            memo[key] = n
            return n

        roots = [t for t in types if t.is_sellable_root and t.is_active]
        print("=" * 78)
        print(f"模板 SKU 组合上限（max_config_depth={max_depth}，活跃供应商={n_suppliers}）")
        print(f"封顶值 CAP={CAP:,}（达到即记为「≥CAP，实质无界」）")
        print("=" * 78)
        print(f"{'可售根类型':<16}{'白盒配置数':>18}{'整机直采件':>12}{'小计':>18}")
        print("-" * 78)
        total = 0
        rows = []
        for r in sorted(roots, key=lambda x: x.name):
            wb = configs(r.id, 1)
            direct = parts_by_type.get(r.id, 0)
            sub = _clamp(wb + direct)
            total = _clamp(total + sub)
            rows.append((r.name, r.kind, wb, direct, sub))
            wbs = "≥CAP" if wb >= CAP else f"{wb:,}"
            subs = "≥CAP" if sub >= CAP else f"{sub:,}"
            print(f"{r.name:<16}{wbs:>18}{direct:>12}{subs:>18}")
        print("-" * 78)
        ts = "≥CAP（实质无界）" if total >= CAP else f"{total:,}"
        print(f"{'结构上限合计':<16}{'':>18}{'':>12}{ts:>18}")
        print("=" * 78)
        print("说明：")
        print("· 上述为「结构组合」上限——属性×部件槽递归×成品件选择，不含供应商维度。")
        print(f"· 若叠加采购来源维度（白盒每个节点可选 {n_suppliers} 家供应商或不标），")
        print("  空间将再放大若干个数量级，故真实跑数需设目标上限而非全量。")
        print("· 多数整机品类组合主要由部件槽递归贡献；属性轴本身很小。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
