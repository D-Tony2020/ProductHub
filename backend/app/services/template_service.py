"""模板（定义层）服务：DAG 防环、可选属性"无"选项禁令、引用计数。"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AttributeDef,
    AttributeOption,
    ComponentSlot,
    NodeType,
    SkuAttributeValue,
    SkuConfigNode,
)

# 可选属性禁止出现"无/不带"语义选项：否则"未选"与"选了无"业务等价但指纹不同
_NONE_LIKE_CODES = {"NONE", "NA", "N_A", "WITHOUT", "NO"}
_NONE_LIKE_LABELS = {"无", "不带", "没有", "n/a", "none", "without"}


def would_create_cycle(db: Session, parent_type_id: int, child_type_id: int) -> bool:
    """在 parent 下挂 child 槽是否成环：从 child 沿槽图 BFS，能走回 parent 即环。"""
    if parent_type_id == child_type_id:
        return True
    seen: set[int] = set()
    frontier = [child_type_id]
    while frontier:
        current = frontier.pop()
        if current == parent_type_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        rows = db.execute(
            select(ComponentSlot.child_type_id).where(
                ComponentSlot.parent_type_id == current
            )
        ).scalars()
        frontier.extend(rows)
    return False


def option_violates_none_rule(attribute: AttributeDef, code: str, label: str) -> bool:
    if attribute.is_required:
        return False
    return code.upper() in _NONE_LIKE_CODES or label.strip().lower() in _NONE_LIKE_LABELS


def option_reference_count(db: Session, option_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(SkuAttributeValue)
        .where(SkuAttributeValue.option_id == option_id)
    ).scalar_one()


def slot_reference_count(db: Session, slot_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(SkuConfigNode)
        .where(SkuConfigNode.slot_id == slot_id)
    ).scalar_one()


def node_type_reference_count(db: Session, node_type_id: int) -> int:
    return db.execute(
        select(func.count())
        .select_from(SkuConfigNode)
        .where(SkuConfigNode.node_type_id == node_type_id)
    ).scalar_one()


def get_or_404(db: Session, model, obj_id: int):
    from fastapi import HTTPException

    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__tablename__} {obj_id} 不存在")
    return obj
