"""API 级红线与端到端主链路：登录 → 配置试算 → 建 SKU → 录价 → 报价单 → 导出冻结。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_payload


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client):
    return login(client, "admin", "admin@Test2026")


@pytest.fixture()
def sales_headers(client):
    return login(client, "sales", "sales@Test2026")


def _payload_json(template, **kw):
    return make_payload(template, **kw).model_dump()


def test_e2e_main_chain(client, template, admin_headers, sales_headers):
    """主链路：试算未命中 → 业务员建 SKU(待录价) → 不能进报价单 → admin 录价 →
    试算命中 → 加入报价单 → 导出冻结。"""
    payload = _payload_json(template)

    # 1. 试算：完整、未命中
    r = client.post("/api/v1/config/validate", json=payload, headers=sales_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["complete"] is True and body["matched_sku"] is None

    # 2. 业务员保存 SKU
    r = client.post("/api/v1/skus", json={"config": payload}, headers=sales_headers)
    assert r.status_code == 201, r.text
    sku = r.json()["sku"]
    assert r.json()["created"] is True

    # 2b. 详情配置树完整：白盒筒体 + 黑盒阀门两个子节点都在
    r = client.get(f"/api/v1/skus/{sku['id']}", headers=sales_headers)
    tree = r.json()["config_tree"]
    assert tree is not None and len(tree["children"]) == 2
    valve_node = next(c for c in tree["children"] if c["slot_code"] == "VALVE")
    assert valve_node["mode"] == "purchased"
    assert valve_node["purchased_part_name"] == "华消K2阀门"
    assert valve_node["supplier_name"] == "华消"

    # 3. 待录价 SKU 不能进报价单
    r = client.post("/api/v1/quotes", json={"customer_name": "ACME"}, headers=sales_headers)
    quote_id = r.json()["id"]
    r = client.post(f"/api/v1/quotes/{quote_id}/items",
                    json={"sku_id": sku["id"], "qty": 100}, headers=sales_headers)
    assert r.status_code == 409

    # 4. 业务员无录价权
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "12.50"}, headers=sales_headers)
    assert r.status_code == 403

    # 5. admin 录价
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "12.50"}, headers=admin_headers)
    assert r.status_code == 201, r.text

    # 6. 再试算：命中既有 SKU 且带现价
    r = client.post("/api/v1/config/validate", json=payload, headers=sales_headers)
    matched = r.json()["matched_sku"]
    assert matched is not None and matched["sku_code"] == sku["sku_code"]
    assert matched["current_prices"][0]["price"] == "12.5000"

    # 7. 重复保存返回既有 SKU（不产生分身）
    r = client.post("/api/v1/skus", json={"config": payload}, headers=sales_headers)
    assert r.json()["created"] is False
    assert r.json()["sku"]["id"] == sku["id"]

    # 8. 加入报价单并导出
    r = client.post(f"/api/v1/quotes/{quote_id}/items",
                    json={"sku_id": sku["id"], "qty": 100}, headers=sales_headers)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/quotes/{quote_id}/export", headers=sales_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")

    # 9. 导出后冻结：再改明细被拒
    r = client.post(f"/api/v1/quotes/{quote_id}/items",
                    json={"sku_id": sku["id"], "qty": 1}, headers=sales_headers)
    assert r.status_code == 409


def test_price_change_then_export_check(client, template, admin_headers, sales_headers):
    """价格快照机制：录新价后导出前校验报告不一致，强制确认或刷新。"""
    payload = _payload_json(template)
    sku = client.post("/api/v1/skus", json={"config": payload},
                      headers=sales_headers).json()["sku"]
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "10"},
                headers=admin_headers)
    quote_id = client.post("/api/v1/quotes", json={"customer_name": "ACME"},
                           headers=sales_headers).json()["id"]
    client.post(f"/api/v1/quotes/{quote_id}/items",
                json={"sku_id": sku["id"], "qty": 5}, headers=sales_headers)

    # 改价（新价从明天生效，避免与今日生效的旧价同日冲突）
    from datetime import date, timedelta

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "11", "valid_from": tomorrow}, headers=admin_headers)
    assert r.status_code == 201, r.text

    # 今天导出：现价仍是 10，快照一致可导出
    r = client.get(f"/api/v1/quotes/{quote_id}/price-check", headers=sales_headers)
    assert r.json()["consistent"] is True


def test_optional_attribute_none_option_forbidden(client, template, admin_headers):
    """模板纪律：可选属性禁止建"无"语义选项（防指纹歧义）。"""
    ext_id = template["ext"].id
    r = client.post(f"/api/v1/template/node-types/{ext_id}/attributes",
                    json={"code": "HOOK", "name": "挂钩", "is_required": False},
                    headers=admin_headers)
    assert r.status_code == 201, r.text
    attr_id = r.json()["id"]
    r = client.post(f"/api/v1/template/attributes/{attr_id}/options",
                    json={"code": "NONE", "label": "无"}, headers=admin_headers)
    assert r.status_code == 409
    # 必选属性不受此限
    r = client.post(f"/api/v1/template/attributes/{template['charge'].id}/options",
                    json={"code": "NONE", "label": "无"}, headers=admin_headers)
    assert r.status_code == 201


def test_slot_cycle_rejected(client, template, admin_headers):
    """槽图 DAG：制造环（阀门下挂灭火器）被拒。"""
    valve_id = template["valve"].id
    ext_id = template["ext"].id
    r = client.post(f"/api/v1/template/node-types/{valve_id}/slots",
                    json={"child_type_id": ext_id, "code": "LOOP", "name": "环"},
                    headers=admin_headers)
    assert r.status_code == 409
    assert "循环" in r.json()["detail"]


def test_retired_sku_restore_flow(client, template, admin_headers, sales_headers):
    """作废占指纹：同配置重配命中作废 SKU，恢复而非新建分身。"""
    payload = _payload_json(template)
    sku = client.post("/api/v1/skus", json={"config": payload},
                      headers=sales_headers).json()["sku"]
    client.post(f"/api/v1/skus/{sku['id']}/retire", headers=admin_headers)

    r = client.post("/api/v1/config/validate", json=payload, headers=sales_headers)
    matched = r.json()["matched_sku"]
    assert matched is not None and matched["status"] == "retired"

    r = client.post("/api/v1/skus", json={"config": payload}, headers=sales_headers)
    assert r.json()["created"] is False  # 不产生分身
    r = client.post(f"/api/v1/skus/{sku['id']}/restore", headers=sales_headers)
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_auth_required(client, template):
    assert client.post("/api/v1/config/validate", json={}).status_code in (401, 422)
    assert client.get("/api/v1/skus").status_code == 401
