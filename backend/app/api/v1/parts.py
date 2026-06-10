"""成品采购件库与供应商。

业务员可现场新建草稿件（立即可用于配置）；admin 审核转正/合并/停用。
建档查重：同供应商+同部件类型+同名由 UNIQUE 拒绝；相似名由 pg_trgm 提示。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user, require_admin
from app.models import AppUser, NodeType, PurchasedPart, SkuConfigNode, Supplier
from app.schemas.parts import (
    MergeIn,
    PurchasedPartIn,
    PurchasedPartOut,
    PurchasedPartUpdate,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
)
from app.services.codes import next_code
from app.services.template_service import get_or_404

router = APIRouter(tags=["parts"])


def _part_out(db: Session, part: PurchasedPart) -> PurchasedPartOut:
    out = PurchasedPartOut.model_validate(part)
    out.supplier_name = part.supplier.name if part.supplier else ""
    out.node_type_name = part.node_type.name if part.node_type else ""
    out.reference_count = db.execute(
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


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(
    body: SupplierIn, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    supplier = Supplier(**body.model_dump())
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
    q: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, pattern=r"^(draft|active|merged|retired)$"),
    usable_only: bool = False,
    db: Session = Depends(get_db), _: AppUser = Depends(get_current_user),
):
    stmt = select(PurchasedPart).order_by(PurchasedPart.id.desc()).limit(200)
    if node_type_id is not None:
        stmt = stmt.where(PurchasedPart.node_type_id == node_type_id)
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
    return [_part_out(db, p) for p in db.execute(stmt).scalars().all()]


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
    return [_part_out(db, db.get(PurchasedPart, i)) for i in rows]


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
    part = PurchasedPart(
        code=next_code(db, "PP"),
        node_type_id=nt.id,
        supplier_id=supplier.id,
        name=name,
        spec_note=body.spec_note,
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
    write_audit(db, actor_id=admin.id, action="update", entity_type="purchased_part",
                entity_id=part.id, before=before, after=body.model_dump(exclude_unset=True))
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
