# -*- coding: utf-8 -*-
"""按产品图谱重建「CO2喷管总成」：型号三选一（喷头型 / 软管+喷头型 / 弯管+喷头型）。

图谱：
  喷管总成 → 型号
    ├ 喷头型      ：喷头.材质 {铜, PA, ABS}
    ├ 软管+喷头型 ：软管材质 {PVC}，喷头材质 {PVC}
    └ 弯管+喷头型 ：弯管材质 {碳钢}，喷头材质 {PVC}

幂等可重跑；旧的并列槽软停用（不删，历史可溯）。干粉喷管总成不动（待老板确认其结构）。
"""
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AttributeDef, AttributeOption, ComponentSlot, NodeType
from app.services.slugs import unique_code


def get_or_create_type(db, name, kind="part"):
    obj = db.execute(select(NodeType).where(NodeType.name == name)).scalar_one_or_none()
    if obj is None:
        obj = NodeType(code=unique_code(db, NodeType, name), name=name, kind=kind)
        db.add(obj)
        db.flush()
        print(f"  + 节点类型 {name} ({obj.code})")
    return obj


def ensure_attr(db, nt, name, options):
    attr = db.execute(select(AttributeDef).where(
        AttributeDef.node_type_id == nt.id, AttributeDef.name == name
    )).scalar_one_or_none()
    if attr is None:
        attr = AttributeDef(
            node_type_id=nt.id, name=name,
            code=unique_code(db, AttributeDef, name, AttributeDef.node_type_id == nt.id),
        )
        db.add(attr)
        db.flush()
        print(f"  + 属性 {nt.name}.{name}")
    for label in options:
        opt = db.execute(select(AttributeOption).where(
            AttributeOption.attribute_id == attr.id, AttributeOption.label == label
        )).scalar_one_or_none()
        if opt is None:
            db.add(AttributeOption(
                attribute_id=attr.id, label=label,
                code=unique_code(db, AttributeOption, label,
                                 AttributeOption.attribute_id == attr.id),
            ))
            print(f"    + 选项 {label}")
    db.flush()
    return attr


def ensure_variant_slot(db, parent, child, name, group):
    slot = db.execute(select(ComponentSlot).where(
        ComponentSlot.parent_type_id == parent.id, ComponentSlot.name == name
    )).scalar_one_or_none()
    if slot is None:
        slot = ComponentSlot(
            parent_type_id=parent.id, child_type_id=child.id, name=name,
            code=unique_code(db, ComponentSlot, name,
                             ComponentSlot.parent_type_id == parent.id),
            variant_group=group, is_required=True, allow_blackbox=True,
        )
        db.add(slot)
        print(f"  + 变体槽 {parent.name} :: {group}/{name} → {child.name}")
    else:
        slot.variant_group = group
        slot.is_active = True
    db.flush()
    return slot


def main() -> None:
    db = SessionLocal()
    try:
        co2_spray = db.execute(
            select(NodeType).where(NodeType.name == "CO2喷管总成")
        ).scalar_one()

        # 1) 旧并列槽软停用（喷管/软管/弯管、喷头）
        for slot in db.execute(select(ComponentSlot).where(
            ComponentSlot.parent_type_id == co2_spray.id,
            ComponentSlot.variant_group.is_(None),
        )).scalars():
            if slot.is_active:
                slot.is_active = False
                print(f"  - 停用旧槽 {slot.name}")

        # 2) 变体子类型与属性
        head = get_or_create_type(db, "喷头")  # 已存在则复用
        ensure_attr(db, head, "材质", ["铜", "PA", "ABS"])

        hose_head = get_or_create_type(db, "软管+喷头型总成")
        ensure_attr(db, hose_head, "软管材质", ["PVC"])
        ensure_attr(db, hose_head, "喷头材质", ["PVC"])

        bend_head = get_or_create_type(db, "弯管+喷头型总成")
        ensure_attr(db, bend_head, "弯管材质", ["碳钢"])
        ensure_attr(db, bend_head, "喷头材质", ["PVC"])

        # 3) 「型号」三选一变体槽
        ensure_variant_slot(db, co2_spray, head, "喷头型", "型号")
        ensure_variant_slot(db, co2_spray, hose_head, "软管+喷头型", "型号")
        ensure_variant_slot(db, co2_spray, bend_head, "弯管+喷头型", "型号")

        db.commit()
        print("CO2喷管总成重建完成（干粉喷管总成未动，待确认）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
