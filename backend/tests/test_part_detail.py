"""采购件详情页 + 供应商用量看板（P2b）：
- /suppliers/overview 用量指标（采购项/整机供应/部件供应/关联成品）
- /purchased-parts/by-id 详情携带关联在售 SKU
- 编辑采购件交期/件名不改任何 SKU 指纹（红线：元数据不入指纹）
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from tests.conftest import make_payload


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_supplier_overview_metrics(client, db, template):
    """同一供应商：1 个部件供应(阀门·part) + 1 个整机供应(整机·product)；
    两个不同指纹的 SKU 均黑盒引用该供应商阀门 → 关联成品去重计 2。"""
    from app.models import PurchasedPart

    admin = login(client, "admin", "admin@Test2026")
    sup = template["supplier"]
    # 既有 PP-T-0001（阀门=part）；再加一个整机供应件（product kind）
    asm = PurchasedPart(code="PP-T-9001", node_type_id=template["ext"].id,
                        supplier_id=sup.id, name="华消整机OEM", status="active")
    db.add(asm)
    db.commit()

    client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG4").model_dump()},
                headers=admin)
    client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG8").model_dump()},
                headers=admin)

    ov = client.get("/api/v1/suppliers/overview", headers=admin).json()
    row = next(s for s in ov if s["id"] == sup.id)
    assert row["component_count"] == 1, row    # PP-T-0001 阀门(part)
    assert row["assembly_count"] == 1, row     # PP-T-9001 整机(product)
    assert row["procurement_items"] == 2, row
    assert row["linked_skus"] == 2, row        # 两个 SKU 黑盒引用同一供应商阀门，去重=2


def test_overview_counts_only_inuse_parts(client, db, template):
    """停用/合并件不计入采购项；无引用供应商关联成品=0。"""
    from app.models import PurchasedPart

    admin = login(client, "admin", "admin@Test2026")
    sup = template["supplier"]
    retired = PurchasedPart(code="PP-T-9002", node_type_id=template["valve"].id,
                            supplier_id=sup.id, name="停用阀门", status="retired")
    db.add(retired)
    db.commit()

    ov = client.get("/api/v1/suppliers/overview", headers=admin).json()
    row = next(s for s in ov if s["id"] == sup.id)
    # 仅 PP-T-0001(active) 计入，retired 不计
    assert row["procurement_items"] == 1, row
    assert row["linked_skus"] == 0, row        # 尚无 SKU 引用


def test_part_detail_linked_skus(client, template):
    admin = login(client, "admin", "admin@Test2026")
    part_id = template["part"].id
    a = client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG4").model_dump()},
                    headers=admin).json()["sku"]
    b = client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG8").model_dump()},
                    headers=admin).json()["sku"]

    d = client.get(f"/api/v1/purchased-parts/by-id/{part_id}", headers=admin).json()
    assert d["reference_count"] == 2, d
    assert {s["sku_code"] for s in d["linked_skus"]} == {a["sku_code"], b["sku_code"]}
    assert all(s["status"] == "active" for s in d["linked_skus"])
    assert d["code"] == "PP-T-0001"


def test_part_detail_no_links(client, template):
    """未被任何 SKU 引用的件：linked_skus 为空、reference_count=0。"""
    admin = login(client, "admin", "admin@Test2026")
    part_id = template["part"].id
    d = client.get(f"/api/v1/purchased-parts/by-id/{part_id}", headers=admin).json()
    assert d["linked_skus"] == []
    assert d["reference_count"] == 0


def test_part_edit_does_not_touch_fingerprint(client, db, template):
    """红线：编辑采购件交期/件名后，引用它的 SKU 指纹必须逐字节不变。"""
    from app.models import Sku

    admin = login(client, "admin", "admin@Test2026")
    part_id = template["part"].id
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    fp_before = db.execute(select(Sku.fingerprint).where(Sku.id == sku["id"])).scalar_one()

    r = client.patch(f"/api/v1/purchased-parts/{part_id}",
                     json={"lead_time_days": 21, "name": "华消K2阀门-改"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["lead_time_days"] == 21
    assert r.json()["name"] == "华消K2阀门-改"

    db.expire_all()
    fp_after = db.execute(select(Sku.fingerprint).where(Sku.id == sku["id"])).scalar_one()
    assert fp_before == fp_after


def test_part_detail_requires_auth(client, template):
    part_id = template["part"].id
    assert client.get(f"/api/v1/purchased-parts/by-id/{part_id}").status_code == 401
    assert client.get("/api/v1/suppliers/overview").status_code == 401
