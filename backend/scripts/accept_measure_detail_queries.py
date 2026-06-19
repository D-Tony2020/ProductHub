# -*- coding: utf-8 -*-
"""测 GET /skus/{id} 详情端点的 SQL 查询次数（N+1 修复 before/after 证据）。
对最深 BOM 的 SKU 与一个浅 BOM 的 SKU 各测一次：若查询数随节点数线性增长=有 N+1，
修复后应≈常数（与节点数无关）。只读，不写。
用法： .venv\\Scripts\\python.exe scripts\\accept_measure_detail_queries.py
"""
import os
os.environ["PRODUCTHUB_DATABASE_URL"] = \
    "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub"

from sqlalchemy import event, func, select  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import make_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppUser, SkuConfigNode  # noqa: E402

db = SessionLocal()
client = TestClient(app)
admin = db.execute(select(AppUser).where(AppUser.username == "admin")).scalar_one()
H = {"Authorization": f"Bearer {make_access_token(admin.id)}"}

cnt = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _count(conn, cursor, statement, params, context, executemany):
    cnt["n"] += 1


def nodes_of(sid):
    return db.execute(select(func.count()).select_from(SkuConfigNode)
                      .where(SkuConfigNode.sku_id == sid)).scalar()


# 最深 BOM 的 SKU
deep = db.execute(
    select(SkuConfigNode.sku_id, func.count().label("n"))
    .group_by(SkuConfigNode.sku_id).order_by(func.count().desc()).limit(1)).first()
deep_id, deep_n = deep[0], deep[1]
# 一个浅 BOM 的 SKU（节点最少，>=1）
shallow = db.execute(
    select(SkuConfigNode.sku_id, func.count().label("n"))
    .group_by(SkuConfigNode.sku_id).order_by(func.count().asc()).limit(1)).first()
shallow_id, shallow_n = shallow[0], shallow[1]

for sid, n in ((shallow_id, shallow_n), (deep_id, deep_n)):
    cnt["n"] = 0
    r = client.get(f"/api/v1/skus/{sid}", headers=H)
    assert r.status_code == 200, (sid, r.status_code, r.text[:160])
    print(f"SKU {sid}: 节点数={n}  详情查询数={cnt['n']}")

db.close()
