# -*- coding: utf-8 -*-
"""验收 Gate2·业务写场景（指向一次性克隆库 producthub_accept，绝不污染 dev）。
进程内 TestClient + 真实 JWT(make_access_token)，端到端验真实鉴权+RBAC+业务红线。
覆盖：建SKU+去重+指纹不可变 / 录价+同日纠错 / 报价E2E+导出冻结 / RBAC 403 / 跨用户IDOR 404 /
      作废恢复 / 部件改名 resync。
用法： .venv\\Scripts\\python.exe scripts\\accept_gate2_write.py
"""
import os
os.environ["PRODUCTHUB_DATABASE_URL"] = \
    "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub_accept"

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import make_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AppUser, AttributeOption, Sku, SkuConfigNode,
)
from app.services.health_engine import reconstruct_payload  # noqa: E402

API = "/api/v1"
db = SessionLocal()
client = TestClient(app)
PASS = FAIL = 0
LOG = []


def check(name, cond, detail=""):
    global PASS, FAIL
    PASS += bool(cond); FAIL += (not cond)
    line = f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else "")
    LOG.append(line); print(line)


admin = db.execute(select(AppUser).where(AppUser.username == "admin")).scalar_one()
sales = db.execute(select(AppUser).where(AppUser.username == "sales01")).scalar_one()
H_ADMIN = {"Authorization": f"Bearer {make_access_token(admin.id)}"}
H_SALES = {"Authorization": f"Bearer {make_access_token(sales.id)}"}


def load_sku(sid):
    return db.execute(
        select(Sku).where(Sku.id == sid).options(
            selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values),
            selectinload(Sku.nodes).selectinload(SkuConfigNode.purchased_part),
        )).scalar_one()


print("=== 场景 C1：建 SKU + 去重 + 指纹不可变（白盒配置树） ===")
# 找一个 active、根为白盒配置(root 非空、有可改属性) 的 SKU 作样本
cand_ids = db.execute(
    select(Sku.id).where(Sku.status == "active").order_by(Sku.id).limit(400)).scalars().all()
sample = None
payload = None
tweak = None
for sid in cand_ids:
    s = load_sku(sid)
    try:
        p = reconstruct_payload(s).model_dump()
    except Exception:
        continue
    if not p.get("root") or not p["root"].get("attributes"):
        continue
    # 找一个有"另一个在用选项"的属性来制造一个新配置
    for a in p["root"]["attributes"]:
        alt = db.execute(select(AttributeOption.id).where(
            AttributeOption.attribute_id == a["attribute_id"],
            AttributeOption.is_active.is_(True),
            AttributeOption.id != a["option_id"]).limit(1)).scalar()
        if alt:
            sample, payload = s, p
            import copy
            tweak = copy.deepcopy(p)
            for ta in tweak["root"]["attributes"]:
                if ta["attribute_id"] == a["attribute_id"]:
                    ta["option_id"] = alt
                    break
            break
    if sample:
        break

if sample is None:
    check("找到可测样本 SKU", False, "未找到含可改属性的白盒 SKU")
else:
    orig_fp, orig_code = sample.fingerprint, sample.sku_code
    # 1) 提交原配置 → 去重命中既有，不新建，指纹/编码 == 原
    r = client.post(f"{API}/skus", json={"config": payload}, headers=H_ADMIN)
    ok = r.status_code == 201
    j = r.json() if ok else {}
    check("提交原配置返回 201", ok, f"status={r.status_code}")
    if ok:
        check("原配置去重命中(created=False)", j.get("created") is False, f"created={j.get('created')}")
        check("去重返回同一 SKU(指纹一致)", j["sku"]["fingerprint"] == orig_fp)
        check("去重返回同一 SKU(编码一致)", j["sku"]["sku_code"] == orig_code)
    # 2) 提交改一个属性后的新配置 → 新指纹（异配置异指纹）
    r2 = client.post(f"{API}/skus", json={"config": tweak}, headers=H_ADMIN)
    ok2 = r2.status_code == 201
    j2 = r2.json() if ok2 else {}
    check("提交新配置返回 201", ok2, f"status={r2.status_code} body={r2.text[:160]}")
    if ok2:
        new_fp = j2["sku"]["fingerprint"]
        check("异配置异指纹(新指纹≠原)", new_fp != orig_fp, f"new={new_fp[:12]} orig={orig_fp[:12]}")
        check("新配置编码≠原编码", j2["sku"]["sku_code"] != orig_code)
        # 3) 再次提交同一新配置 → 去重稳定(created=False, 同指纹)
        r3 = client.post(f"{API}/skus", json={"config": tweak}, headers=H_ADMIN)
        j3 = r3.json()
        check("新配置二次提交去重稳定", j3.get("created") is False and j3["sku"]["fingerprint"] == new_fp)
    # 4) 原 SKU 落库指纹/编码绝未原地改（红线）
    db.expire_all()
    again = db.get(Sku, sample.id)
    check("原 SKU 指纹未原地改(红线)", again.fingerprint == orig_fp)
    check("原 SKU 编码未原地改(红线)", again.sku_code == orig_code)
    SAMPLE_ID = sample.id

