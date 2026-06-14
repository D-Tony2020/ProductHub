"""供应商溯源升级·方案甲 P1 红线回归：
- 🔴 golden：不标供应商的配置，指纹与行为与升级前一致（dedup 不变）；
- 供应商入指纹：同规格标不同供应商 = 不同 SKU；标同一供应商 = dedup 命中；
- 重建稳定：带供应商的 SKU 反推重算指纹不变（健康检测/治理流可靠）；
- 停用供应商：lenient 体检走 supply 软警(supplier_disabled)，不阻断。
全套 51 项若仍绿，即证明 no-supplier 序列化逐字节未变。
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


def _payload_cyl_supplier(template, supplier_id, charge="KG4"):
    """在 make_payload 的白盒筒体节点上标一个供应商。"""
    p = make_payload(template, charge=charge)
    cyl_sel = next(s for s in p.root.slots if s.slot_id == template["slot_cyl"].id)
    cyl_sel.child.supplier_id = supplier_id
    return p


def _create(client, payload, headers):
    return client.post("/api/v1/skus", json={"config": payload.model_dump()},
                       headers=headers).json()


def test_supplier_enters_fingerprint_as_identity(client, template, db):
    from app.models import Supplier

    admin = login(client, "admin", "admin@Test2026")
    s_hx = template["supplier"].id
    s_hf = Supplier(code="HF", name="浩丰")
    db.add(s_hf)
    db.commit()

    # 不标供应商
    base = _create(client, make_payload(template, charge="KG4"), admin)
    assert base["created"] is True

    # 同规格 + 筒体标华消 → 入指纹 → 不同 SKU
    a = _create(client, _payload_cyl_supplier(template, s_hx, "KG4"), admin)
    assert a["created"] is True
    assert a["sku"]["id"] != base["sku"]["id"]
    assert a["sku"]["fingerprint"] != base["sku"]["fingerprint"]

    # 同规格 + 筒体标浩丰 → 又一个不同 SKU
    b = _create(client, _payload_cyl_supplier(template, s_hf.id, "KG4"), admin)
    assert b["created"] is True
    assert b["sku"]["fingerprint"] != a["sku"]["fingerprint"]

    # 再次标华消同规格 → 命中既有指纹，dedup 不新建
    a2 = _create(client, _payload_cyl_supplier(template, s_hx, "KG4"), admin)
    assert a2["created"] is False
    assert a2["sku"]["id"] == a["sku"]["id"]


def test_supplier_sku_health_ok_and_fingerprint_stable(client, template, db):
    admin = login(client, "admin", "admin@Test2026")
    a = _create(client, _payload_cyl_supplier(template, template["supplier"].id, "KG8"), admin)
    sku_id, fp = a["sku"]["id"], a["sku"]["fingerprint"]
    # 带供应商的完整 SKU → 健康 ok（供应商在用）
    h = client.get(f"/api/v1/skus/{sku_id}/health", headers=admin).json()
    assert h["status"] == "ok"
    # 反推重算不改指纹（体检/治理流可靠）
    detail = client.get(f"/api/v1/skus/{sku_id}", headers=admin).json()
    assert detail["fingerprint"] == fp
    # 来源地图：筒体节点带上供应商名
    def walk(n):
        yield n
        for c in n.get("children", []):
            yield from walk(c)
    names = [n.get("supplier_name") for n in walk(detail["config_tree"])]
    assert "华消" in names


def test_disabled_supplier_supply_warn_not_block(client, template, db):
    admin = login(client, "admin", "admin@Test2026")
    a = _create(client, _payload_cyl_supplier(template, template["supplier"].id, "KG4"), admin)
    sku_id = a["sku"]["id"]
    # 停用供应商后体检：黄色 supply 警示(supplier_disabled)，不拦
    template["supplier"].is_active = False
    db.commit()
    h = client.get(f"/api/v1/skus/{sku_id}/health", headers=admin).json()
    assert h["status"] == "supply_warn" and h["blocking"] is False
    assert any(i["supply_kind"] == "supplier_disabled" for i in h["families"]["supply"]), h
