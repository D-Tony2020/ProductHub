"""导入红线：dry-run 无副作用、confirm 入库、同文件幂等、指纹碰撞标记已存在。"""
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from tests.conftest import make_payload


@pytest.fixture()
def client(db, template):
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["root_type_code", "attr:CHARGE", "attr:PRESSURE",
               "attr:CYLINDER.MATERIAL", "part:VALVE", "price", "currency"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_import_two_phase_and_idempotent(client, db, template):
    headers = login(client, "admin", "admin@Test2026")
    content = _xlsx([
        ["EXT", "KG4", "MPA1_2", "CS", "华消|华消K2阀门", "12.5", "USD"],
        ["EXT", "KG8", "MPA1_4", "SS", "新供应商|某新阀门", "15", "USD"],
        ["EXT", "KG4", "BAD_OPT", "CS", "华消|华消K2阀门", "1", "USD"],  # 错误行
    ]).read()

    # dry-run：报告 2 可入库 + 1 错误；不产生任何 SKU
    r = client.post("/api/v1/imports/dry-run",
                    files={"file": ("seed.xlsx", content)}, headers=headers)
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["ok_rows"] == 2 and batch["error_rows"] == 1
    assert client.get("/api/v1/skus", headers=headers).json()["total"] == 0

    # confirm：2 行入库（含自动建档新供应商/新成品件），错误行跳过
    r = client.post(f"/api/v1/imports/{batch['id']}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok_rows"] == 2
    skus = client.get("/api/v1/skus", headers=headers).json()
    assert skus["total"] == 2
    # 价格已带入
    assert any(s["current_prices"] and s["current_prices"][0]["price"] == "12.5000"
               for s in skus["items"])

    # 同文件再次 dry-run：幂等拦截
    r = client.post("/api/v1/imports/dry-run",
                    files={"file": ("seed.xlsx", content)}, headers=headers)
    assert r.status_code == 409

    # 指纹碰撞：手工配置与导入行同款 → 命中既有，不新建
    payload = make_payload(template).model_dump()
    r = client.post("/api/v1/skus", json={"config": payload}, headers=headers)
    assert r.json()["created"] is False
