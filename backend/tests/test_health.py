"""M1 止血包回归：三族健康检测（completeness/structural/supply）+ 报价硬闸/软提醒。

红线守护：完整 SKU 恒为 ok 且指纹稳定；模板收紧后既有 SKU 实时翻面（不碰指纹、不改库）；
红族（缺配/违反互斥）硬拦报价 409，黄族（停用/停产件）放行但回填提醒。
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


def _create_priced_sku(client, template, headers, **kw):
    """建一个完整 SKU 并录 USD 现价，返回 sku dict。"""
    sku = client.post("/api/v1/skus", json={"config": make_payload(template, **kw).model_dump()},
                      headers=headers).json()["sku"]
    r = client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "20"}, headers=headers)
    assert r.status_code == 201, r.text
    return sku


# ---------- 黄金不变量：完整 SKU 恒 ok，指纹稳定 ----------

def test_golden_complete_is_ok_and_fingerprint_stable(client, template):
    admin = login(client, "admin", "admin@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    fp0 = sku["fingerprint"]
    assert fp0

    h = client.get(f"/api/v1/skus/{sku['id']}/health", headers=admin).json()
    assert h["status"] == "ok"
    assert h["blocking"] is False and h["quotable"] is True
    assert h["families"]["completeness"] == []
    assert h["families"]["structural"] == []
    assert h["families"]["supply"] == []

    # 体检是只读推导：跑完后指纹分毫不动（不得污染落库数据）
    fp1 = client.get(f"/api/v1/skus/{sku['id']}", headers=admin).json()["fingerprint"]
    assert fp1 == fp0


# ---------- completeness（红）：模板新增必配槽 → 既有 SKU 缺配，硬拦报价 ----------

def test_completeness_drift_blocks_quote(client, template, db):
    from app.models import ComponentSlot, NodeType

    admin = login(client, "admin", "admin@Test2026")
    sku = _create_priced_sku(client, template, admin)

    # 模板收紧：给整机加一个全新的必配部件槽，既有 SKU 从未配置它 → 缺必配
    gauge = NodeType(code="GAUGE", name="压力表", kind="part")
    db.add(gauge)
    db.flush()
    db.add(ComponentSlot(parent_type_id=template["ext"].id, child_type_id=gauge.id,
                         code="GAUGE", name="压力表", is_required=True))
    db.commit()

    h = client.get(f"/api/v1/skus/{sku['id']}/health", headers=admin).json()
    assert h["status"] == "incomplete" and h["blocking"] is True and h["quotable"] is False
    assert h["families"]["completeness"], h
    assert any("压力表" in i["message"] for i in h["families"]["completeness"])

    # 统计带"待治理"计入
    assert client.get("/api/v1/skus/stats", headers=admin).json()["incomplete"] >= 1

    # 报价硬闸：残货进不了报价单，结构化 409
    qid = client.post("/api/v1/quotes", json={"customer_name": "拦截测试", "currency": "USD"},
                      headers=admin).json()["id"]
    r = client.post(f"/api/v1/quotes/{qid}/items", json={"sku_id": sku["id"], "qty": 1},
                    headers=admin)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "INCOMPLETE_SKU"
    assert detail["family"] == "completeness"
    assert detail["sku_code"] == sku["sku_code"]


# ---------- structural（红）：两个已填槽并入同一互斥组 → 违反"恰好一个" ----------

def test_structural_variant_violation_blocks_quote(client, template, db):
    admin = login(client, "admin", "admin@Test2026")
    sku = _create_priced_sku(client, template, admin)

    # 把两个本已各自配好的必配槽并入同一变体组：现在组内选了 2 个 → 违反恰好一个
    template["slot_cyl"].variant_group = "主部件"
    template["slot_valve"].variant_group = "主部件"
    db.commit()

    h = client.get(f"/api/v1/skus/{sku['id']}/health", headers=admin).json()
    assert h["status"] == "incomplete" and h["blocking"] is True
    assert h["families"]["structural"], h
    assert any("只能选择一种" in i["message"] for i in h["families"]["structural"])

    qid = client.post("/api/v1/quotes", json={"customer_name": "互斥测试", "currency": "USD"},
                      headers=admin).json()["id"]
    r = client.post(f"/api/v1/quotes/{qid}/items", json={"sku_id": sku["id"], "qty": 1},
                    headers=admin)
    assert r.status_code == 409
    assert r.json()["detail"]["family"] == "structural"


# ---------- supply（黄）：停用在用选项 → 警示但放行，回填提醒 ----------

def test_supply_disabled_option_warns_not_blocks(client, template, db):
    admin = login(client, "admin", "admin@Test2026")
    # 用白盒阀门，确保 SKU 实际引用了 cyl 的 MATERIAL.CS 选项
    sku = _create_priced_sku(client, template, admin, material="CS")

    template["options"]["MATERIAL.CS"].is_active = False
    db.commit()

    h = client.get(f"/api/v1/skus/{sku['id']}/health", headers=admin).json()
    assert h["status"] == "supply_warn"
    assert h["blocking"] is False and h["quotable"] is True   # 黄族不拦
    assert h["families"]["supply"], h
    assert h["families"]["completeness"] == [] and h["families"]["structural"] == []

    # 报价软提醒：可加入，且当次行回填 supply_warnings
    qid = client.post("/api/v1/quotes", json={"customer_name": "软提醒测试", "currency": "USD"},
                      headers=admin).json()["id"]
    r = client.post(f"/api/v1/quotes/{qid}/items", json={"sku_id": sku["id"], "qty": 1},
                    headers=admin)
    assert r.status_code == 201, r.text
    line = next(i for i in r.json()["items"] if i["sku_id"] == sku["id"])
    assert line["supply_warnings"], r.json()


# ---------- supply（黄）：在用成品件停产 → 警示但放行 ----------

def test_supply_retired_part_warns_not_blocks(client, template, db):
    admin = login(client, "admin", "admin@Test2026")
    sku = _create_priced_sku(client, template, admin, valve_mode="purchased")

    template["part"].status = "retired"
    db.commit()

    h = client.get(f"/api/v1/skus/{sku['id']}/health", headers=admin).json()
    assert h["status"] == "supply_warn" and h["blocking"] is False
    assert any(i["supply_kind"] == "part_retired" for i in h["families"]["supply"]), h
