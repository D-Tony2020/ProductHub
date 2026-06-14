"""SKU 库货架 P1：/skus/stats 统计与 node-types?with_counts 计数正确性。"""
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


def test_stats_and_counts(client, template):
    admin = login(client, "admin", "admin@Test2026")

    # SKU A：在售且录价；SKU B：在售但待录价（不同配置→不同指纹）
    a = client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG4").model_dump()},
                    headers=admin).json()["sku"]
    client.post(f"/api/v1/skus/{a['id']}/prices", json={"price": "12.5"}, headers=admin)
    b = client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG8").model_dump()},
                    headers=admin).json()["sku"]

    s = client.get("/api/v1/skus/stats", headers=admin).json()
    assert s["active"] == 1, s          # 仅 A 有现价
    assert s["pending_price"] == 1, s   # B 待录价
    assert s["new_this_week"] == 2, s   # 刚建的两个
    assert s["stale_30d"] == 0, s       # 今日录价，未满 30 天

    # 品类计数 = 该品类在售 SKU（含待录价）= 2
    types = client.get("/api/v1/template/node-types",
                       params={"with_counts": True}, headers=admin).json()
    ext = next(t for t in types if t["id"] == template["ext"].id)
    assert ext["sku_count"] == 2, ext
    # 不带 with_counts 时不计算
    plain = client.get("/api/v1/template/node-types", headers=admin).json()
    assert all(t["sku_count"] is None for t in plain)

    # 作废 A 后：active 归零（A 退出在售），pending 不变
    client.post(f"/api/v1/skus/{a['id']}/retire", headers=admin)
    s2 = client.get("/api/v1/skus/stats", headers=admin).json()
    assert s2["active"] == 0 and s2["pending_price"] == 1, s2
    types2 = client.get("/api/v1/template/node-types",
                        params={"with_counts": True}, headers=admin).json()
    assert next(t for t in types2 if t["id"] == template["ext"].id)["sku_count"] == 1


def test_mine_filter(client, template):
    admin = login(client, "admin", "admin@Test2026")
    sales = login(client, "sales", "sales@Test2026")
    # admin 建一个，sales 建一个（不同配置）
    client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG4").model_dump()},
                headers=admin)
    client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG8").model_dump()},
                headers=sales)
    mine_admin = client.get("/api/v1/skus", params={"mine": True}, headers=admin).json()
    mine_sales = client.get("/api/v1/skus", params={"mine": True}, headers=sales).json()
    assert mine_admin["total"] == 1 and mine_sales["total"] == 1
    allin = client.get("/api/v1/skus", headers=admin).json()
    assert allin["total"] == 2


def test_stats_route_not_shadowed(client, template):
    """/skus/stats 不被 /skus/{sku_id} 动态路由捕获（int 转换不会拦截 'stats'）。"""
    admin = login(client, "admin", "admin@Test2026")
    r = client.get("/api/v1/skus/stats", headers=admin)
    assert r.status_code == 200
    assert set(r.json().keys()) == {
        "active", "pending_price", "new_this_week", "stale_30d", "incomplete",
    }


def test_overview(client, template):
    """产品全貌：按可售品类聚合（产品库首页"全貌"视图数据源）。"""
    admin = login(client, "admin", "admin@Test2026")
    a = client.post("/api/v1/skus", json={"config": make_payload(template, charge="KG4").model_dump()},
                    headers=admin).json()["sku"]
    client.post(f"/api/v1/skus/{a['id']}/prices", json={"price": "12.5"}, headers=admin)
    ov = client.get("/api/v1/skus/overview", headers=admin).json()
    ext = next(o for o in ov if o["root_type_id"] == template["ext"].id)
    assert ext["kind"] == "product"
    assert ext["sku_count"] == 1
    assert float(ext["price_min"]) == 12.5 and float(ext["price_max"]) == 12.5
    assert ext["slot_count"] == 2   # 筒体槽 + 阀门槽
    assert ext["attr_count"] == 2   # 充装量 + 工作压力
    assert ext["currency"] == "USD"
