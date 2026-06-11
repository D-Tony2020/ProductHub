"""北京合胜灭火器产品体系构建（基于《产品品类图谱（初稿）》）。

运行即【清空全部产品业务数据】（保留 app_user 账号与 audit_log 历史），
再按本文件的数据定义重建节点类型 / 属性 / 选项 / 部件槽。可重复执行（幂等）。

建模要点（与产品负责人分析一致）：
- 三层：整机品类(product) → 装配体(part) → 基础零件(part)；基础零件全局共享。
- 阀门只含阀组内部零件；压力表 / 虹吸管 / 喷管总成与阀门【并列】挂在整机层（按客户确认）。
- 筒体设为可售根 → "空瓶"即单卖筒体，无冗余。
- 所有零部件槽 allow_blackbox=True：任何部件均可整件外购（贸易公司核心诉求）。
- 尺寸 / 配比类暂无真实档位：建为必选属性 + 一个"通用规格"占位选项，
  后续在模板页加真实档位并停用占位（随时可改，不破坏底层）。
- 充装量放整机层且可筛选（客户询盘第一关键词）；筒体容量保留供空瓶单卖。

执行：在 backend 目录运行  python -m scripts.build_catalog
"""
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models import (
    AttributeDef,
    AttributeOption,
    ComponentSlot,
    NodeType,
)
from app.services.slugs import unique_code

PLACEHOLDER = "通用规格"  # 尺寸/配比类占位档位

# 清空顺序：先子后父；保留 app_user 与 audit_log
_WIPE = (
    "quote_item, quote, sku_price, sku_attribute_value, sku_config_node, sku, "
    "config_draft, import_batch, purchased_part, supplier, attribute_option, "
    "attribute_def, component_slot, node_type, code_counter"
)


def wipe(db) -> None:
    db.execute(text(f"TRUNCATE TABLE {_WIPE} RESTART IDENTITY CASCADE"))
    db.commit()


# ---------------------------------------------------------------------------
# 数据定义
# 属性写法：(名称, [选项label...], 必选?, 可筛选?)  选项为 None 表示尺寸占位
# ---------------------------------------------------------------------------
SZ = None  # 尺寸/配比占位标记

# 基础零件（全局共享）：名称 -> 属性列表
BASE_PARTS: dict[str, list] = {
    "阀体": [("材质", ["铜", "不锈钢", "铝"], True, False),
            ("表面处理", ["钝化", "镀铬", "镀镍"], True, False),
            ("尺寸", SZ, True, False)],
    "把手": [("材质", ["碳钢", "不锈钢"], True, False),
            ("颜色", ["红", "绿"], True, False)],
    "顶杆": [("材质", ["铜", "不锈钢"], True, False), ("尺寸", SZ, True, False)],
    "插销": [("材质", ["铜", "不锈钢", "碳钢"], True, False), ("尺寸", SZ, True, False)],
    "弹簧": [("材质", ["不锈钢", "碳钢"], True, False), ("尺寸", SZ, True, False)],
    "O型圈": [("材质", ["丁晴胶", "EPDM"], True, False), ("尺寸", SZ, True, False)],
    "吸管座": [("材质", ["铜", "PA", "ABS"], True, False), ("尺寸", SZ, True, False)],
    "铆钉": [("材质", ["不锈钢", "碳钢"], True, False), ("尺寸", SZ, True, False)],
    "链条": [("材质", ["橡胶", "PA"], True, False), ("颜色", ["红", "黑"], True, False)],
    "喷头": [("材质", ["铜", "PA", "ABS"], True, False)],
    "保险帽": [("材质", ["铜"], True, False)],
    "保险片": [("材质", ["不锈钢"], True, False)],
    "垫片": [("材质", ["紫铜", "PA"], True, False)],
    "喷管": [("材质", ["PVC", "碳钢", "铝"], True, False), ("尺寸", SZ, True, False)],
    # 整机直接零部件
    "压力表": [("型号", ["弹簧管", "膜片", "仿膜片"], True, False),
             ("表盘尺寸", ["25mm", "30mm", "37mm"], True, False),
             ("螺纹", ["M10x1", "M10x1x12.5", "NPT 1/8"], True, False)],
    "虹吸管": [("材质", ["PVC", "铝-6061"], True, False),
             ("长度", ["20cm", "30cm"], True, False)],
    "干粉药剂": [("颜色", ["黄", "白"], True, False), ("成分配比", SZ, True, False)],
    "CO2药剂": [],  # 图未展开，建类型占位
}

# 装配体：名称 -> (属性列表, [ (子部件名, 槽名, 必配?) ... ])
ASSEMBLIES: dict[str, tuple] = {
    "保险装置": ([], [("保险帽", "保险帽", True), ("保险片", "保险片", False),
                  ("垫片", "垫片", False)]),
    "干粉阀门": ([], [("阀体", "阀体", True), ("把手", "把手", False),
                  ("顶杆", "顶杆", False), ("插销", "插销", False),
                  ("弹簧", "弹簧", False), ("O型圈", "O型圈", False),
                  ("吸管座", "吸管座", False), ("铆钉", "铆钉", False),
                  ("链条", "链条", False)]),
    "CO2阀门": ([], [("阀体", "阀体", True), ("把手", "把手", False),
                   ("顶杆", "顶杆", False), ("插销", "插销", False),
                   ("弹簧", "弹簧", False), ("吸管座", "吸管座", False),
                   ("铆钉", "铆钉", False), ("链条", "链条", False),
                   ("保险装置", "保险装置", False)]),
    "干粉喷管总成": ([], [("喷头", "喷头", True), ("喷管", "喷管", False)]),
    "CO2喷管总成": ([], [("喷头", "喷头", True), ("喷管", "喷管/软管/弯管", False)]),
}

