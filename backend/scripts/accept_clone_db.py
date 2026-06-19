# -*- coding: utf-8 -*-
"""验收 Gate2：从 dev 库 producthub 秒级克隆出一次性写场景库 producthub_accept。
服务端 TEMPLATE 拷贝（不走 pg_dump，低内存）。要求 producthub 无其它活动连接。
读场景走 dev（只读）；凡写场景（建SKU/报价/录价/导入）走本克隆，跑完即弃，绝不污染 dev。
用法： .venv\\Scripts\\python.exe scripts\\accept_clone_db.py
"""
from sqlalchemy import create_engine, text

ADMIN = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub_test"
CLONE = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub_accept"

eng = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    for db in ("producthub", "producthub_accept"):
        c.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": db})
    c.execute(text("DROP DATABASE IF EXISTS producthub_accept"))
    c.execute(text("CREATE DATABASE producthub_accept TEMPLATE producthub"))
eng.dispose()
print("CLONE_CREATED producthub_accept <- producthub")

eng2 = create_engine(CLONE)
with eng2.connect() as c:
    sku = c.execute(text("SELECT count(*) FROM sku")).scalar()
    act = c.execute(text("SELECT count(*) FROM sku WHERE status='active'")).scalar()
    sup = c.execute(text("SELECT count(*) FROM supplier")).scalar()
    usr = c.execute(text("SELECT username, role, can_set_price FROM app_user ORDER BY id")).all()
eng2.dispose()
print(f"VERIFY sku={sku} active={act} supplier={sup}")
print("USERS:", [(u[0], u[1], u[2]) for u in usr])
