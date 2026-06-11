"""模板管理增强：code 自动生成（拼音转写+作用域查重）与节点类型拖拽排序。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client):
    resp = client.post("/api/v1/auth/login",
                       json={"username": "admin", "password": "admin@Test2026"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_auto_code_from_chinese_name(client, template):
    headers = login(client)
    # 节点类型：中文名 → 拼音 code
    r = client.post("/api/v1/template/node-types",
                    json={"name": "顶杆", "kind": "part"}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "DING_GAN"

    # 同名再建 → 查重加序号
    r2 = client.post("/api/v1/template/node-types",
                     json={"name": "顶杆", "kind": "part"}, headers=headers)
    assert r2.json()["code"] == "DING_GAN_2"

    # 属性与选项：选项 code 由显示名转写，数字字母直通
    valve_id = template["valve"].id
    a = client.post(f"/api/v1/template/node-types/{valve_id}/attributes",
                    json={"name": "口径"}, headers=headers).json()
    assert a["code"] == "KOU_JING"
    o = client.post(f"/api/v1/template/attributes/{a['id']}/options",
                    json={"label": "25mm"}, headers=headers).json()
    assert o["code"] == "25MM"

    # 槽：现场新建类型后挂槽，槽 code 同样自动生成
    r = client.post(f"/api/v1/template/node-types/{valve_id}/slots",
                    json={"name": "顶杆", "child_type_id": r.json()["id"]},
                    headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "DING_GAN"

    # 显式 code 仍被接受（导入/种子路径）
    r = client.post("/api/v1/template/node-types",
                    json={"code": "NOZZLE", "name": "喷嘴", "kind": "part"}, headers=headers)
    assert r.json()["code"] == "NOZZLE"


def test_reorder_node_types(client, template):
    headers = login(client)
    before = client.get("/api/v1/template/node-types", headers=headers).json()
    ids = [t["id"] for t in before]
    assert len(ids) >= 3
    new_order = list(reversed(ids))

    r = client.put("/api/v1/template/node-types/reorder",
                   json={"ids": new_order}, headers=headers)
    assert r.status_code == 200, r.text
    after = [t["id"] for t in r.json()]
    assert after == new_order

    # 持久化生效：重新拉取顺序一致
    again = [t["id"] for t in client.get("/api/v1/template/node-types", headers=headers).json()]
    assert again == new_order


def test_reorder_requires_admin(client, template):
    resp = client.post("/api/v1/auth/login",
                       json={"username": "sales", "password": "sales@Test2026"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    r = client.put("/api/v1/template/node-types/reorder", json={"ids": []}, headers=headers)
    assert r.status_code == 403
