"""模板管理（admin）：品类/部件类型、部件槽、属性、选项。

纪律（在 API 层强制）：code 不可变（Update schema 无该字段）；删除一律软停用；
被引用对象 FK RESTRICT 兜底；槽图 DAG 防环；可选属性禁建"无"语义选项。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user, require_admin
from app.models import (
    AppUser,
    AttributeDef,
    AttributeOption,
    ComponentSlot,
    NodeType,
    Sku,
    SkuConfigNode,
)
from app.schemas.template import (
    AttributeIn,
    AttributeOut,
    AttributeUpdate,
    AttributeWithOptionsOut,
    ImpactFamilyCount,
    ImpactPreviewIn,
    ImpactPreviewOut,
    ImpactSample,
    NodeTypeDetailOut,
    NodeTypeIn,
    NodeTypeOut,
    NodeTypeParentsOut,
    NodeTypeUpdate,
    OptionIn,
    OptionOut,
    OptionUpdate,
    ParentRefOut,
    SlotIn,
    SlotOut,
    SlotUpdate,
)
from app.services.health_engine import compute_health
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
    with_counts: bool = False,
    db: Session = Depends(get_db),
    _: AppUser = Depends(get_current_user),
):
    stmt = select(NodeType).order_by(NodeType.display_order, NodeType.id)
    if not include_inactive:
        stmt = stmt.where(NodeType.is_active.is_(True))
    rows = db.execute(stmt).scalars().all()
    out = [NodeTypeOut.model_validate(nt) for nt in rows]
    if with_counts:
        # 每个品类在售 SKU 数（一次分组查询，O(1) 而非 N+1）
        from app.models import Sku

        counts = dict(
            db.execute(
                select(Sku.root_type_id, func.count())
                .where(Sku.status == "active")
                .group_by(Sku.root_type_id)
            ).all()
        )
        # 反向归属计数：每个节点被几个不同上级当部件引用
        pcounts = dict(
            db.execute(
                select(
                    ComponentSlot.child_type_id,
                    func.count(func.distinct(ComponentSlot.parent_type_id)),
                ).group_by(ComponentSlot.child_type_id)
            ).all()
        )
        for item in out:
            item.sku_count = counts.get(item.id, 0)
            item.parent_count = pcounts.get(item.id, 0)
    return out


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
    # 反向归属：本类型被哪些上级当部件引用（多对多，直接上级，去重）
    # 取整实体再 distinct——SELECT DISTINCT 下 ORDER BY 列须在投影内，故不投影裸列
    parent_rows = db.execute(
        select(NodeType)
        .join(ComponentSlot, ComponentSlot.parent_type_id == NodeType.id)
        .where(ComponentSlot.child_type_id == type_id)
        .distinct()
        .order_by(NodeType.display_order)
    ).scalars().all()
    return NodeTypeDetailOut(
        **NodeTypeOut.model_validate(nt).model_dump(),
        attributes=attrs,
        slots=[SlotOut.model_validate(s) for s in nt.slots],
        parents=[ParentRefOut(id=p.id, name=p.name, is_active=p.is_active) for p in parent_rows],
    )


def _upward_ancestor_ids(db: Session, type_id: int) -> set[int]:
    """沿槽图(child←parent)向上 BFS，返回所有祖先节点类型 id（不含自身、防环）。
    一次取全图边、内存遍历，避免逐层查询。"""
    edges = db.execute(
        select(ComponentSlot.child_type_id, ComponentSlot.parent_type_id)
    ).all()
    up: dict[int, set[int]] = {}
    for child, parent in edges:
        up.setdefault(child, set()).add(parent)
    visited: set[int] = set()
    frontier = [type_id]
    while frontier:
        nxt: list[int] = []
        for cur in frontier:
            for p in up.get(cur, ()):
                if p != type_id and p not in visited:
                    visited.add(p)
                    nxt.append(p)
        frontier = nxt
    return visited


@router.get("/node-types/{type_id}/parents", response_model=NodeTypeParentsOut)
def node_type_parents(
    type_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    """档位二·双维上级归属：部件级直接上级 + 品类级 BFS 祖先（结构脉络带的"上级↑"维）。"""
    get_or_404(db, NodeType, type_id)
    direct = db.execute(
        select(NodeType)
        .join(ComponentSlot, ComponentSlot.parent_type_id == NodeType.id)
        .where(ComponentSlot.child_type_id == type_id)
        .distinct()
        .order_by(NodeType.display_order)
    ).scalars().all()
    anc = _upward_ancestor_ids(db, type_id)
    cats = []
    if anc:
        cats = db.execute(
            select(NodeType)
            .where(NodeType.id.in_(anc), NodeType.is_sellable_root.is_(True))
            .order_by(NodeType.display_order)
        ).scalars().all()

    def _ref(p: NodeType) -> ParentRefOut:
        return ParentRefOut(id=p.id, name=p.name, is_active=p.is_active)

    return NodeTypeParentsOut(
        direct=[_ref(p) for p in direct],
        root_categories=[_ref(p) for p in cats],
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
    if data.get("variant_group") is not None:
        data["variant_group"] = data["variant_group"].strip() or None
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
    # 互斥组允许显式清空：传空串 → NULL
    if "variant_group" in body.model_fields_set and body.variant_group is not None:
        body.variant_group = body.variant_group.strip() or None
        if body.variant_group is None:
            slot.variant_group = None
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


# ---------- C dry-run：编辑前影响面预演 ----------

_IMPACT_MODELS = {
    "node_type": NodeType, "attribute": AttributeDef,
    "slot": ComponentSlot, "option": AttributeOption,
}
# 仅这些收紧/停用类布尔变更可能把既有完整 SKU 变成残货，才值得预演
_IMPACT_FIELDS = {"is_active", "is_required"}


@router.post("/preview-impact", response_model=ImpactPreviewOut)
def preview_impact(
    body: ImpactPreviewIn,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_admin),
):
    """模板编辑 dry-run：在 savepoint 内套用拟改动 → 批量重算既有 SKU 健康 → 回滚不落库，
    统计"由完好变残货"的数量与分族。绝不持久化（红线）。复用 M1 的 compute_health。"""
    model = _IMPACT_MODELS[body.entity_type]
    bad = set(body.changes) - _IMPACT_FIELDS
    if bad:
        raise HTTPException(422, f"不支持预演的字段：{', '.join(sorted(bad))}")
    entity = get_or_404(db, model, body.entity_id)
    # 受影响的根类型：定位到该编辑作用的节点类型
    if body.entity_type == "node_type":
        tid = entity.id
    elif body.entity_type == "attribute":
        tid = entity.node_type_id
    elif body.entity_type == "option":
        tid = get_or_404(db, AttributeDef, entity.attribute_id).node_type_id
    else:  # slot：作用在其所属上级类型
        tid = entity.parent_type_id
    # 候选品类 = 该类型自身(若是可售根) + 其向上 BFS 的可售根祖先；据此收敛候选 SKU
    cat_pool = _upward_ancestor_ids(db, tid) | {tid}
    cat_ids = list(db.execute(
        select(NodeType.id)
        .where(NodeType.id.in_(cat_pool), NodeType.is_sellable_root.is_(True))
    ).scalars())
    if not cat_ids:
        return ImpactPreviewOut(candidate_count=0, newly_broken=0, by_family=ImpactFamilyCount())
    candidates = db.execute(
        select(Sku)
        .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
        .where(Sku.status == "active", Sku.root_type_id.in_(cat_ids))
    ).scalars().all()
    # 改前：哪些候选当前是完好的（只有"完好→残"才算预警的"变"）
    tc_before: dict = {}
    before_ok = {s.id for s in candidates if compute_health(db, s, tc_before).status == "ok"}

    fam = ImpactFamilyCount()
    samples: list[ImpactSample] = []
    newly = 0
    sp = db.begin_nested()  # SAVEPOINT：套用拟改动仅为重算，结束必回滚
    try:
        for field, value in body.changes.items():
            setattr(entity, field, value)
        db.flush()
        tc_after: dict = {}
        for s in candidates:
            if s.id not in before_ok:
                continue
            h = compute_health(db, s, tc_after)
            if h.status != "ok":
                newly += 1
                if h.families.completeness:
                    fam.completeness += 1
                elif h.families.structural:
                    fam.structural += 1
                else:
                    fam.supply += 1
                if len(samples) < 10:
                    samples.append(
                        ImpactSample(sku_id=s.id, sku_code=s.sku_code, status=h.status)
                    )
    finally:
        sp.rollback()  # 撤销预演，模板分毫不动
    return ImpactPreviewOut(
        candidate_count=len(candidates), newly_broken=newly, by_family=fam, samples=samples,
    )