print("\n=== 场景 C2：录价 + 同日纠错 supersede（admin 有录价权） ===")
pid_sku = db.execute(select(Sku.id).where(Sku.status == "active").order_by(Sku.id)).scalars().first()
r = client.post(f"{API}/skus/{pid_sku}/prices", json={"price": "123.45", "currency": "USD"}, headers=H_ADMIN)
check("录价 201", r.status_code == 201, f"status={r.status_code} body={r.text[:160]}")
r = client.get(f"{API}/skus/{pid_sku}/prices", headers=H_ADMIN)
prices = r.json() if r.status_code == 200 else []
cur = [p for p in prices if not p.get("superseded")]
check("现价含刚录入 123.45", any(str(p["price"]).startswith("123.45") for p in cur))
# 同日再录 → 纠错，旧行 superseded
r = client.post(f"{API}/skus/{pid_sku}/prices", json={"price": "130.00", "currency": "USD"}, headers=H_ADMIN)
check("同日纠错 201", r.status_code == 201, f"status={r.status_code}")
r = client.get(f"{API}/skus/{pid_sku}/prices", headers=H_ADMIN)
prices = r.json()
cur = [p for p in prices if not p.get("superseded")]
sup = [p for p in prices if p.get("superseded")]
check("同币种现价唯一", len([p for p in cur if p["currency"] == "USD"]) == 1, f"USD现价数={len([p for p in cur if p['currency']=='USD'])}")
check("现价更新为 130.00", any(str(p["price"]).startswith("130.0") for p in cur))
check("旧价 123.45 被 supersede 灰显", any(str(p["price"]).startswith("123.45") for p in sup))

print("\n=== 场景 C3：RBAC — sales(无录价权) 录价应 403 ===")
r = client.post(f"{API}/skus/{pid_sku}/prices", json={"price": "1.00", "currency": "USD"}, headers=H_SALES)
check("sales 录价被拒 403", r.status_code == 403, f"status={r.status_code}")

print("\n=== 场景 C4：报价单 E2E + 导出冻结 ===")
r = client.post(f"{API}/quotes", json={"customer_name": "验收测试客户A"}, headers=H_ADMIN)
check("建报价单 201", r.status_code == 201, f"status={r.status_code} body={r.text[:160]}")
qid = r.json()["id"] if r.status_code == 201 else None
if qid:
    r = client.post(f"{API}/quotes/{qid}/items", json={"sku_id": pid_sku, "qty": 2}, headers=H_ADMIN)
    check("加入报价明细 201", r.status_code == 201, f"status={r.status_code} body={r.text[:160]}")
    r = client.post(f"{API}/quotes/{qid}/export", headers=H_ADMIN)
    check("导出报价单 200", r.status_code == 200, f"status={r.status_code}")
    check("导出为 xlsx", "spreadsheet" in r.headers.get("content-type", ""), r.headers.get("content-type", "")[:40])
    # 导出后冻结：再改明细应 409
    r = client.post(f"{API}/quotes/{qid}/items", json={"sku_id": pid_sku, "qty": 1}, headers=H_ADMIN)
    check("导出后加明细被冻结 409", r.status_code == 409, f"status={r.status_code}")

    print("\n=== 场景 C5：跨用户 IDOR — sales 访问 admin 的报价单应 404 ===")
    r = client.get(f"{API}/quotes/{qid}", headers=H_SALES)
    check("跨用户读报价单 404", r.status_code == 404, f"status={r.status_code}")
    r = client.patch(f"{API}/quotes/{qid}", json={"customer_name": "篡改"}, headers=H_SALES)
    check("跨用户改报价单 404", r.status_code == 404, f"status={r.status_code}")

print("\n=== 场景 C6：SKU 作废 / 恢复 ===")
ret_sku = db.execute(select(Sku.id).where(Sku.status == "active").order_by(Sku.id.desc())).scalars().first()
r = client.post(f"{API}/skus/{ret_sku}/retire", headers=H_ADMIN)
check("作废 200", r.status_code == 200, f"status={r.status_code}")
db.expire_all()
check("状态变 retired", db.get(Sku, ret_sku).status == "retired")
r = client.post(f"{API}/skus/{ret_sku}/restore", headers=H_ADMIN)
check("恢复 200", r.status_code == 200)
db.expire_all()
check("状态回 active", db.get(Sku, ret_sku).status == "active")

print("\n=== 场景 C7：部件改名 → 引用 SKU 摘要名 resync，指纹/编码不变（红线） ===")
# 找一个被某 SKU 黑盒引用的 purchased_part
row = db.execute(
    select(SkuConfigNode.purchased_part_id, SkuConfigNode.sku_id)
    .where(SkuConfigNode.purchased_part_id.is_not(None)).limit(1)).first()
if row:
    part_id, ref_sku_id = row
    before = db.get(Sku, ref_sku_id)
    fp_before, code_before, name_before = before.fingerprint, before.sku_code, before.name
    r = client.patch(f"{API}/purchased-parts/{part_id}", json={"name": "验收改名件XYZ"}, headers=H_ADMIN)
    check("部件改名 200", r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")
    db.expire_all()
    after = db.get(Sku, ref_sku_id)
    check("引用 SKU 指纹未变(红线)", after.fingerprint == fp_before)
    check("引用 SKU 编码未变(红线)", after.sku_code == code_before)
    check("引用 SKU 摘要名已 resync", "验收改名件XYZ" in (after.name or ""), f"name={after.name}")
else:
    check("找到黑盒引用部件", False, "无 purchased_part 引用")

print(f"\n==== Gate2 写场景结果：{PASS} passed, {FAIL} failed ====")
db.close()
