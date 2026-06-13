"""录价 A 红线：同日改价改为软作废（真 append-only），作废行不进现价、不泄漏进报价。"""
from datetime import date, timedelta

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


def test_same_day_correction_is_soft_supersede(client, template):
    """同日改价：旧行软作废保留（不物删），历史可追溯，现价取新值。"""
    admin = login(client, "admin", "admin@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "9.9"}, headers=admin)
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "10.5"}, headers=admin)

    hist = client.get(f"/api/v1/skus/{sku['id']}/prices", headers=admin).json()
    # append-only：两条都在（旧 9.9 被作废、新 10.5 生效），不再物删
    assert len(hist) == 2, hist
    superseded = [h for h in hist if h["superseded"]]
    active = [h for h in hist if not h["superseded"]]
    assert len(superseded) == 1 and superseded[0]["price"] == "9.9000"
    assert len(active) == 1 and active[0]["price"] == "10.5000"

    # 现价取数收口：只认未作废的 10.5（作废的 9.9 不泄漏）
    detail = client.get(f"/api/v1/skus/{sku['id']}", headers=admin).json()
    assert detail["current_prices"][0]["price"] == "10.5000"


def test_superseded_price_not_in_quote(client, template):
    """作废错价不会被快照进报价单（现价收口两处都过滤）。"""
    admin = login(client, "admin", "admin@Test2026")
    sales = login(client, "sales", "sales@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "1"}, headers=admin)   # 错价
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "88"}, headers=admin)  # 纠正

    q = client.post("/api/v1/quotes", json={"customer_name": "ACME"}, headers=sales).json()
    client.post(f"/api/v1/quotes/{q['id']}/items", json={"sku_id": sku["id"], "qty": 1}, headers=sales)
    quote = client.get(f"/api/v1/quotes/{q['id']}", headers=sales).json()
    # 快照价必须是纠正后的 88，而非作废的 1
    assert quote["items"][0]["snapshot_price"] == "88.0000", quote["items"][0]


def test_cross_day_still_appends(client, template):
    """跨日改价仍是正常追加（旧价 valid_to 截断、新价插入，两条均未作废）。"""
    admin = login(client, "admin", "admin@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=admin).json()["sku"]
    client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "10"}, headers=admin)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "12", "valid_from": tomorrow}, headers=admin)
    assert r.status_code == 201, r.text
    hist = client.get(f"/api/v1/skus/{sku['id']}/prices", headers=admin).json()
    assert len(hist) == 2 and all(not h["superseded"] for h in hist)
