"""开发用：打印当前产品体系树，便于核对建模结果。"""
from app.core.db import SessionLocal
from app.models import AttributeDef, AttributeOption, ComponentSlot, NodeType


def main() -> None:
    db = SessionLocal()
    try:
        products = db.query(NodeType).filter_by(kind="product").order_by(
            NodeType.display_order).all()
        sellable_parts = db.query(NodeType).filter_by(kind="part", is_sellable_root=True).all()
        print("=== 可售整机品类 ===")
        for p in products:
            charges = db.query(AttributeOption).join(AttributeDef).filter(
                AttributeDef.node_type_id == p.id, AttributeDef.code.like("%CHONG%")
            ).all()
            ch = "/".join(o.label for o in charges) or "—"
            slots = db.query(ComponentSlot).filter_by(parent_type_id=p.id).order_by(
                ComponentSlot.display_order).all()
            slot_str = "、".join(
                f"{s.name}[{db.get(NodeType, s.child_type_id).name}{'*必配' if s.is_required else ''}]"
                for s in slots
            )
            print(f"  {p.name}（充装量 {ch}）: {slot_str or '（占位，未展开）'}")
        print("\n=== 可售单件（空瓶等）===")
        for p in sellable_parts:
            print(f"  {p.name}")
        print("\n=== 装配体（含子部件槽）===")
        for a in db.query(NodeType).filter_by(kind="part").order_by(NodeType.display_order).all():
            slots = db.query(ComponentSlot).filter_by(parent_type_id=a.id).all()
            if slots:
                print(f"  {a.name}: " + "、".join(
                    f"{s.name}[{db.get(NodeType, s.child_type_id).name}]" for s in slots))
    finally:
        db.close()


if __name__ == "__main__":
    main()
