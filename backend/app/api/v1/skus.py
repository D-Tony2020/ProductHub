"""SKU：创建（配置落库）、检索（动态属性筛选）、详情（只读配置树+价格史）、作废/恢复、清单导出。"""
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, selectinload

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import get_current_user
from app.models import (
    AppUser,
    AttributeDef,
    NodeType,
    PurchasedPart,
    Sku,
    SkuAttributeValue,
    SkuConfigNode,
    SkuPrice,
)
from app.schemas.config import CurrentPrice
from app.schemas.sku import (
    SkuAttributeValueOut,
    SkuCreateIn,
    SkuCreateResult,
    SkuDetailOut,
    SkuHealth,
    SkuListOut,
    SkuNodeOut,
    SkuOut,
    SkuOverviewOut,
    SkuStatsOut,
    SkuUpdateIn,
    SkuUpdateResult,
)
from app.services.config_engine import _current_prices, create_sku
from app.services.graybox import summarize_spec
from app.services.health_engine import compute_health, load_sku_for_health
from app.services.template_service import get_or_404

router = APIRouter(prefix="/skus", tags=["skus"])


def _sku_out(db: Session, sku: Sku, health_status: str | None = None) -> SkuOut:
    out = SkuOut.model_validate(sku, from_attributes=True)
    out.root_type_name = sku.root_type.name if sku.root_type else ""
    out.current_prices = _current_prices(db, sku.id)
    out.health_status = health_status  # 由调用方实时推导填入（列表/详情）
    if sku.superseded_by_sku_id and sku.superseded_by:
        out.superseded_by_sku_code = sku.superseded_by.sku_code  # 血缘展示
    return out


def _node_out(db: Session, node: SkuConfigNode) -> SkuNodeOut:
    attrs = []
    for av in sorted(node.attribute_values, key=lambda v: v.attribute.display_order):
        attrs.append(
            SkuAttributeValueOut(
                attribute_id=av.attribute_id,
                option_id=av.option_id,
                attribute_code=av.attribute.code,
                attribute_name=av.attribute.name,
                option_code=av.option.code,
                option_label=av.option.label,
                option_active=av.option.is_active,
            )
        )
    part = node.purchased_part
    # 来源：黑盒由成品件供应商派生；白盒由节点级供应商标注（方案甲）
    if part is not None:
        supplier_id, supplier_name = part.supplier_id, part.supplier.name
    elif node.supplier_id is not None:
        supplier_id, supplier_name = node.supplier_id, node.supplier.name if node.supplier else None
    else:
        supplier_id, supplier_name = None, None
    return SkuNodeOut(
        id=node.id,
        slot_id=node.slot_id,
        slot_code=node.slot.code if node.slot else None,
        slot_name=node.slot.name if node.slot else None,
        node_type_id=node.node_type_id,
        node_type_code=db.get(NodeType, node.node_type_id).code,
        node_type_name=db.get(NodeType, node.node_type_id).name,
        mode=node.mode,
        purchased_part_id=part.id if part else None,
        purchased_part_name=part.name if part else None,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        part_spec_note=part.spec_note if part else None,
        part_spec_summary=summarize_spec(db, part.spec_config) if part else "",
        attributes=attrs,
        children=[
            _node_out(db, c)
            for c in sorted(node.children, key=lambda c: (c.slot.display_order if c.slot else 0))
        ],
    )


