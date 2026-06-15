"""整机直采（黑盒整机）：根节点 = 一个整机采购件(product+可售根)，直接成为可售 SKU。

红线回归：根 token 用 "P:{件号}"，与既有配置根 "C:" 前缀整串首字符即不同
→ 既有 SKU 指纹逐字节零影响；同件去重、异件异指纹、灰盒不入指纹。
"""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_payload


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client, u, p):
    r = client.post("/api/v1/auth/login", json={"username": u, "password": p})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_assembly_part(db, template, *, code="PP-T-OEM1", name="华消整机OEM", status="active"):
    """整机采购件：node_type=可售根整机(ext)，挂供应商(华消)。"""
    from app.models import PurchasedPart
    part = PurchasedPart(code=code, node_type_id=template["ext"].id,
                         supplier_id=template["supplier"].id, name=name, status=status)
    db.add(part)
    db.commit()
    return part


def _expected_fp(part_code: str) -> str:
    return hashlib.sha256(f"P:{part_code}".encode("utf-8")).hexdigest()


def _direct_payload(template, part_id):
    return {"config": {"root_type_id": template["ext"].id, "root_purchased_part_id": part_id}}


def test_create_and_fingerprint(client, db, template):
    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    r = client.post("/api/v1/skus", json=_direct_payload(template, oem.id), headers=admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True
    assert body["sku"]["fingerprint"] == _expected_fp(oem.code)
    assert oem.name in body["sku"]["name"]


def test_dedup_same_part(client, db, template):
    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    a = client.post("/api/v1/skus", json=_direct_payload(template, oem.id), headers=admin).json()
    b = client.post("/api/v1/skus", json=_direct_payload(template, oem.id), headers=admin).json()
    assert a["created"] is True and b["created"] is False
    assert a["sku"]["id"] == b["sku"]["id"]


def test_distinct_parts_distinct_fingerprints(client, db, template):
    admin = login(client, "admin", "admin@Test2026")
    o1 = _make_assembly_part(db, template, code="PP-T-OEM1", name="华消整机A")
    o2 = _make_assembly_part(db, template, code="PP-T-OEM2", name="华消整机B")
    fp1 = client.post("/api/v1/skus", json=_direct_payload(template, o1.id),
                      headers=admin).json()["sku"]["fingerprint"]
    fp2 = client.post("/api/v1/skus", json=_direct_payload(template, o2.id),
                      headers=admin).json()["sku"]["fingerprint"]
    assert fp1 != fp2
    assert fp1 == _expected_fp("PP-T-OEM1") and fp2 == _expected_fp("PP-T-OEM2")


def test_direct_distinct_from_configured_no_collision(client, db, template):
    """整机直采(P:) 与逐项配置(C:) 指纹不同，且配置 SKU 指纹不以 P: token 开头。"""
    admin = login(client, "admin", "admin@Test2026")
    cfg = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    oem = _make_assembly_part(db, template)
    direct = client.post("/api/v1/skus", json=_direct_payload(template, oem.id),
                         headers=admin).json()["sku"]
    assert cfg["fingerprint"] != direct["fingerprint"]
    assert direct["fingerprint"] == _expected_fp(oem.code)


def test_wrong_type_part_rejected(client, db, template):
    """整机件类型≠根品类 → 422（拿部件 valve 件当整机根直采应失败）。"""
    admin = login(client, "admin", "admin@Test2026")
    r = client.post("/api/v1/skus", json=_direct_payload(template, template["part"].id),
                    headers=admin)
    assert r.status_code == 422, r.text


def test_retired_assembly_part_rejected(client, db, template):
    admin = login(client, "admin", "admin@Test2026")
    dead = _make_assembly_part(db, template, code="PP-T-DEAD", name="停用整机", status="retired")
    r = client.post("/api/v1/skus", json=_direct_payload(template, dead.id), headers=admin)
    assert r.status_code == 422, r.text


def test_nonexistent_part_rejected(client, db, template):
    admin = login(client, "admin", "admin@Test2026")
    r = client.post("/api/v1/skus", json=_direct_payload(template, 999999), headers=admin)
    assert r.status_code == 422, r.text


def test_payload_must_have_exactly_one_root(client, db, template):
    """schema 校验：root 与 root_purchased_part_id 二选一（两者都给 → 422）。"""
    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    both = {"config": {
        "root_type_id": template["ext"].id,
        "root": make_payload(template).model_dump()["root"],
        "root_purchased_part_id": oem.id,
    }}
    assert client.post("/api/v1/skus", json=both, headers=admin).status_code == 422
    neither = {"config": {"root_type_id": template["ext"].id}}
    assert client.post("/api/v1/skus", json=neither, headers=admin).status_code == 422


def test_graybox_spec_not_in_fingerprint(client, db, template):
    """整机件挂灰盒规格不改指纹（指纹只认件号）；详情应能读到规格摘要。"""
    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    # 挂灰盒纯文本规格
    client.patch(f"/api/v1/purchased-parts/{oem.id}/spec",
                 json={"spec_note": "充装量2kg / 碳钢筒体", "spec_config": None}, headers=admin)
    body = client.post("/api/v1/skus", json=_direct_payload(template, oem.id),
                       headers=admin).json()
    assert body["sku"]["fingerprint"] == _expected_fp(oem.code)  # 规格不进指纹


def test_direct_sku_health_roundtrip(client, db, template):
    """落库后 reconstruct→重算 指纹 == 原指纹（健康/治理路径一致）；健康 ok。"""
    from app.services.config_engine import validate_config
    from app.services.health_engine import (
        compute_health,
        load_sku_for_health,
        reconstruct_payload,
    )

    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    sku_id = client.post("/api/v1/skus", json=_direct_payload(template, oem.id),
                         headers=admin).json()["sku"]["id"]
    db.expire_all()
    sku = load_sku_for_health(db, sku_id)
    payload = reconstruct_payload(sku)
    assert payload.root_purchased_part_id == oem.id and payload.root is None
    result, _ = validate_config(db, payload, lenient=True)
    assert result.complete is True
    assert result.fingerprint == _expected_fp(oem.code)
    assert compute_health(db, sku).status == "ok"


def test_direct_sku_quotable(client, db, template):
    """整机直采 SKU 可正常录价、进现价（与组配 SKU 同范式）。"""
    admin = login(client, "admin", "admin@Test2026")
    oem = _make_assembly_part(db, template)
    sku_id = client.post("/api/v1/skus", json=_direct_payload(template, oem.id),
                         headers=admin).json()["sku"]["id"]
    r = client.post(f"/api/v1/skus/{sku_id}/prices", json={"price": "88.5"}, headers=admin)
    assert r.status_code in (200, 201), r.text
    detail = client.get(f"/api/v1/skus/{sku_id}", headers=admin).json()
    assert any(float(p["price"]) == 88.5 for p in detail["current_prices"])
