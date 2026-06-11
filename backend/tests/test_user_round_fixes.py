"""用户测试发现问题的回归：草稿 500、同日改价纠错、超大价格 500。"""
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


def test_draft_create_returns_200_not_500(client, template):
    """R18 回归：DraftOut.updated_at 类型错误导致建草稿 500。"""
    headers = login(client, "sales", "sales@Test2026")
    r = client.post("/api/v1/config-drafts",
                    json={"root_type_id": template["ext"].id, "title": "草稿", "payload": {"x": 1}},
                    headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["updated_at"] is not None
    r = client.get("/api/v1/config-drafts", headers=headers)
    assert r.status_code == 200 and len(r.json()) == 1


def test_same_day_price_correction(client, template):
    """R9 回归：同日录错价必须能当天纠正；纠错保留审计、价格史不留脏记录。"""
    headers = login(client, "admin", "admin@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=headers).json()["sku"]
    assert client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "9.9"},
                       headers=headers).status_code == 201
    # 同日纠错
    r = client.post(f"/api/v1/skus/{sku['id']}/prices", json={"price": "10.5"}, headers=headers)
    assert r.status_code == 201, r.text
    hist = client.get(f"/api/v1/skus/{sku['id']}/prices", headers=headers).json()
    assert len(hist) == 1 and hist[0]["price"] == "10.5000"  # 错误记录被顶替，不留脏行
    # 回溯覆盖仍被拒
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "8", "valid_from": "2020-01-01"}, headers=headers)
    assert r.status_code == 409


def test_huge_price_rejected_422(client, template):
    """R17 回归：超出 Numeric(14,4) 容量的价格在入参层拦截，而非数据库 500。"""
    headers = login(client, "admin", "admin@Test2026")
    sku = client.post("/api/v1/skus", json={"config": make_payload(template).model_dump()},
                      headers=headers).json()["sku"]
    r = client.post(f"/api/v1/skus/{sku['id']}/prices",
                    json={"price": "999999999999.9999"}, headers=headers)
    assert r.status_code == 422
