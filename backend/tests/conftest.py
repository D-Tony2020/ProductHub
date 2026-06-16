"""测试基座：独立 producthub_test 库，按 Alembic 迁移建 schema（迁移本身也被测试）。"""
import os

# 必须在导入任何 app 模块之前设定测试库连接
TEST_DB_URL = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub_test"
ADMIN_DB_URL = "postgresql+psycopg://producthub:producthub_dev@127.0.0.1:5440/producthub"
os.environ["PRODUCTHUB_DATABASE_URL"] = TEST_DB_URL
# jwt_secret 现为必填项（无代码默认值）：测试注入一个 ≥32 字节的固定值
os.environ.setdefault("PRODUCTHUB_JWT_SECRET", "test-only-jwt-secret-0123456789abcdefghij")

import pytest
from sqlalchemy import create_engine, select, text

from alembic import command
from alembic.config import Config as AlembicConfig


@pytest.fixture(scope="session", autouse=True)
def test_database():
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'producthub_test' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text("DROP DATABASE IF EXISTS producthub_test"))
        conn.execute(text("CREATE DATABASE producthub_test"))
    admin_engine.dispose()

    cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture()
def db(test_database):
    from app.core.db import SessionLocal, engine

    session = SessionLocal()
    yield session
    # 必须先关会话再 TRUNCATE：残留事务的 ACCESS SHARE 锁会让 TRUNCATE 永久等待
    session.rollback()
    session.close()
    engine.dispose()
    with engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE TABLE audit_log, quote_item, quote, sku_price, sku_attribute_value, "
            "sku_config_node, sku, config_draft, import_batch, purchased_part, supplier, "
            "attribute_option, attribute_def, component_slot, node_type, code_counter, "
            "app_user RESTART IDENTITY CASCADE"
        ))
        conn.commit()


@pytest.fixture()
def template(db):
    """最小灭火器模板：整机(充装量/压力) + 筒体槽(材质) + 阀门槽(阀体材质)，阀门可黑盒。"""
    from app.models import (
        AppUser,
        AttributeDef,
        AttributeOption,
        ComponentSlot,
        NodeType,
        PurchasedPart,
        Supplier,
    )
    from app.core.security import hash_password

    admin = AppUser(username="admin", password_hash=hash_password("admin@Test2026"),
                    display_name="管理员", role="admin", can_set_price=True)
    sales = AppUser(username="sales", password_hash=hash_password("sales@Test2026"),
                    display_name="业务员", role="sales")
    db.add_all([admin, sales])

    ext = NodeType(code="EXT", name="灭火器", kind="product", is_sellable_root=True)
    cyl = NodeType(code="CYL", name="筒体", kind="part")
    valve = NodeType(code="VALVE", name="阀门", kind="part")
    db.add_all([ext, cyl, valve])
    db.flush()

    charge = AttributeDef(node_type_id=ext.id, code="CHARGE", name="充装量", is_filterable=True)
    pressure = AttributeDef(node_type_id=ext.id, code="PRESSURE", name="工作压力")
    material = AttributeDef(node_type_id=cyl.id, code="MATERIAL", name="材质")
    body = AttributeDef(node_type_id=valve.id, code="BODY", name="阀体材质")
    db.add_all([charge, pressure, material, body])
    db.flush()

    options = {}
    for attr, pairs in [
        (charge, [("KG4", "4kg"), ("KG8", "8kg")]),
        (pressure, [("MPA1_2", "1.2MPa"), ("MPA1_4", "1.4MPa")]),
        (material, [("CS", "碳钢"), ("SS", "不锈钢")]),
        (body, [("BRASS", "黄铜"), ("ALU", "铝合金")]),
    ]:
        for code, label in pairs:
            o = AttributeOption(attribute_id=attr.id, code=code, label=label)
            db.add(o)
            options[f"{attr.code}.{code}"] = o
    db.flush()

    slot_cyl = ComponentSlot(parent_type_id=ext.id, child_type_id=cyl.id,
                             code="CYLINDER", name="筒体", is_required=True)
    slot_valve = ComponentSlot(parent_type_id=ext.id, child_type_id=valve.id,
                               code="VALVE", name="阀门", is_required=True)
    db.add_all([slot_cyl, slot_valve])

    supplier = Supplier(code="HX", name="华消")
    db.add(supplier)
    db.flush()
    part = PurchasedPart(code="PP-T-0001", node_type_id=valve.id, supplier_id=supplier.id,
                         name="华消K2阀门", status="active")
    db.add(part)
    db.commit()

    return {
        "admin": admin, "sales": sales, "ext": ext, "cyl": cyl, "valve": valve,
        "charge": charge, "pressure": pressure, "material": material, "body": body,
        "options": options, "slot_cyl": slot_cyl, "slot_valve": slot_valve,
        "supplier": supplier, "part": part,
    }


def make_payload(t, *, charge="KG4", pressure="MPA1_2", material="CS",
                 valve_mode="purchased", valve_body="BRASS",
                 attr_order_reversed=False):
    """构造标准配置：白盒筒体 + 黑盒(或白盒)阀门。"""
    from app.schemas.config import (
        AttributeSelection,
        ConfigNodeIn,
        ConfigPayload,
        SlotSelection,
    )

    o = t["options"]
    root_attrs = [
        AttributeSelection(attribute_id=t["charge"].id, option_id=o[f"CHARGE.{charge}"].id),
        AttributeSelection(attribute_id=t["pressure"].id, option_id=o[f"PRESSURE.{pressure}"].id),
    ]
    if attr_order_reversed:
        root_attrs.reverse()

    cyl_node = ConfigNodeIn(attributes=[
        AttributeSelection(attribute_id=t["material"].id, option_id=o[f"MATERIAL.{material}"].id)
    ])
    if valve_mode == "purchased":
        valve_sel = SlotSelection(slot_id=t["slot_valve"].id, mode="purchased",
                                  purchased_part_id=t["part"].id)
    else:
        valve_sel = SlotSelection(
            slot_id=t["slot_valve"].id, mode="configured",
            child=ConfigNodeIn(attributes=[
                AttributeSelection(attribute_id=t["body"].id,
                                   option_id=o[f"BODY.{valve_body}"].id)
            ]),
        )
    slots = [
        SlotSelection(slot_id=t["slot_cyl"].id, mode="configured", child=cyl_node),
        valve_sel,
    ]
    if attr_order_reversed:
        slots.reverse()
    return ConfigPayload(root_type_id=t["ext"].id,
                         root=ConfigNodeIn(attributes=root_attrs, slots=slots))
