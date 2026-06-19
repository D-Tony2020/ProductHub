"""M2 回归：① 供应商分类筛选 / ② 档位二双维上级归属 / ③ C dry-run 影响面预演 /
④ B 治理闭环(修改SKU=新建+血缘，旧SKU停用或保活，指纹永不原地改)。
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_payload


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create(client, template, headers, **kw):
    return client.post("/api/v1/skus",
                       json={"config": make_payload(template, **kw).model_dump()},
                       headers=headers).json()["sku"]


# ---------- ① 供应商分类筛选（出现即计入；自产无供应商不返回）----------

def test_supplier_filter(client, template):
    admin = login(client, "admin", "admin@Test2026")
    _create(client, template, admin, charge="KG4", valve_mode="purchased")   # 黑盒阀门→华消
    _create(client, template, admin, charge="KG8", valve_mode="configured")  # 白盒阀门→无供应商
    assert client.get("/api/v1/skus", headers=admin).json()["total"] == 2
    r = client.get("/api/v1/skus", params={"supplier_id": template["supplier"].id},
                   headers=admin).json()
    assert r["total"] == 1                       # 仅用到该供应商成品件的那只命中
    # 不存在的供应商 → 空
    assert client.get("/api/v1/skus", params={"supplier_id": 999999},
                      headers=admin).json()["total"] == 0


def test_supplier_filter_includes_whitebox(client, template):
    """供应商口径 = 黑盒(经成品件) ∪ 白盒(节点级供应商标注)，与关联成品页 / 概览 linked_skus 同口径：
    既要命中经其成品件供货的 SKU，也要命中仅在白盒节点上标注其来源的 SKU。"""
    admin = login(client, "admin", "admin@Test2026")
    sup = template["supplier"].id
    # 黑盒：阀门经该供应商成品件
    _create(client, template, admin, charge="KG4", valve_mode="purchased")
    # 白盒：阀门自配(不经任何成品件)，仅在筒体节点直接标注该供应商
    p = make_payload(template, charge="KG8", valve_mode="configured")
    cyl_sel = next(s for s in p.root.slots if s.slot_id == template["slot_cyl"].id)
    cyl_sel.child.supplier_id = sup
    client.post("/api/v1/skus", json={"config": p.model_dump()}, headers=admin)
    # 黑、白两只都应落入该供应商（并集）
    assert client.get("/api/v1/skus", params={"supplier_id": sup},
                      headers=admin).json()["total"] == 2


def test_part_rename_resyncs_sku_name(client, template, db):
    """成品件改名 → 引用它的 SKU 展示名实时同步；红线：sku_code / fingerprint 永不变。"""
    from app.models import Sku
    admin = login(client, "admin", "admin@Test2026")
    res = _create(client, template, admin, charge="KG4", valve_mode="purchased")  # 黑盒阀门=华消K2阀门
    sku_id = res["id"]
    assert template["part"].name in res["name"]          # 创建时展示名内含件名（华消K2阀门）
    old_code = res["sku_code"]
    old_fp = db.get(Sku, sku_id).fingerprint
    r = client.patch(f"/api/v1/purchased-parts/{template['part'].id}",
                     json={"name": "华消K3阀门改"}, headers=admin)
    assert r.status_code == 200
    db.expire_all()
    s = db.get(Sku, sku_id)
    assert "华消K3阀门改" in s.name                        # 展示名已随件名同步
    assert "华消K2阀门" not in s.name                      # 旧件名已脱离
    assert s.sku_code == old_code                         # 红线：编码不可变
    assert s.fingerprint == old_fp                        # 红线：指纹不可变


# ---------- ② 档位二：双维上级归属 ----------

def test_node_type_parents_two_dimensions(client, template):
    admin = login(client, "admin", "admin@Test2026")
    cyl, ext = template["cyl"], template["ext"]
    r = client.get(f"/api/v1/template/node-types/{cyl.id}/parents", headers=admin).json()
    assert [p["id"] for p in r["direct"]] == [ext.id]            # 部件级：直接上级=灭火器
    assert [p["id"] for p in r["root_categories"]] == [ext.id]   # 品类级：可售根=灭火器
    # 根品类自身无上级
    r2 = client.get(f"/api/v1/template/node-types/{ext.id}/parents", headers=admin).json()
    assert r2["direct"] == [] and r2["root_categories"] == []


# ---------- ③ C dry-run：编辑前影响面预演（不落库）----------

def test_dry_run_impact_option_disable(client, template):
    admin = login(client, "admin", "admin@Test2026")
    _create(client, template, admin, material="CS")   # 完整 SKU，用到 MATERIAL.CS
    cs = template["options"]["MATERIAL.CS"]
    ss = template["options"]["MATERIAL.SS"]

    r = client.post("/api/v1/template/preview-impact",
                    json={"entity_type": "option", "entity_id": cs.id,
                          "changes": {"is_active": False}}, headers=admin).json()
    assert r["candidate_count"] >= 1
    assert r["newly_broken"] == 1                 # 该 SKU 由 ok 变 supply_warn
    assert r["by_family"]["supply"] == 1
    assert r["samples"][0]["status"] == "supply_warn"

    # 预演绝不落库：CS 仍 active
    opts = client.get(f"/api/v1/template/attributes/{template['material'].id}/options",
                      headers=admin).json()
    assert next(o for o in opts if o["id"] == cs.id)["is_active"] is True

    # 停用未被任何 SKU 使用的 SS → 零破坏
    r2 = client.post("/api/v1/template/preview-impact",
                     json={"entity_type": "option", "entity_id": ss.id,
                           "changes": {"is_active": False}}, headers=admin).json()
    assert r2["newly_broken"] == 0


# ---------- ④ B 治理闭环：修改SKU=新建+血缘，指纹不原地改 ----------

def test_modify_sku_creates_new_and_supersedes_keep_alive(client, template):
    admin = login(client, "admin", "admin@Test2026")
    a = _create(client, template, admin, charge="KG4")
    r = client.post(f"/api/v1/skus/{a['id']}/update",
                    json={"config": make_payload(template, charge="KG8").model_dump(),
                          "retire_old": False}, headers=admin)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["created"] is True
    assert res["new_sku"]["id"] != a["id"]
    assert res["new_sku"]["fingerprint"] != a["fingerprint"]   # 新指纹，旧的没动
    assert res["old_sku"]["superseded_by_sku_id"] == res["new_sku"]["id"]
    assert res["old_sku"]["superseded_by_sku_code"] == res["new_sku"]["sku_code"]
    assert res["old_sku"]["status"] == "active"                # 保活=仍在售可报价

    # 已被取代的 SKU 不可再改
    r2 = client.post(f"/api/v1/skus/{a['id']}/update",
                     json={"config": make_payload(template, charge="KG4").model_dump()},
                     headers=admin)
    assert r2.status_code == 409


def test_modify_sku_retire_old(client, template):
    admin = login(client, "admin", "admin@Test2026")
    b = _create(client, template, admin, charge="KG4")
    res = client.post(f"/api/v1/skus/{b['id']}/update",
                      json={"config": make_payload(template, charge="KG8").model_dump(),
                            "retire_old": True}, headers=admin).json()
    assert res["old_sku"]["status"] == "retired"
    assert res["new_sku"]["health_status"] == "ok"


def test_modify_sku_no_change_rejected(client, template):
    admin = login(client, "admin", "admin@Test2026")
    c = _create(client, template, admin, charge="KG4")
    # 提交与原 SKU 完全相同的配置 → 命中既有指纹 → 无修改，409
    r = client.post(f"/api/v1/skus/{c['id']}/update",
                    json={"config": make_payload(template, charge="KG4").model_dump()},
                    headers=admin)
    assert r.status_code == 409