@router.post("", response_model=SkuCreateResult, status_code=201)
def create(
    body: SkuCreateIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    sku, created = create_sku(db, body.config, created_by=user.id)
    if created:
        write_audit(db, actor_id=user.id, action="create", entity_type="sku",
                    entity_id=sku.id, after={"sku_code": sku.sku_code,
                                             "fingerprint": sku.fingerprint})
    db.commit()
    return SkuCreateResult(created=created, sku=_sku_out(db, sku))


@router.get("", response_model=SkuListOut)
def search(
    q: str | None = Query(default=None, max_length=200),
    root_type_id: int | None = None,
    status: str | None = Query(default=None, pattern=r"^(active|retired|pending_price|incomplete)$"),
    option_id: list[int] = Query(default=[]),
    purchased_part_id: int | None = None,
    supplier_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    mine: bool = False,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    stmt = select(Sku)
    if mine:
        stmt = stmt.where(Sku.created_by == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Sku.sku_code.ilike(like) | Sku.name.ilike(like))
    if root_type_id is not None:
        stmt = stmt.where(Sku.root_type_id == root_type_id)
    if status == "pending_price":
        # 待录价 = active 且无现行价（推导态，无冗余状态字段）
        stmt = stmt.where(
            Sku.status == "active",
            ~Sku.id.in_(select(sql_text("sku_id")).select_from(sql_text("v_sku_current_price"))),
        )
    elif status == "incomplete":
        # 残货 = active 且健康检测非 ok（实时推导，无法 SQL 下推，末尾特殊处理）
        stmt = stmt.where(Sku.status == "active")
    elif status is not None:
        stmt = stmt.where(Sku.status == status)
    for oid in option_id:
        # 每个选中的选项都要求 SKU 配置树中存在该取值（跨节点 AND 语义）
        stmt = stmt.where(
            Sku.id.in_(
                select(SkuConfigNode.sku_id)
                .join(SkuAttributeValue, SkuAttributeValue.config_node_id == SkuConfigNode.id)
                .where(SkuAttributeValue.option_id == oid)
            )
        )
    if purchased_part_id is not None:
        stmt = stmt.where(
            Sku.id.in_(
                select(SkuConfigNode.sku_id).where(
                    SkuConfigNode.purchased_part_id == purchased_part_id
                )
            )
        )
    if supplier_id is not None:
        # 按供应商分类（"出现即计入"）：SKU 配置树中任一黑盒件来自该供应商即命中。
        # 经 SkuConfigNode.purchased_part_id → PurchasedPart.supplier_id 两级关联；
        # 纯自产(无外购件)的 SKU 天然不落入任何供应商，符合设计。
        stmt = stmt.where(
            Sku.id.in_(
                select(SkuConfigNode.sku_id)
                .join(PurchasedPart, PurchasedPart.id == SkuConfigNode.purchased_part_id)
                .where(PurchasedPart.supplier_id == supplier_id)
            )
        )
    # 健康检测要遍历配置树，预取避免 N+1；type_cache 跨 SKU 复用类型查询
    stmt = stmt.options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
    type_cache: dict = {}
    if status == "incomplete":
        # 实时推导：候选 active 全量 → 算 health → 过滤残货 → Python 分页
        scored = [(s, compute_health(db, s, type_cache))
                  for s in db.execute(stmt.order_by(Sku.id.desc())).scalars().all()]
        residual = [(s, h) for s, h in scored if h.status != "ok"]
        total = len(residual)
        page_rows = residual[(page - 1) * page_size: page * page_size]
        return SkuListOut(total=total, items=[_sku_out(db, s, h.status) for s, h in page_rows])
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Sku.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return SkuListOut(
        total=total,
        items=[_sku_out(db, s, compute_health(db, s, type_cache).status) for s in rows],
    )


@router.get("/stats", response_model=SkuStatsOut)
def stats(db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """SKU 库统计带：货架口径四个数。须声明在 /skus/{sku_id} 之前以免被动态路由捕获。"""
    has_price = select(sql_text("sku_id")).select_from(sql_text("v_sku_current_price"))
    active = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", Sku.id.in_(has_price))
    ).scalar_one()
    pending = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", ~Sku.id.in_(has_price))
    ).scalar_one()
    new_week = db.execute(
        select(func.count()).select_from(Sku)
        .where(Sku.status == "active", Sku.created_at >= datetime.now() - timedelta(days=7))
    ).scalar_one()
    today = date.today()
    # 在售且"当前生效价"的生效日已满 30 天：提醒管理者复审久未动价的货
    stale = db.execute(
        select(func.count(func.distinct(SkuPrice.sku_id)))
        .select_from(SkuPrice).join(Sku, Sku.id == SkuPrice.sku_id)
        .where(
            Sku.status == "active",
            SkuPrice.valid_from <= today - timedelta(days=30),
            (SkuPrice.valid_to.is_(None)) | (SkuPrice.valid_to >= today),
        )
    ).scalar_one()
    # 待治理（残货）：在售且健康检测非 ok（红 completeness/structural + 黄 supply）
    active_skus = db.execute(
        select(Sku)
        .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
        .where(Sku.status == "active")
    ).scalars().all()
    tc: dict = {}
    incomplete = sum(1 for s in active_skus if compute_health(db, s, tc).status != "ok")
    return SkuStatsOut(active=active, pending_price=pending,
                       new_this_week=new_week, stale_30d=stale, incomplete=incomplete)


@router.get("/overview", response_model=list[SkuOverviewOut])
def overview(db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """产品全貌：按可售品类聚合（比 SKU 粗一档）。产品库首页"全貌"视图的数据源。"""
    priced_ids = set(
        db.execute(select(sql_text("sku_id")).select_from(sql_text("v_sku_current_price")))
        .scalars().all()
    )
    roots = db.execute(
        select(NodeType).where(NodeType.is_sellable_root.is_(True))
        .options(selectinload(NodeType.slots), selectinload(NodeType.attributes))
        .order_by(NodeType.display_order, NodeType.id)
    ).scalars().all()
    tc: dict = {}
    out: list[SkuOverviewOut] = []
    for rt in roots:
        skus = db.execute(
            select(Sku)
            .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
            .where(Sku.status == "active", Sku.root_type_id == rt.id)
        ).scalars().all()
        incomplete = pending = 0
        prices: list = []
        currency = None
        for s in skus:
            if compute_health(db, s, tc).status != "ok":
                incomplete += 1
            cps = _current_prices(db, s.id)
            if cps:
                for p in cps:
                    prices.append(p.price)
                    currency = p.currency
            else:
                pending += 1
        out.append(SkuOverviewOut(
            root_type_id=rt.id, root_type_name=rt.name, kind=rt.kind,
            sku_count=len(skus), incomplete=incomplete, pending_price=pending,
            price_min=min(prices) if prices else None,
            price_max=max(prices) if prices else None,
            currency=currency,
            slot_count=len([x for x in rt.slots if x.is_active]),
            attr_count=len([a for a in rt.attributes if a.is_active]),
        ))
    return out


@router.get("/export")
def export_list(
    root_type_id: int | None = None,
    db: Session = Depends(get_db),
    _: AppUser = Depends(get_current_user),
):
    """SKU 清单导出 Excel（业务员高频）。"""
    stmt = select(Sku).where(Sku.status == "active").order_by(Sku.id)
    if root_type_id is not None:
        stmt = stmt.where(Sku.root_type_id == root_type_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "SKU 清单"
    ws.append(["SKU 编码", "名称", "品类", "现价", "币种", "价格生效日", "状态"])
    for sku in db.execute(stmt).scalars():
        prices = _current_prices(db, sku.id)
        p: CurrentPrice | None = prices[0] if prices else None
        ws.append([
            sku.sku_code, sku.name, sku.root_type.name if sku.root_type else "",
            float(p.price) if p else None, p.currency if p else "",
            p.valid_from if p else "", "在售" if prices else "待录价",
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"SKU-list-{datetime.now():%Y%m%d-%H%M}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{sku_id}", response_model=SkuDetailOut)
def detail(
    sku_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)
):
    sku = db.execute(
        select(Sku)
        .where(Sku.id == sku_id)
        .options(selectinload(Sku.nodes).selectinload(SkuConfigNode.attribute_values))
    ).scalar_one_or_none()
    if sku is None:
        raise HTTPException(404, f"SKU {sku_id} 不存在")
    root = next((n for n in sku.nodes if n.parent_node_id is None), None)
    health = compute_health(db, sku)
    out = SkuDetailOut(
        **_sku_out(db, sku, health.status).model_dump(),
        config_tree=_node_out(db, root) if root else None,
        health=health,
    )
    return out


@router.get("/{sku_id}/health", response_model=SkuHealth)
def health(sku_id: int, db: Session = Depends(get_db), _: AppUser = Depends(get_current_user)):
    """SKU 在最新模板下的健康体检（三族）。实时推导、不碰指纹。"""
    sku = load_sku_for_health(db, sku_id)
    if sku is None:
        raise HTTPException(404, f"SKU {sku_id} 不存在")
    return compute_health(db, sku)


@router.post("/{sku_id}/retire", response_model=SkuOut)
def retire(
    sku_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    sku = get_or_404(db, Sku, sku_id)
    if sku.status == "retired":
        raise HTTPException(409, "SKU 已是作废状态")
    sku.status = "retired"
    write_audit(db, actor_id=user.id, action="retire", entity_type="sku",
                entity_id=sku.id, before={"status": "active"}, after={"status": "retired"})
    db.commit()
    return _sku_out(db, sku)


@router.post("/{sku_id}/restore", response_model=SkuOut)
def restore(
    sku_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)
):
    """作废恢复：同配置重配时引导恢复原 SKU 而非新建分身。"""
    sku = get_or_404(db, Sku, sku_id)
    if sku.status == "active":
        raise HTTPException(409, "SKU 已是在用状态")
    sku.status = "active"
    write_audit(db, actor_id=user.id, action="restore", entity_type="sku",
                entity_id=sku.id, before={"status": "retired"}, after={"status": "active"})
    db.commit()
    return _sku_out(db, sku)


@router.post("/{sku_id}/update", response_model=SkuUpdateResult, status_code=201)
def update_config(
    sku_id: int,
    body: SkuUpdateIn,
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """修改既有 SKU 配置（M2-B 治理闭环）：绝不原地改（会变指纹），而是生成一个新 SKU、
    旧 SKU 留痕指向新 SKU，并按 retire_old 决定旧 SKU 停用还是保活（保活=仍可报价，只记血缘）。
    新配置不完整 → 422（沿用 create 同闸）；与原 SKU 完全相同 → 409（无修改）。"""
    old = get_or_404(db, Sku, sku_id)
    if old.status != "active" or old.superseded_at is not None:
        raise HTTPException(409, f"SKU {old.sku_code} 已作废或已被取代，不可再修改")
    new_sku, created = create_sku(db, body.config, created_by=user.id)
    if new_sku.id == old.id:
        # 指纹不变=没有实质修改，不产生血缘（杜绝自指与噪声）
        raise HTTPException(409, "新配置与原 SKU 完全相同，未发生任何修改")
    if not created and new_sku.status == "retired":
        # 改成了某个已作废配置 → 用户主动重新采纳，复活之（避免指向死链）
        new_sku.status = "active"
    old.superseded_by_sku_id = new_sku.id
    old.superseded_at = datetime.now()
    if body.retire_old:
        old.status = "retired"
    write_audit(
        db, actor_id=user.id, action="supersede", entity_type="sku", entity_id=old.id,
        before={"sku_code": old.sku_code, "status": "active"},
        after={"superseded_by": new_sku.sku_code, "new_sku_id": new_sku.id,
               "old_status": old.status, "created_new": created},
    )
    db.commit()
    return SkuUpdateResult(
        created=created,
        new_sku=_sku_out(db, new_sku, compute_health(db, new_sku).status),
        old_sku=_sku_out(db, old),
    )
