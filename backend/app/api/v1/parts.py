"""成品采购件库与供应商。

业务员可现场新建草稿件（立即可用于配置）；admin 审核转正/合并/停用。
建档查重：同供应商+同部件类型+同名由 UNIQUE 拒绝；相似名由 pg_trgm 提示。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user, require_admin
from app.models import AppUser, NodeType, PurchasedPart, Sku, SkuConfigNode, Supplier
from app.schemas.parts import (
    LinkedSku,
    MergeIn,
    PartSpecUpdate,
    PurchasedPartDetailOut,
    PurchasedPartIn,
    PurchasedPartOut,
    PurchasedPartUpdate,
    SupplierCategoryCount,
    SupplierIn,
    SupplierLinkedSku,
    SupplierOut,
    SupplierOverviewOut,
    SupplierUpdate,
)
from app.services.codes import next_code
from app.services.config_engine import resync_names_for_part
from app.services.graybox import summarize_spec
from app.services.template_service import get_or_404

router = APIRouter(tags=["parts"])


def _ref_counts(db: Session, part_ids: list[int]) -> dict[int, int]:
    """一次 GROUP BY 批量取多件的被引用 SKU 数，替代逐件 COUNT 子查询的 N+1。"""
    if not part_ids:
        return {}
    return dict(db.execute(
        select(SkuConfigNode.purchased_part_id, func.count())
        .where(SkuConfigNode.purchased_part_id.in_(part_ids))
        .group_by(SkuConfigNode.purchased_part_id)
    ).all())


def _part_out(db: Session, part: PurchasedPart, ref_count: int | None = None) -> PurchasedPartOut:
    out = PurchasedPartOut.model_validate(part)
    out.supplier_name = part.supplier.name if part.supplier else ""
    out.node_type_name = part.node_type.name if part.node_type else ""
    out.node_type_kind = part.node_type.kind if part.node_type else ""
    out.spec_summary = summarize_spec(db, part.spec_config)
    # 批量场景由调用方预取引用数(消 N+1)；单条场景回落到逐件 COUNT
    out.reference_count = ref_count if ref_count is not None else db.execute(
        select(func.count()).select_from(SkuConfigNode).where(
            SkuConfigNode.purchased_part_id == part.id
        )
    ).scalar_one()
    return out


# ---------- 供应商 ----------

@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    include_inactive: bool = False,
    db: Session = Depends(get_db), _: AppUser = Depends(get_current_user),
):
    stmt = select(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active.is_(True))
    return db.execute(stmt).scalars().all()


@router.get("/suppliers/overview", response_model=list[SupplierOverviewOut])
def suppliers_overview(db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """供应商 + 用量指标（采购项/整机供应/部件供应/关联在售SKU）。一次性聚合，防 N+1。"""
    suppliers = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()
    # 采购项按 整机(product)/部件(part) 分类计数
    item_rows = db.execute(text(
        "SELECT pp.supplier_id sid, nt.kind kind, count(*) c "
        "FROM purchased_part pp JOIN node_type nt ON nt.id = pp.node_type_id "
        "WHERE pp.status IN ('draft','active') GROUP BY pp.supplier_id, nt.kind"
    )).all()
    items: dict[int, dict] = {}
    for sid, kind, c in item_rows:
        items.setdefault(sid, {})[kind] = c
    # 关联在售 SKU：黑盒(经成品件)∪白盒(节点级供应商标注)，UNION 去重 (sku,supplier) 对
    sku_rows = db.execute(text(
        "SELECT supplier_id sid, count(DISTINCT sku_id) c FROM ("
        "  SELECT pp.supplier_id, scn.sku_id FROM sku_config_node scn "
        "    JOIN purchased_part pp ON pp.id = scn.purchased_part_id "
        "    JOIN sku s ON s.id = scn.sku_id AND s.status = 'active' "
        "  UNION "
        "  SELECT scn.supplier_id, scn.sku_id FROM sku_config_node scn "
        "    JOIN sku s ON s.id = scn.sku_id AND s.status = 'active' "
        "    WHERE scn.supplier_id IS NOT NULL"
        ") u GROUP BY supplier_id"
    )).all()
    skus = {sid: c for sid, c in sku_rows}
    out: list[SupplierOverviewOut] = []
    for s in suppliers:
        it = items.get(s.id, {})
        prod, part = it.get("product", 0), it.get("part", 0)
        o = SupplierOverviewOut.model_validate(s)
        o.assembly_count, o.component_count = prod, part
        o.procurement_items = prod + part
        o.linked_skus = skus.get(s.id, 0)
        out.append(o)
    return out


@router.get("/suppliers/{supplier_id}/linked-skus", response_model=list[SupplierLinkedSku])
def supplier_linked_skus(
    supplier_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    """该供应商关联的在售 SKU（黑盒经成品件 ∪ 白盒节点标注），含用法来源，供「关联成品」页下钻。
    与 overview 的 linked_skus 同口径(active SKU 去重)。"""
    get_or_404(db, Supplier, supplier_id)
    by_sku: dict[int, SupplierLinkedSku] = {}
    # 黑盒：经该供应商的成品件供货（一 SKU 可经多件 → 收集件名）
    for r in db.execute(text(
        "SELECT DISTINCT s.id sid, s.sku_code, s.name nm, s.status, pp.name part_name "
        "FROM sku_config_node scn "
        "JOIN purchased_part pp ON pp.id = scn.purchased_part_id AND pp.supplier_id = :sup "
        "JOIN sku s ON s.id = scn.sku_id AND s.status = 'active'"
    ), {"sup": supplier_id}).all():
        o = by_sku.get(r.sid)
        if o is None:
            o = SupplierLinkedSku(sku_id=r.sid, sku_code=r.sku_code, name=r.nm, status=r.status)
            by_sku[r.sid] = o
        if r.part_name not in o.via_blackbox:
            o.via_blackbox.append(r.part_name)
    # 白盒：节点直接标注该供应商
    for r in db.execute(text(
        "SELECT DISTINCT s.id sid, s.sku_code, s.name nm, s.status "
        "FROM sku_config_node scn "
        "JOIN sku s ON s.id = scn.sku_id AND s.status = 'active' "
        "WHERE scn.supplier_id = :sup"
    ), {"sup": supplier_id}).all():
        o = by_sku.get(r.sid)
        if o is None:
            o = SupplierLinkedSku(sku_id=r.sid, sku_code=r.sku_code, name=r.nm, status=r.status)
            by_sku[r.sid] = o
        o.via_whitebox = True
    return sorted(by_sku.values(), key=lambda x: x.sku_id, reverse=True)


@router.get("/suppliers/{supplier_id}/category-breakdown",
            response_model=list[SupplierCategoryCount])
def supplier_category_breakdown(
    supplier_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    """该供应商的「件目录」：按它**实际供应/标注的节点件类型(node_type)**分组，计该件类型被多少
    在售 SKU 用到（黑盒经成品件 ∪ 白盒采购来源标注·去重）。归属严格按"该件类型本身由该供应商供应"，
    不再因 SKU 某子件命中而把整机品类整只算入。按产品模板节点顺序(display_order)排列、不按数量。
    下钻同口径：count == /skus?supplier_id=&supplier_part_type_id= 的 total（数字与下钻对齐）。"""
    get_or_404(db, Supplier, supplier_id)
    rows = db.execute(text(
        "SELECT u.node_type_id, nt.name, nt.kind, count(DISTINCT u.sku_id) c "
        "FROM ("
        "  SELECT scn.sku_id, scn.node_type_id FROM sku_config_node scn "
        "    JOIN purchased_part pp ON pp.id = scn.purchased_part_id AND pp.supplier_id = :sup "
        "    JOIN sku s ON s.id = scn.sku_id AND s.status = 'active' "
        "  UNION "
        "  SELECT scn.sku_id, scn.node_type_id FROM sku_config_node scn "
        "    JOIN sku s ON s.id = scn.sku_id AND s.status = 'active' "
        "    WHERE scn.supplier_id = :sup"
        ") u JOIN node_type nt ON nt.id = u.node_type_id "
        "GROUP BY u.node_type_id, nt.name, nt.kind, nt.display_order "
        "ORDER BY nt.display_order, nt.name"
    ), {"sup": supplier_id}).all()
    return [SupplierCategoryCount(node_type_id=r[0], name=r[1], kind=r[2], count=r[3])
            for r in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(
    body: SupplierIn, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    data = body.model_dump()
    data["code"] = data["code"] or next_code(db, "SUP")  # 缺省自动生成 SUP 流水
    supplier = Supplier(**data)
    db.add(supplier)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"供应商 code 已存在：{body.code}")
    write_audit(db, actor_id=admin.id, action="create", entity_type="supplier",
                entity_id=supplier.id, after=body.model_dump())
    db.commit()
    return supplier


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int, body: SupplierUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    supplier = get_or_404(db, Supplier, supplier_id)
    before = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        before[field] = getattr(supplier, field)
        setattr(supplier, field, value)
    write_audit(db, actor_id=admin.id, action="update", entity_type="supplier",
                entity_id=supplier.id, before=before,
                after=body.model_dump(exclude_unset=True))
    db.commit()
    return supplier


# ---------- 成品采购件 ----------

@router.get("/purchased-parts", response_model=list[PurchasedPartOut])
def list_parts(
    node_type_id: int | None = None,
    supplier_id: int | None = None,
    kind: str | None = Query(default=None, pattern=r"^(product|part)$"),
    q: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern=r"^(draft|active|merged|retired)$"),
    usable_only: bool = False,
    db: Session = Depends(get_db), _: AppUser = Depends(get_current_user),
):
    stmt = select(PurchasedPart).order_by(PurchasedPart.id.desc()).limit(200)
    if node_type_id is not None:
        stmt = stmt.where(PurchasedPart.node_type_id == node_type_id)
    if kind is not None:  # 整机(product)/部件(part) 大类过滤——供 KPI「整机供应/部件供应」下钻
        stmt = stmt.where(PurchasedPart.node_type.has(NodeType.kind == kind))
    if supplier_id is not None:
        stmt = stmt.where(PurchasedPart.supplier_id == supplier_id)
    if status is not None:
        stmt = stmt.where(PurchasedPart.status == status)
    if usable_only:
        stmt = stmt.where(PurchasedPart.status.in_(("draft", "active")))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            PurchasedPart.name.ilike(like)
            | PurchasedPart.supplier.has(Supplier.name.ilike(like))
        )
    # 预取 supplier/node_type(消逐件 lazy) + 批量引用数(消逐件 COUNT)
    parts = db.execute(
        stmt.options(selectinload(PurchasedPart.supplier), selectinload(PurchasedPart.node_type))
    ).scalars().all()
    ref = _ref_counts(db, [p.id for p in parts])
    return [_part_out(db, p, ref.get(p.id, 0)) for p in parts]


@router.get("/purchased-parts/by-id/{part_id}", response_model=PurchasedPartDetailOut)
def get_part(part_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """单件详情（含灰盒规格 + 关联在售/作废 SKU 列表）。供采购件详情页与规格编辑器调用。"""
    part = get_or_404(db, PurchasedPart, part_id)
    base = _part_out(db, part)
    skus = db.execute(
        select(Sku).join(SkuConfigNode, SkuConfigNode.sku_id == Sku.id)
        .where(SkuConfigNode.purchased_part_id == part_id).distinct().order_by(Sku.id.desc())
    ).scalars().all()
    return PurchasedPartDetailOut(
        **base.model_dump(),
        linked_skus=[
            LinkedSku(id=s.id, sku_code=s.sku_code, name=s.name, status=s.status) for s in skus
        ],
    )


@router.get("/purchased-parts/similar", response_model=list[PurchasedPartOut])
def similar_parts(
    node_type_id: int,
    name: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db), _: AppUser = Depends(get_current_user),
):
    """建档查重：同部件类型下按 trigram 相似度返回近似件。"""
    rows = db.execute(
        text(
            """
            SELECT id FROM purchased_part
            WHERE node_type_id = :tid AND similarity(name, :name) > 0.25
            ORDER BY similarity(name, :name) DESC LIMIT 10
            """
        ),
        {"tid": node_type_id, "name": name},
    ).scalars().all()
    if not rows:
        return []
    parts = {p.id: p for p in db.execute(
        select(PurchasedPart)
        .options(selectinload(PurchasedPart.supplier), selectinload(PurchasedPart.node_type))
        .where(PurchasedPart.id.in_(rows))
    ).scalars()}
    ref = _ref_counts(db, list(rows))
    return [_part_out(db, parts[i], ref.get(i, 0)) for i in rows if i in parts]  # 保留 trigram 相似度序


@router.post("/purchased-parts", response_model=PurchasedPartOut, status_code=201)
def create_part(
    body: PurchasedPartIn,
    db: Session = Depends(get_db), user: AppUser = Depends(get_current_user),
):
    nt = get_or_404(db, NodeType, body.node_type_id)
    if body.supplier_id is not None:
        supplier = get_or_404(db, Supplier, body.supplier_id)
    elif body.new_supplier_name:
        # 现场新建供应商：code 走 SUP 流水
        supplier = Supplier(code=next_code(db, "SUP"), name=body.new_supplier_name)
        db.add(supplier)
        db.flush()
    else:
        raise HTTPException(422, "必须指定供应商或提供新供应商名称")

    name = " ".join(body.name.split())  # 归一化空白，降低"同名异写"重复建档
    # 参考交期：件上未给则用供应商默认交期预填（权威值仍在件上、可后续覆盖）
    lead_time = body.lead_time_days if body.lead_time_days is not None else supplier.lead_time_days
    part = PurchasedPart(
        code=next_code(db, "PP"),
        node_type_id=nt.id,
        supplier_id=supplier.id,
        name=name,
        spec_note=body.spec_note,
        lead_time_days=lead_time,
        status="draft" if user.role != "admin" else "active",
        created_by=user.id,
    )
    db.add(part)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"同供应商同部件类型下已存在同名件：{name}")
    write_audit(db, actor_id=user.id, action="create", entity_type="purchased_part",
                entity_id=part.id, after={"name": name, "supplier_id": supplier.id,
                                          "node_type_id": nt.id, "status": part.status})
    db.commit()
    return _part_out(db, part)


@router.patch("/purchased-parts/{part_id}", response_model=PurchasedPartOut)
def update_part(
    part_id: int, body: PurchasedPartUpdate,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    part = get_or_404(db, PurchasedPart, part_id)
    before = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        before[field] = getattr(part, field)
        setattr(part, field, " ".join(value.split()) if field == "name" else value)
    # 改名后同步刷新引用该件的 SKU 展示名（快照→实时对齐）；name 不入指纹，红线安全
    resynced = (resync_names_for_part(db, part.id)
                if "name" in before and before["name"] != part.name else 0)
    after = body.model_dump(exclude_unset=True)
    if resynced:
        after["name_resynced_skus"] = resynced
    write_audit(db, actor_id=admin.id, action="update", entity_type="purchased_part",
                entity_id=part.id, before=before, after=after)
    db.commit()
    return _part_out(db, part)


@router.patch("/purchased-parts/{part_id}/spec", response_model=PurchasedPartOut)
def update_part_spec(
    part_id: int, body: PartSpecUpdate,
    db: Session = Depends(get_db), user: AppUser = Depends(get_current_user),
):
    """编辑成品件的灰盒规格(spec_note/spec_config)。规格仅描述、不入指纹，故对所有登录用户开放
    (区别于改名/治理的 admin 门)，让现场建 draft 件的业务员也能补规格。"""
    part = get_or_404(db, PurchasedPart, part_id)
    if part.status not in ("draft", "active"):
        raise HTTPException(409, "已合并/停用的件不可编辑规格")
    part.spec_note = body.spec_note
    part.spec_config = body.spec_config
    write_audit(db, actor_id=user.id, action="update_spec", entity_type="purchased_part",
                entity_id=part.id,
                after={"spec_note": body.spec_note, "has_spec_config": bool(body.spec_config)})
    db.commit()
    return _part_out(db, part)


@router.post("/purchased-parts/{part_id}/approve", response_model=PurchasedPartOut)
def approve_part(
    part_id: int, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    part = get_or_404(db, PurchasedPart, part_id)
    if part.status != "draft":
        raise HTTPException(409, f"仅草稿件可转正（当前状态：{part.status}）")
    part.status = "active"
    write_audit(db, actor_id=admin.id, action="approve", entity_type="purchased_part",
                entity_id=part.id, before={"status": "draft"}, after={"status": "active"})
    db.commit()
    return _part_out(db, part)


@router.post("/purchased-parts/{part_id}/retire", response_model=PurchasedPartOut)
def retire_part(
    part_id: int, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    part = get_or_404(db, PurchasedPart, part_id)
    if part.status == "merged":
        raise HTTPException(409, "已合并件不可再停用")
    before = part.status
    part.status = "retired"
    write_audit(db, actor_id=admin.id, action="retire", entity_type="purchased_part",
                entity_id=part.id, before={"status": before}, after={"status": "retired"})
    db.commit()
    return _part_out(db, part)


@router.post("/purchased-parts/{part_id}/merge", response_model=PurchasedPartOut)
def merge_part(
    part_id: int, body: MergeIn,
    db: Session = Depends(get_db), admin: AppUser = Depends(require_admin),
):
    """标记重复：part 合并指向 target。旧 SKU 不受影响（指纹含原件 code，历史事实保留）。"""
    part = get_or_404(db, PurchasedPart, part_id)
    target = get_or_404(db, PurchasedPart, body.target_part_id)
    if part.id == target.id:
        raise HTTPException(422, "不能合并到自身")
    if target.status not in ("draft", "active"):
        raise HTTPException(409, "合并目标必须是可用件（draft/active）")
    if part.node_type_id != target.node_type_id:
        raise HTTPException(409, "只能合并同部件类型的件")
    before = part.status
    part.status = "merged"
    part.merged_into_id = target.id
    write_audit(db, actor_id=admin.id, action="merge", entity_type="purchased_part",
                entity_id=part.id, before={"status": before},
                after={"status": "merged", "merged_into_id": target.id})
    db.commit()
    return _part_out(db, part)
