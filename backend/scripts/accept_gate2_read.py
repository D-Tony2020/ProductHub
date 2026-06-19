# -*- coding: utf-8 -*-
"""验收 Gate2·业务读场景（指向 dev 库 producthub，只读，绝不写）。
进程内 TestClient + 真实 JWT，API total 对 SQL 真值核对。
覆盖：检索/筛选/排序/分页/币种/区间/quotable/sourcing、详情+BOM、统计、供应商黑∪白口径、
      结构化检索 sp_pair、边界(422/深翻页/404)。
用法： .venv\\Scripts\\python.exe scripts\\accept_gate2_read.py
"""
import os
os.environ["PRODUCTHUB_DATABASE_URL"] = \
    "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub"

from sqlalchemy import func, select, text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import make_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AppUser, AttributeOption, Sku, SkuAttributeValue, SkuConfigNode,
)

API = "/api/v1"
db = SessionLocal()
client = TestClient(app)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    PASS += bool(cond); FAIL += (not cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


admin = db.execute(select(AppUser).where(AppUser.username == "admin")).scalar_one()
H = {"Authorization": f"Bearer {make_access_token(admin.id)}"}


def total(**params):
    r = client.get(f"{API}/skus", params={**params, "page_size": 1}, headers=H)
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return r.json()["total"]


print("=== 场景 R1：检索总量对 SQL 真值 ===")
sql_all = db.execute(select(func.count()).select_from(Sku)).scalar()
check("全量 total == SQL", total() == sql_all, f"api={total()} sql={sql_all}")
sql_active = db.execute(select(func.count()).select_from(Sku).where(Sku.status == "active")).scalar()
check("status=active total == SQL", total(status="active") == sql_active, f"sql={sql_active}")

# 取一个有量的整机品类
rt = db.execute(select(Sku.root_type_id, func.count()).group_by(Sku.root_type_id)
                .order_by(func.count().desc())).first()
rtid, rtn = rt[0], rt[1]
check(f"root_type_id={rtid} total == SQL", total(root_type_id=rtid) == rtn, f"sql={rtn}")

print("\n=== 场景 R2：单规格(option_id) 命中对 SQL ===")
oid = db.execute(
    select(SkuAttributeValue.option_id, func.count(func.distinct(SkuConfigNode.sku_id)))
    .join(SkuConfigNode, SkuConfigNode.id == SkuAttributeValue.config_node_id)
    .group_by(SkuAttributeValue.option_id).order_by(func.count(func.distinct(SkuConfigNode.sku_id)).desc())
).first()
oid_id, oid_cnt = oid[0], oid[1]
check(f"option_id={oid_id} total == SQL", total(option_id=oid_id) == oid_cnt, f"sql={oid_cnt}")

print("\n=== 场景 R3：结构化检索 sp_pair(供应商×件类型, 黑∪白) 对 SQL ===")
# 取一个黑盒(成品件)节点的 (supplier, node_type) 对，算黑∪白真值
pair = db.execute(text(
    "SELECT pp.supplier_id, scn.node_type_id, count(DISTINCT scn.sku_id) n "
    "FROM sku_config_node scn JOIN purchased_part pp ON pp.id=scn.purchased_part_id "
    "GROUP BY 1,2 ORDER BY n DESC LIMIT 1")).first()
sid, ntid, _n = pair[0], pair[1], pair[2]
truth = db.execute(text(
    "SELECT count(DISTINCT s.id) FROM sku s WHERE "
    " s.id IN (SELECT scn.sku_id FROM sku_config_node scn JOIN purchased_part pp ON pp.id=scn.purchased_part_id "
    "          WHERE pp.supplier_id=:sid AND scn.node_type_id=:ntid) "
    " OR s.id IN (SELECT sku_id FROM sku_config_node WHERE supplier_id=:sid AND node_type_id=:ntid)"),
    {"sid": sid, "ntid": ntid}).scalar()
check(f"sp_pair={sid}:{ntid} total == SQL黑∪白", total(sp_pair=f"{sid}:{ntid}") == truth, f"api={total(sp_pair=f'{sid}:{ntid}')} sql={truth}")

print("\n=== 场景 R4：供应商过滤(黑∪白) 对 SQL ===")
sup_id = sid
truth_sup = db.execute(text(
    "SELECT count(DISTINCT s.id) FROM sku s WHERE s.status='active' AND ("
    " s.id IN (SELECT scn.sku_id FROM sku_config_node scn JOIN purchased_part pp ON pp.id=scn.purchased_part_id WHERE pp.supplier_id=:sid)"
    " OR s.id IN (SELECT sku_id FROM sku_config_node WHERE supplier_id=:sid))"),
    {"sid": sup_id}).scalar()
check(f"supplier_id={sup_id}&active total == SQL黑∪白", total(supplier_id=sup_id, status="active") == truth_sup, f"sql={truth_sup}")

print("\n=== 场景 R5：供应商品类细分 sum(count) == 黑∪白下钻总量 ===")
r = client.get(f"{API}/suppliers/{sup_id}/category-breakdown", headers=H)
if r.status_code == 200:
    bd = r.json()
    s_sum = sum(x["count"] for x in bd)
    check("category-breakdown sum == 供应商active总量", s_sum == truth_sup, f"sum={s_sum} truth={truth_sup}")
    # 下钻某件类型 count == /skus supplier_part_type total
    if bd:
        b0 = bd[0]
        t = total(supplier_id=sup_id, supplier_part_type_id=b0["node_type_id"], status="active")
        check(f"下钻件类型{b0['node_type_id']} count 对上 /skus", t == b0["count"], f"api={t} breakdown={b0['count']}")
else:
    check("category-breakdown 可用", False, f"status={r.status_code}")

print("\n=== 场景 R6：详情 + BOM + 价格 ===")
sid_detail = db.execute(select(Sku.id).where(Sku.status == "active").order_by(Sku.id)).scalars().first()
r = client.get(f"{API}/skus/{sid_detail}", headers=H)
check("详情 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    check("详情含配置树 config_tree/nodes", ("config_tree" in d) or ("nodes" in d), f"keys={list(d.keys())[:8]}")
r = client.get(f"{API}/skus/{sid_detail}/prices", headers=H)
check("价格历史 200", r.status_code == 200)

print("\n=== 场景 R7：统计 / 全貌 ===")
r = client.get(f"{API}/skus/stats", headers=H)
check("stats 200", r.status_code == 200, f"status={r.status_code}")
r = client.get(f"{API}/skus/overview", headers=H)
check("overview 200", r.status_code == 200)

print("\n=== 场景 R8：排序 / 币种 / 区间 / quotable / sourcing ===")
for srt in ("recent", "price_asc", "price_desc", "code", "name", "created_asc"):
    r = client.get(f"{API}/skus", params={"sort": srt, "currency": "USD", "page_size": 5}, headers=H)
    check(f"sort={srt} 200", r.status_code == 200, f"status={r.status_code}")
r = client.get(f"{API}/skus", params={"price_min": 50, "price_max": 200, "currency": "USD", "page_size": 1}, headers=H)
check("价格区间 200", r.status_code == 200)
r = client.get(f"{API}/skus", params={"quotable": "true", "currency": "USD", "page_size": 1}, headers=H)
check("quotable 200", r.status_code == 200)
for sc in ("blackbox", "whitebox", "direct"):
    r = client.get(f"{API}/skus", params={"sourcing": sc, "page_size": 1}, headers=H)
    check(f"sourcing={sc} 200", r.status_code == 200, f"status={r.status_code}")

print("\n=== 场景 R9：边界 / 容错 ===")
check("非法 status → 422", client.get(f"{API}/skus", params={"status": "xxx"}, headers=H).status_code == 422)
check("非法 sort → 422", client.get(f"{API}/skus", params={"sort": "xxx"}, headers=H).status_code == 422)
check("非法 currency → 422", client.get(f"{API}/skus", params={"currency": "usd"}, headers=H).status_code == 422)
rdeep = client.get(f"{API}/skus", params={"page": 99999, "page_size": 20}, headers=H)
check("深翻页优雅返回 200 空页", rdeep.status_code == 200 and rdeep.json()["items"] == [], f"status={rdeep.status_code}")
check("不存在 SKU → 404", client.get(f"{API}/skus/999999999", headers=H).status_code == 404)
check("未带令牌 → 401", client.get(f"{API}/skus").status_code == 401)

print(f"\n==== Gate2 读场景结果：{PASS} passed, {FAIL} failed ====")
db.close()
