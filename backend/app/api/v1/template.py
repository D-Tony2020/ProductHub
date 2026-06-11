"""模板管理（admin）：品类/部件类型、部件槽、属性、选项。

纪律（在 API 层强制）：code 不可变（Update schema 无该字段）；删除一律软停用；
被引用对象 FK RESTRICT 兜底；槽图 DAG 防环；可选属性禁建"无"语义选项。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user, require_admin
from app.models import AppUser, AttributeDef, AttributeOption, ComponentSlot, NodeType
from app.schemas.template import (
    AttributeIn,
    AttributeOut,
    AttributeUpdate,
    AttributeWithOptionsOut,
    NodeTypeDetailOut,
    NodeTypeIn,
    NodeTypeOut,
    NodeTypeUpdate,
    OptionIn,
    OptionOut,
    OptionUpdate,
    SlotIn,
    SlotOut,
    SlotUpdate,
)
from app.services.slugs import unique_code
from app.services.template_service import (
    get_or_404,
    option_reference_count,
    option_violates_none_rule,
    would_create_cycle,
)

router = APIRouter(prefix="/template", tags=["template"])


def _apply_updates(obj, body) -> dict:
    """套用非 None 字段，返回变更前快照（审计用）。"""
    before = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        before[field] = getattr(obj, field)
        setattr(obj, field, value)
    return before


# ---------- 节点类型 ----------

@router.get("/node-types", response_model=list[NodeTypeOut])
def list_node_types(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: AppUser = Depends(get_current_user),
):
    stmt = select(NodeType).order_by(NodeType.display_order, NodeType.id)
    if not include_inactive:
        stmt = stmt.where(NodeType.is_active.is_(True))
    return db.execute(stmt).scalars().all()


@router.get("/node-types/{type_id}", response_model=NodeTypeDetailOut)
def get_node_type(
    type_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    nt = get_or_404(db, NodeType, type_id)
    attrs = []
    for a in nt.attributes:
        item = AttributeWithOptionsOut.model_validate(a)
        item.options = [OptionOut.model_validate(o) for o in a.options]
        attrs.append(item)
    return NodeTypeDetailOut(
        **NodeTypeOut.model_validate(nt).model_dump(),
        attributes=attrs,
        slots=[SlotOut.model_validate(s) for s in nt.slots],
    )


@router.post("/node-types", response_model=NodeTypeOut, status_code=201)
def create_node_type(
    body: NodeTypeIn, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    data = body.model_dump()
    data["code"] = data["code"] or unique_code(db, NodeType, body.name)
    nt = NodeType(**data)
    db.add(nt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"节点类型 code 已存在：{data['code']}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="node_type",
                entity_id=nt.id, after=data)
    db.commit()
    return nt


class ReorderIn(BaseModel):
    ids: list[int]


@router.put("/node-types/reorder", response_model=list[NodeTypeOut])
def reorder_node_types(
    body: ReorderIn, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    """按传入 id 顺序重排 display_order（拖拽排序）。未包含的类型排在其后，相对顺序不变。"""
    order = {tid: idx for idx, tid in enumerate(body.ids)}
    all_types = db.execute(
        select(NodeType).order_by(NodeType.display_order, NodeType.id)
    ).scalars().all()
    tail = len(order)
    for nt in all_types:
        if nt.id in order:
            nt.display_order = order[nt.id]
        else:
            nt.display_order = tail
            tail += 1
    write_audit(db, actor_id=admin.id, action="reorder", entity_type="node_type",
                entity_id="*", after={"ids": body.ids})
    db.commit()
    return db.execute(
        select(NodeType).order_by(NodeType.display_order, NodeType.id)
    ).scalars().all()


@router.patch("/node-types/{type_id}", response_model=NodeTypeOut)
def update_node_type(
    type_id: int, body: NodeTypeUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    nt = get_or_404(db, NodeType, type_id)
    before = _apply_updates(nt, body)
    write_audit(db, actor_id=admin.id, action="update", entity_type="node_type",
                entity_id=nt.id, before=before, after=body.model_dump(exclude_unset=True))
    db.commit()
    return nt


# ---------- 部件槽 ----------

@router.post("/node-types/{type_id}/slots", response_model=SlotOut, status_code=201)
def create_slot(
    type_id: int, body: SlotIn,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    parent = get_or_404(db, NodeType, type_id)
    child = get_or_404(db, NodeType, body.child_type_id)
    if not child.is_active:
        raise HTTPException(409, f"部件类型「{child.name}」已停用，不可新建槽")
    if would_create_cycle(db, parent.id, child.id):
        raise HTTPException(409, f"在「{parent.name}」下挂「{child.name}」会形成循环结构（槽图必须为 DAG）")
    data = body.model_dump()
    data["code"] = data["code"] or unique_code(
        db, ComponentSlot, body.name, ComponentSlot.parent_type_id == parent.id
    )
    slot = ComponentSlot(parent_type_id=parent.id, **data)
    db.add(slot)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"该节点类型下槽 code 已存在：{data['code']}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="component_slot",
                entity_id=slot.id, after=body.model_dump())
    db.commit()
    return slot


@router.patch("/slots/{slot_id}", response_model=SlotOut)
def update_slot(
    slot_id: int, body: SlotUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    slot = get_or_404(db, ComponentSlot, slot_id)
    before = _apply_updates(slot, body)
    write_audit(db, actor_id=admin.id, action="update", entity_type="component_slot",
                entity_id=slot.id, before=before, after=body.model_dump(exclude_unset=True))
    db.commit()
    return slot


# ---------- 属性 ----------

@router.post("/node-types/{type_id}/attributes", response_model=AttributeOut, status_code=201)
def create_attribute(
    type_id: int, body: AttributeIn,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    nt = get_or_404(db, NodeType, type_id)
    data = body.model_dump()
    data["code"] = data["code"] or unique_code(
        db, AttributeDef, body.name, AttributeDef.node_type_id == nt.id
    )
    attr = AttributeDef(node_type_id=nt.id, **data)
    db.add(attr)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"该节点类型下属性 code 已存在：{data['code']}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="attribute_def",
                entity_id=attr.id, after=body.model_dump())
    db.commit()
    return attr


@router.patch("/attributes/{attr_id}", response_model=AttributeOut)
def update_attribute(
    attr_id: int, body: AttributeUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    attr = get_or_404(db, AttributeDef, attr_id)
    before = _apply_updates(attr, body)
    write_audit(db, actor_id=admin.id, action="update", entity_type="attribute_def",
                entity_id=attr.id, before=before, after=body.model_dump(exclude_unset=True))
    db.commit()
    return attr


# ---------- 选项 ----------

@router.get("/attributes/{attr_id}/options", response_model=list[OptionOut])
def list_options(
    attr_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    get_or_404(db, AttributeDef, attr_id)
    options = db.execute(
        select(AttributeOption)
        .where(AttributeOption.attribute_id == attr_id)
        .order_by(AttributeOption.display_order, AttributeOption.id)
    ).scalars().all()
    out = []
    for o in options:
        item = OptionOut.model_validate(o)
        item.reference_count = option_reference_count(db, o.id)
        out.append(item)
    return out


@router.post("/attributes/{attr_id}/options", response_model=OptionOut, status_code=201)
def create_option(
    attr_id: int, body: OptionIn,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    attr = get_or_404(db, AttributeDef, attr_id)
    if option_violates_none_rule(attr, body.code, body.label):
        raise HTTPException(
            409,
            f"可选属性「{attr.name}」禁止创建“无/不带”语义的选项："
            "“未选”与“选了无”会产生两个业务等价但指纹不同的配置。"
            "请把该属性改为必选，或将“带不带”建模为可选部件槽。",
        )
    data = body.model_dump()
    # 选项 code 由显示名转写（"4kg"→"4KG"、"碳钢"→"TAN_GANG"）
    data["code"] = data["code"] or unique_code(
        db, AttributeOption, body.label, AttributeOption.attribute_id == attr.id
    )
    option = AttributeOption(attribute_id=attr.id, **data)
    db.add(option)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"该属性下选项 code 已存在：{data['code']}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="attribute_option",
                entity_id=option.id, after=body.model_dump(mode="json"))
    db.commit()
    return option


@router.patch("/options/{option_id}", response_model=OptionOut)
def update_option(
    option_id: int, body: OptionUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    option = get_or_404(db, AttributeOption, option_id)
    before = _apply_updates(option, body)
    write_audit(db, actor_id=admin.id, action="update", entity_type="attribute_option",
                entity_id=option.id, before=before,
                after=body.model_dump(exclude_unset=True, mode="json"))
    db.commit()
    out = OptionOut.model_validate(option)
    out.reference_count = option_reference_count(db, option.id)
    return out
