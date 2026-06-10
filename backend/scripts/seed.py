"""种子数据：管理员账号 + 灭火器示例模板（幂等，可重复执行）。

正式模板划分须与客户工作坊共建确认（M1），本脚本提供演示与测试基础。
"""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    AppUser,
    AttributeDef,
    AttributeOption,
    ComponentSlot,
    NodeType,
    PurchasedPart,
    Supplier,
)
from app.services.codes import next_code


def get_or_create(db, model, defaults=None, **keys):
    obj = db.execute(select(model).filter_by(**keys)).scalar_one_or_none()
    if obj is None:
        obj = model(**keys, **(defaults or {}))
        db.add(obj)
        db.flush()
    return obj


def main() -> None:
    db = SessionLocal()
    try:
        # ---- 账号 ----
        get_or_create(
            db, AppUser, username="admin",
            defaults=dict(password_hash=hash_password("admin@ProductHub2026"),
                          display_name="管理员", role="admin", can_set_price=True),
        )
        get_or_create(
            db, AppUser, username="sales01",
            defaults=dict(password_hash=hash_password("sales@ProductHub2026"),
                          display_name="业务员小王", role="sales"),
        )

        # ---- 节点类型 ----
        ext = get_or_create(db, NodeType, code="EXT_DP_PORTABLE",
                            defaults=dict(name="手提式干粉灭火器", kind="product",
                                          is_sellable_root=True, display_order=1))
        cylinder = get_or_create(db, NodeType, code="CYLINDER",
                                 defaults=dict(name="筒体", kind="part", display_order=10))
        valve = get_or_create(db, NodeType, code="VALVE",
                              defaults=dict(name="阀门", kind="part", display_order=11))
        hose = get_or_create(db, NodeType, code="HOSE",
                             defaults=dict(name="喷管", kind="part", display_order=12))
        gauge = get_or_create(db, NodeType, code="GAUGE",
                              defaults=dict(name="压力表", kind="part", display_order=13))

        def attr(nt, code, name, options, required=True, filterable=False, unit=None):
            a = get_or_create(db, AttributeDef, node_type_id=nt.id, code=code,
                              defaults=dict(name=name, is_required=required,
                                            is_filterable=filterable, unit=unit))
            for i, (ocode, label) in enumerate(options):
                get_or_create(db, AttributeOption, attribute_id=a.id, code=ocode,
                              defaults=dict(label=label, display_order=i))
            return a

        # 整机属性
        attr(ext, "CHARGE_KG", "充装量",
             [("KG1", "1kg"), ("KG2", "2kg"), ("KG4", "4kg"), ("KG8", "8kg")],
             filterable=True, unit="kg")
        attr(ext, "WORK_PRESSURE", "工作压力",
             [("MPA1_2", "1.2MPa"), ("MPA1_4", "1.4MPa")], filterable=True, unit="MPa")
        attr(ext, "AGENT_TYPE", "干粉类型", [("ABC", "ABC干粉"), ("BC", "BC干粉")],
             filterable=True)

        # 部件属性
        attr(cylinder, "MATERIAL", "筒体材质", [("CS", "碳钢"), ("SS", "不锈钢")])
        attr(cylinder, "WALL_MM", "壁厚",
             [("MM1_2", "1.2mm"), ("MM1_5", "1.5mm"), ("MM2_0", "2.0mm")], unit="mm")
        attr(valve, "BODY_MATERIAL", "阀体材质", [("BRASS", "黄铜"), ("ALU", "铝合金")])
        attr(valve, "VALVE_TYPE", "阀门形式", [("SQUEEZE", "压把式"), ("WHEEL", "手轮式")])
        attr(hose, "LENGTH_MM", "喷管长度", [("L400", "400mm"), ("L500", "500mm")], unit="mm")
        attr(gauge, "RANGE", "量程", [("R2_5", "0-2.5MPa")])

        # 部件槽
        def slot(parent, child, code, name, order, required=True, blackbox=True):
            return get_or_create(db, ComponentSlot, parent_type_id=parent.id, code=code,
                                 defaults=dict(child_type_id=child.id, name=name,
                                               display_order=order, is_required=required,
                                               allow_blackbox=blackbox))

        slot(ext, cylinder, "CYLINDER", "筒体", 1)
        slot(ext, valve, "VALVE", "阀门", 2)
        slot(ext, hose, "HOSE", "喷管", 3)
        slot(ext, gauge, "GAUGE", "压力表", 4)

        # 成品采购件示例
        huaxiao = get_or_create(db, Supplier, code="HUAXIAO",
                                defaults=dict(name="华消阀门"))
        existing_part = db.execute(
            select(PurchasedPart).where(
                PurchasedPart.supplier_id == huaxiao.id,
                PurchasedPart.node_type_id == valve.id,
                PurchasedPart.name == "华消 K2 阀门总成",
            )
        ).scalar_one_or_none()
        if existing_part is None:
            db.add(PurchasedPart(code=next_code(db, "PP"), node_type_id=valve.id,
                                 supplier_id=huaxiao.id, name="华消 K2 阀门总成",
                                 status="active"))

        db.commit()
        print("种子数据就绪：admin / sales01 账号、手提式干粉灭火器模板、华消成品阀门示例")
        print("首次登录后请立即修改默认密码！")
    finally:
        db.close()


if __name__ == "__main__":
    main()
