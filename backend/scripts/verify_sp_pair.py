# -*- coding: utf-8 -*-
"""验证 /skus 的 sp_pair[] 多对来源约束（完整版结构化检索后端）。

方法：进程内 TestClient 跑【真实路由 + 真实 dev 库】，与一个【独立 Python oracle】双向比对。
oracle 不复用 API 的 SQL，而是逐 SKU 在内存里按"节点级谓词"判断（黑∪白），形成独立真值。

场景：
  1) 单对 ≡ 旧 supplier_id+supplier_part_type_id（同库同参，证 sp_pair 单对与既有口径全等）
  2) 双对非零（自动找一个与首对共现的第二对，证 AND 真生效、非恒零）
  3) 用户原查询：干粉灭火器+2kg+把手绿 + 筒体浩丰 + 虹吸管瑞丰
  4) 顺序无关：sp_pair=[A,B] == [B,A]
  5) 非法输入静默忽略：sp_pair=["abc","3","3:24"] == sp_pair=["3:24"]

用法： .venv\\Scripts\\python.exe scripts\\verify_sp_pair.py
"""
from collections import Counter

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.core.security import get_current_user
from app.main import app
from app.models import (
    AppUser, AttributeDef, AttributeOption, NodeType, PurchasedPart,
    Sku, SkuAttributeValue, SkuConfigNode, Supplier,
)

db = SessionLocal()
PASS, FAIL = 0, 0


def check(name, a, b):
    global PASS, FAIL
    ok = a == b
    PASS += ok
    FAIL += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: api={a} oracle={b}")


# ---- override 鉴权（搜索仅用 user 于 mine 过滤，这里不传 mine） ----
admin = db.execute(select(AppUser).where(AppUser.role == "admin")).scalars().first()
app.dependency_overrides[get_current_user] = lambda: admin
client = TestClient(app)


def api_count(**params):
    r = client.get("/api/v1/skus", params={**params, "page_size": 1})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return r.json()["total"]


# ---- 解析 id（按名取，不硬编码） ----
def nt(name):
    return db.execute(select(NodeType).where(NodeType.name == name)).scalars().first()


root = nt("干粉灭火器")
cyl = nt("干粉筒体")
siphon = nt("虹吸管")
handle = nt("把手")
print("节点类型:", {x.name: x.id for x in (root, cyl, siphon, handle) if x})

haofeng = db.execute(select(Supplier).where(Supplier.name.like("%浩丰%"))).scalars().first()
ruifeng = db.execute(select(Supplier).where(Supplier.name.like("%瑞丰%"))).scalars().all()
print("浩丰:", haofeng.id, haofeng.name)
print("瑞丰:", [(s.id, s.name) for s in ruifeng])

# 充装量=2kg、把手颜色=绿
fill_attr = db.execute(
    select(AttributeDef).where(AttributeDef.name.like("%充装量%"))).scalars().first()
opt_2kg = db.execute(select(AttributeOption).where(
    AttributeOption.attribute_id == fill_attr.id,
    AttributeOption.label.like("%2kg%"))).scalars().first()
color_attr = db.execute(select(AttributeDef).where(
    AttributeDef.node_type_id == handle.id, AttributeDef.name.like("%颜色%"))).scalars().first()
opt_green = db.execute(select(AttributeOption).where(
    AttributeOption.attribute_id == color_attr.id,
    AttributeOption.label.like("%绿%"))).scalars().first()
print("充装量2kg opt:", opt_2kg.id, opt_2kg.label, "| 把手颜色绿 opt:", opt_green.id, opt_green.label)

# ---- 构建独立 oracle：逐 SKU 内存判断 ----
print("\n加载全量 SKU 构建 oracle …")
skus = db.execute(
    select(Sku).options(
        selectinload(Sku.nodes).selectinload(SkuConfigNode.purchased_part),
        selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values),
    )
).scalars().all()
print(f"  共 {len(skus)} 个 SKU")

# 预计算每个 SKU：节点 (node_type_id -> set(供应商id, 黑白合并))、option 集合
sku_pairs = {}   # sku_id -> set((ntid, supplier_id))
sku_opts = {}    # sku_id -> set(option_id)
sku_root = {}
for s in skus:
    pairs = set()
    opts = set()
    for n in s.nodes:
        sids = set()
        if n.supplier_id is not None:
            sids.add(n.supplier_id)               # 白盒：节点直接标注
        if n.purchased_part is not None and n.purchased_part.supplier_id is not None:
            sids.add(n.purchased_part.supplier_id)  # 黑盒：外购件供应商
        for sid in sids:
            pairs.add((n.node_type_id, sid))
        for av in n.attribute_values:
            if av.option_id is not None:
                opts.add(av.option_id)
    sku_pairs[s.id] = pairs
    sku_opts[s.id] = opts
    sku_root[s.id] = s.root_type_id