# 筒体（可售根 = 空瓶单卖）
CYLINDERS: dict[str, list] = {
    "干粉筒体": [("瓶底", ["U型底", "丁字底"], True, False),
              ("内喷涂", ["有", "无"], True, False),
              ("材质", ["不锈钢", "碳钢"], True, False),
              ("容量", ["1kg", "2kg", "3kg", "4kg"], True, True)],
    "CO2筒体": [("材质", ["铝合金", "碳钢"], True, False),
               ("容量", ["2kg", "3kg", "5kg"], True, True)],
}

# 整机品类：名称 -> (充装量选项, [ (子部件名, 槽名, 必配?) ... ])
PRODUCTS: dict[str, tuple] = {
    "干粉灭火器": (["1kg", "2kg", "3kg", "4kg"],
              [("干粉筒体", "筒体", True), ("干粉阀门", "阀门", True),
               ("压力表", "压力表", False), ("虹吸管", "虹吸管", False),
               ("干粉喷管总成", "喷管总成", False), ("干粉药剂", "干粉药剂", False)]),
    "CO2灭火器": (["2kg", "3kg", "5kg"],
              [("CO2筒体", "筒体", True), ("CO2阀门", "阀门", True),
               ("虹吸管", "虹吸管", False), ("CO2喷管总成", "喷管总成", False),
               ("CO2药剂", "药剂", False)]),  # CO2 无压力表
}

# 未展开品类：建占位（可售根），后续工作坊补
PLACEHOLDER_PRODUCTS = ["水基灭火器", "推车灭火器", "软管卷盘"]


def build(db) -> None:
    reg: dict[str, NodeType] = {}

    def ensure_type(name: str, kind: str, sellable: bool, order: int) -> NodeType:
        if name in reg:
            return reg[name]
        nt = NodeType(code=unique_code(db, NodeType, name), name=name, kind=kind,
                      is_sellable_root=sellable, display_order=order, is_active=True)
        db.add(nt)
        db.flush()
        reg[name] = nt
        return nt

    def add_attrs(nt: NodeType, attrs: list) -> None:
        for order, spec in enumerate(attrs):
            name, opts, required, filterable = spec
            a = AttributeDef(
                node_type_id=nt.id, code=unique_code(db, AttributeDef, name,
                                                     AttributeDef.node_type_id == nt.id),
                name=name, value_kind="enum", is_required=required,
                is_filterable=filterable, display_order=order,
            )
            db.add(a)
            db.flush()
            labels = opts if opts is not None else [PLACEHOLDER]  # 尺寸占位
            for i, label in enumerate(labels):
                db.add(AttributeOption(
                    attribute_id=a.id,
                    code=unique_code(db, AttributeOption, label,
                                     AttributeOption.attribute_id == a.id),
                    label=label, display_order=i,
                ))
            db.flush()

    def add_slots(parent: NodeType, slots: list) -> None:
        for order, (child_name, slot_name, required) in enumerate(slots):
            child = reg[child_name]
            db.add(ComponentSlot(
                parent_type_id=parent.id, child_type_id=child.id,
                code=unique_code(db, ComponentSlot, slot_name,
                                 ComponentSlot.parent_type_id == parent.id),
                name=slot_name, is_required=required, allow_blackbox=True,
                display_order=order,
            ))
        db.flush()

    order = 0
    # 1. 基础零件（先建，供装配体引用）
    for name, attrs in BASE_PARTS.items():
        add_attrs(ensure_type(name, "part", False, order), attrs)
        order += 1
    # 2. 装配体（含保险装置，需在阀门前建好）
    for name, (attrs, slots) in ASSEMBLIES.items():
        nt = ensure_type(name, "part", True, order)  # 装配体也可单卖
        add_attrs(nt, attrs)
        order += 1
    for name, (_, slots) in ASSEMBLIES.items():
        add_slots(reg[name], slots)
    # 3. 筒体（可售根 = 空瓶）
    for name, attrs in CYLINDERS.items():
        add_attrs(ensure_type(name, "part", True, order), attrs)
        order += 1
    # 4. 整机品类
    for name, (charges, slots) in PRODUCTS.items():
        nt = ensure_type(name, "product", True, order)
        add_attrs(nt, [("充装量", charges, True, True)])
        add_slots(nt, slots)
        order += 1
    # 5. 占位品类
    for name in PLACEHOLDER_PRODUCTS:
        ensure_type(name, "product", True, order)
        order += 1

    db.commit()
    return reg


def main() -> None:
    db = SessionLocal()
    try:
        wipe(db)
        reg = build(db)
        types = db.query(NodeType).count()
        attrs = db.query(AttributeDef).count()
        opts = db.query(AttributeOption).count()
        slots = db.query(ComponentSlot).count()
        print(f"产品体系已重建：{types} 个节点类型 / {attrs} 个属性 / {opts} 个选项 / {slots} 个部件槽")
        print("可售整机：干粉灭火器、CO2灭火器（+水基/推车/软管卷盘占位）")
        print("可售单件：干粉筒体、CO2筒体（即空瓶）")
        print(f"尺寸/配比类已用占位档位「{PLACEHOLDER}」顶位，待真实档位在模板页增补")
    finally:
        db.close()


if __name__ == "__main__":
    main()