def oracle(root_type_id=None, option_ids=(), pairs=()):
    """pairs: iterable of (supplier_id, node_type_id)，各自 AND；黑∪白已并入 sku_pairs。"""
    cnt = 0
    for s in skus:
        if root_type_id is not None and sku_root[s.id] != root_type_id:
            continue
        if not all(o in sku_opts[s.id] for o in option_ids):
            continue
        if not all((ntid, sid) in sku_pairs[s.id] for (sid, ntid) in pairs):
            continue
        cnt += 1
    return cnt


def pp(sid, ntid):
    return f"{sid}:{ntid}"


print("\n=== 场景 1：单对 ≡ 旧 supplier_id+supplier_part_type_id ===")
a_sp = api_count(root_type_id=root.id, sp_pair=[pp(haofeng.id, cyl.id)])
a_legacy = api_count(root_type_id=root.id, supplier_id=haofeng.id, supplier_part_type_id=cyl.id)
orc = oracle(root.id, pairs=[(haofeng.id, cyl.id)])
check("sp_pair[浩丰:筒体] vs oracle", a_sp, orc)
check("sp_pair[浩丰:筒体] vs legacy参数", a_sp, a_legacy)

print("\n=== 场景 2：双对非零（自动找与首对共现的第二对） ===")
# 在满足 root ∧ (浩丰,筒体) 的 SKU 里，统计其它 (ntid,sid) 共现频次，挑一个最常见的做第二对
base_ids = [s.id for s in skus
            if sku_root[s.id] == root.id and (cyl.id, haofeng.id) in sku_pairs[s.id]]
co = Counter()
for sid_ in base_ids:
    for (ntid2, sid2) in sku_pairs[sid_]:
        if (ntid2, sid2) != (cyl.id, haofeng.id):
            co[(ntid2, sid2)] += 1
print(f"  base(root∧浩丰×筒体)={len(base_ids)}；候选第二对 top5：{co.most_common(5)}")
if co:
    (ntid2, sid2), _ = co.most_common(1)[0]
    a_two = api_count(root_type_id=root.id,
                      sp_pair=[pp(haofeng.id, cyl.id), pp(sid2, ntid2)])
    orc_two = oracle(root.id, pairs=[(haofeng.id, cyl.id), (sid2, ntid2)])
    check(f"双对[浩丰:筒体 + {sid2}:{ntid2}]", a_two, orc_two)
    print(f"    （第二对 = 件类型{ntid2} ← 供应商{sid2}，命中应 >0 且 ≤ base）")

print("\n=== 场景 3：用户原查询（干粉灭火器+2kg+把手绿 + 筒体浩丰 + 虹吸管瑞丰） ===")
for rf in ruifeng:
    pairs = [(haofeng.id, cyl.id), (rf.id, siphon.id)]
    a = api_count(root_type_id=root.id, option_id=[opt_2kg.id, opt_green.id],
                  sp_pair=[pp(haofeng.id, cyl.id), pp(rf.id, siphon.id)])
    orc = oracle(root.id, option_ids=[opt_2kg.id, opt_green.id], pairs=pairs)
    check(f"筒体浩丰 + 虹吸管{rf.name}", a, orc)

print("\n=== 场景 4：顺序无关 ===")
if co:
    a_ab = api_count(root_type_id=root.id, sp_pair=[pp(haofeng.id, cyl.id), pp(sid2, ntid2)])
    a_ba = api_count(root_type_id=root.id, sp_pair=[pp(sid2, ntid2), pp(haofeng.id, cyl.id)])
    check("sp_pair[A,B] == [B,A]", a_ab, a_ba)

print("\n=== 场景 5：非法输入静默忽略 ===")
a_clean = api_count(root_type_id=root.id, sp_pair=[pp(haofeng.id, cyl.id)])
a_dirty = api_count(root_type_id=root.id,
                    sp_pair=["abc", "3", ":", "3:", ":24", "x:y", pp(haofeng.id, cyl.id)])
check("含非法对 == 仅合法对", a_dirty, a_clean)

print(f"\n==== 结果：{PASS} passed, {FAIL} failed ====")
db.close()
